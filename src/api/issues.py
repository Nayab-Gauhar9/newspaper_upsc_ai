# src/api/routes/issues.py
import json
import os
import time
import zoneinfo
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
import requests
from sqlalchemy import select, or_, desc, func
from sqlalchemy.orm import Session, selectinload

from src.database.session import SessionLocal, get_db
from src.database.models import IssueDossierModel, IssueGraphEdgeModel
from src.schema.issues import (
    IssueDossierSummaryOut,
    IssueDossierDetailOut,
    GraphEdgeOut,
    PrelimsDrillItemOut,
)
from src.api.schemas import ChapterDossierGroup, DossierSummaryItem
from src.storage.redis_cache import get_redis_cache

router = APIRouter(prefix="/api/issues", tags=["Topic Evolution Engine"])

# Cache Lifespans
CACHE_TTL_2_HOURS = 7200
CACHE_TTL_TODAY = 600       # 10 minutes TTL
CACHE_TTL_DOSSIER = 86400   # 24 hours TTL

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
UTC = zoneinfo.ZoneInfo("UTC")

# Cloudflare Invalidation Credentials
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")


# ─────────────────────────────────────────────────────────────
# Cache Invalidation Helpers
# ─────────────────────────────────────────────────────────────
def purge_cloudflare_dossier_edge(issue_slug: str):
    """Instructs Cloudflare Edge in Mumbai to purge cached responses for this dossier."""
    if not (CLOUDFLARE_ZONE_ID and CLOUDFLARE_API_TOKEN):
        return

    url = f"https://api.cloudflare.com/client/v4/zones/{CLOUDFLARE_ZONE_ID}/purge_cache"
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "files": [
            f"https://politymentor.com/api/issues/{issue_slug}",
            f"https://politymentor.com/api/issues/{issue_slug}/timeline",
            "https://politymentor.com/api/issues/updated-today?limit=10",
            "https://politymentor.com/api/issues/chapters/summary",
        ]
    }

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        print(f"[*] Cloudflare edge purged ({issue_slug}): status {res.status_code}")
    except Exception as e:
        print(f"[!] Cloudflare purge failed for {issue_slug}: {e}")


def invalidate_dossier_cache(issue_slug: str, r_cache):
    """Evicts Redis keys and triggers a Cloudflare Edge purge when a dossier evolves."""
    normalized_slug = issue_slug.strip().lower()

    if r_cache:
        keys_to_purge = [
            f"dossier:detail:{normalized_slug}",
            f"dossier:timeline:{normalized_slug}",
            "dossiers:feed:updated-today:10",
            "dossiers:chapters:summary",
        ]

        try:
            r_cache.delete(*keys_to_purge)

            # Evict chapter groupings
            cursor = 0
            while True:
                cursor, keys = r_cache.scan(cursor=cursor, match="dossiers:by-chapter:*", count=50)
                if keys:
                    r_cache.delete(*keys)
                if cursor == 0:
                    break

            # Evict top lists
            cursor = 0
            while True:
                cursor, keys = r_cache.scan(cursor=cursor, match="dossiers:list:*", count=50)
                if keys:
                    r_cache.delete(*keys)
                if cursor == 0:
                    break

            print(f"[*] Successfully evicted Redis cache for dossier: {normalized_slug}")
        except Exception as e:
            print(f"[!] Redis invalidation warning: {e}")

    # Purge Cloudflare Edge cache
    purge_cloudflare_dossier_edge(normalized_slug)


# ─────────────────────────────────────────────────────────────
# Utility Serialization
# ─────────────────────────────────────────────────────────────
def get_ist_today_utc_bounds():
    """Calculates IST 00:00:00 to 23:59:59 converted to UTC timestamps for DB queries."""
    now_ist = datetime.now(IST)
    start_ist = datetime.combine(now_ist.date(), dtime.min, tzinfo=IST)
    end_ist = datetime.combine(now_ist.date(), dtime.max, tzinfo=IST)
    return start_ist.astimezone(UTC), end_ist.astimezone(UTC)


def _serialize_dossier_item(d: IssueDossierModel) -> dict:
    """Safely extracts model fields and nested JSON structures matching Neon schema."""
    mains_data = d.mains_framework or {}
    mains_hook = (
        mains_data.get("introduction_hook")
        if isinstance(mains_data, dict)
        else None
    )

    factsheet_data = d.prelims_factsheet or {}
    raw_articles = (
        factsheet_data.get("constitutional_articles", [])
        if isinstance(factsheet_data, dict)
        else []
    )

    if isinstance(raw_articles, str):
        try:
            articles = json.loads(raw_articles)
        except Exception:
            articles = [raw_articles]
    elif isinstance(raw_articles, list):
        articles = raw_articles
    else:
        articles = []

    return {
        "issue_id": str(d.issue_id),
        "issue_slug": d.issue_slug,
        "title": d.title,
        "status": d.status or "active",
        "article_count": d.article_count or 1,
        "canonical_summary": d.canonical_summary,
        "mains_hook": mains_hook,
        "constitutional_articles": articles,
        "last_updated_at": (
            d.last_updated_at.isoformat() if d.last_updated_at else None
        ),
    }


# ─────────────────────────────────────────────────────────────
# 1. HOMEPAGE HORIZONTAL CAROUSEL ENDPOINT
# ─────────────────────────────────────────────────────────────
@router.get("/updated-today", response_model=List[DossierSummaryItem])
def get_dossiers_updated_today(
    response: Response,
    limit: int = Query(10, ge=1, le=30),
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """
    Returns dossiers that evolved today in IST.
    If 0 exist today, gracefully falls back to the top 5 most recently updated dossiers.
    """
    cache_key = f"dossiers:feed:updated-today:{limit}"
    start_time = time.perf_counter()

    # 1. Check Redis Cache
    if r_cache:
        try:
            cached_data = r_cache.get(cache_key)
            if cached_data:
                duration_ms = (time.perf_counter() - start_time) * 1000
                response.headers["Cache-Control"] = f"public, max-age={CACHE_TTL_TODAY}, s-maxage={CACHE_TTL_TODAY}, stale-while-revalidate=60"
                response.headers["X-Cache"] = "HIT"
                response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
                return json.loads(cached_data)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    # 2. Query Today's Dossiers using IST bounds
    start_utc, end_utc = get_ist_today_utc_bounds()

    stmt = (
        select(IssueDossierModel)
        .where(
            IssueDossierModel.last_updated_at >= start_utc,
            IssueDossierModel.last_updated_at <= end_utc,
        )
        .order_by(desc(IssueDossierModel.last_updated_at))
        .limit(limit)
    )
    dossiers = db.scalars(stmt).all()

    # 3. Fallback to latest 5 if today has no updates
    is_fallback = False
    if not dossiers:
        is_fallback = True
        fallback_stmt = (
            select(IssueDossierModel)
            .order_by(desc(IssueDossierModel.last_updated_at))
            .limit(5)
        )
        dossiers = db.scalars(fallback_stmt).all()

    results = [_serialize_dossier_item(d) for d in dossiers]

    # 4. Populate Redis Cache
    if r_cache:
        try:
            r_cache.setex(
                name=cache_key,
                time=CACHE_TTL_TODAY,
                value=json.dumps(results),
            )
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["Cache-Control"] = f"public, max-age={CACHE_TTL_TODAY}, s-maxage={CACHE_TTL_TODAY}, stale-while-revalidate=60"
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Fallback"] = str(is_fallback).lower()
    response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

    return results


# ─────────────────────────────────────────────────────────────
# 2. BY-CHAPTER ENDPOINT (SUPPORTS 'today', 'active', 'closed')
# ─────────────────────────────────────────────────────────────
@router.get("/by-chapter", response_model=List[ChapterDossierGroup])
def get_dossiers_grouped_by_chapter(
    response: Response,
    status_filter: Optional[str] = Query(
        None, description="Filter by status: 'today', 'active', 'closed', 'settled', 'resolved', or None for all"
    ),
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    start_time = time.perf_counter()
    normalized_status = (status_filter or "all").strip().lower()
    cache_key = f"dossiers:by-chapter:{normalized_status}"
    ttl = CACHE_TTL_TODAY if normalized_status == "today" else CACHE_TTL_2_HOURS

    # 1. Attempt Redis Read
    if r_cache:
        try:
            cached_data = r_cache.get(cache_key)
            if cached_data:
                duration_ms = (time.perf_counter() - start_time) * 1000
                response.headers["Cache-Control"] = f"public, max-age=300, s-maxage={ttl}, stale-while-revalidate=120"
                response.headers["X-Cache"] = "HIT"
                response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
                return json.loads(cached_data)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    # 2. Database Fallback (Cache Miss)
    stmt = select(IssueDossierModel)

    if normalized_status == "today":
        start_utc, end_utc = get_ist_today_utc_bounds()
        stmt = stmt.where(
            IssueDossierModel.last_updated_at >= start_utc,
            IssueDossierModel.last_updated_at <= end_utc,
        )
    elif normalized_status in ["week", "last_7_days", "weekly"]:
        now_utc = datetime.now(UTC)
        seven_days_ago_utc = now_utc - timedelta(days=7)
        stmt = stmt.where(IssueDossierModel.last_updated_at >= seven_days_ago_utc)
    elif normalized_status != "all":
        if normalized_status in ["closed", "settled", "resolved"]:
            stmt = stmt.where(
                IssueDossierModel.status.in_(["closed", "settled", "resolved"])
            )
        else:
            stmt = stmt.where(IssueDossierModel.status == normalized_status)

    stmt = stmt.order_by(
        IssueDossierModel.chapter_name.asc(),
        IssueDossierModel.last_updated_at.desc(),
    )
    dossiers = db.scalars(stmt).all()

    if not dossiers:
        duration_ms = (time.perf_counter() - start_time) * 1000
        response.headers["Cache-Control"] = "public, max-age=60"
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
        return []

    # 3. Group records by chapter_name
    grouped_data = defaultdict(list)
    for d in dossiers:
        chapter = d.chapter_name or "General Constitutional Issues"
        grouped_data[chapter].append(_serialize_dossier_item(d))

    response_payload = [
        {
            "chapter_name": chap,
            "total_dossiers": len(items),
            "dossiers": items,
        }
        for chap, items in grouped_data.items()
    ]

    # 4. Save to Redis
    if r_cache:
        try:
            r_cache.setex(
                name=cache_key,
                time=ttl,
                value=json.dumps(response_payload),
            )
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["Cache-Control"] = f"public, max-age=300, s-maxage={ttl}, stale-while-revalidate=120"
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
    return response_payload


# ─────────────────────────────────────────────────────────────
# 3. OTHER ISSUE ENDPOINTS
# ─────────────────────────────────────────────────────────────
@router.get(
    "/",
    response_model=List[IssueDossierSummaryOut],
    summary="List all evolving constitutional dossiers",
)
def list_dossiers(
    response: Response,
    chapter_name: Optional[str] = Query(
        None, description="Filter by Laxmikanth chapter (e.g. 'Supreme Court')"
    ),
    status_filter: Optional[str] = Query(
        None, description="Filter by status: 'active', 'dormant', 'resolved'"
    ),
    search: Optional[str] = Query(
        None, description="Search keyword in title or summary"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """Returns a list of living topic dossiers ordered by latest update."""
    cache_key = f"dossiers:list:chap={chapter_name or 'all'}:stat={status_filter or 'all'}:skip={skip}:lim={limit}"

    if not search and r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=300, s-maxage=3600, stale-while-revalidate=120"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception:
            pass

    stmt = select(IssueDossierModel)

    if chapter_name:
        stmt = stmt.where(IssueDossierModel.chapter_name.ilike(f"%{chapter_name.strip()}%"))

    if status_filter:
        stmt = stmt.where(IssueDossierModel.status == status_filter.strip().lower())

    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                IssueDossierModel.title.ilike(term),
                IssueDossierModel.canonical_summary.ilike(term),
                IssueDossierModel.issue_slug.ilike(term),
            )
        )

    stmt = stmt.order_by(desc(IssueDossierModel.last_updated_at)).offset(skip).limit(limit)
    items = db.scalars(stmt).all()

    serialized = [IssueDossierSummaryOut.model_validate(i).model_dump(mode="json") for i in items]

    if not search and r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_2_HOURS, json.dumps(serialized))
        except Exception:
            pass

    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=3600, stale-while-revalidate=120"
    response.headers["X-Cache"] = "MISS"
    return serialized


@router.get(
    "/prelims/drills",
    response_model=List[PrelimsDrillItemOut],
    summary="Get recent Prelims True/False statements across all active dossiers",
)
def get_prelims_drills(
    response: Response,
    limit: int = Query(20, ge=1, le=50),
    chapter_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """Flattens recent edge prelims_statements into an interactive drill feed."""
    cache_key = f"dossiers:drills:lim={limit}:chap={chapter_name or 'all'}"
    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=300, s-maxage=1800, stale-while-revalidate=60"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception:
            pass

    stmt = (
        select(IssueGraphEdgeModel, IssueDossierModel.title, IssueDossierModel.chapter_name)
        .join(IssueDossierModel, IssueGraphEdgeModel.issue_slug == IssueDossierModel.issue_slug)
        .where(IssueGraphEdgeModel.prelims_event_facts.isnot(None))
        .order_by(desc(IssueGraphEdgeModel.event_date), desc(IssueGraphEdgeModel.created_at))
    )

    if chapter_name:
        stmt = stmt.where(IssueDossierModel.chapter_name.ilike(f"%{chapter_name.strip()}%"))

    results = db.execute(stmt.limit(limit * 2)).all()

    drills = []
    for edge, title, chapter in results:
        facts = edge.prelims_event_facts or {}
        statements = facts.get("prelims_statements") or []
        for s in statements:
            if "statement" in s and s.get("statement"):
                item = PrelimsDrillItemOut(
                    issue_slug=edge.issue_slug,
                    dossier_title=title,
                    chapter_name=chapter,
                    publication=edge.publication,
                    event_date=edge.event_date,
                    statement=s.get("statement"),
                    is_correct=bool(s.get("is_correct")),
                    explanation=s.get("explanation", ""),
                    provisions_invoked=facts.get("provisions_invoked", []),
                )
                drills.append(item.model_dump(mode="json"))
            if len(drills) >= limit:
                break
        if len(drills) >= limit:
            break

    if r_cache:
        try:
            r_cache.setex(cache_key, 1800, json.dumps(drills))
        except Exception:
            pass

    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=1800, stale-while-revalidate=60"
    response.headers["X-Cache"] = "MISS"
    return drills


@router.get(
    "/chapters/summary",
    summary="Get count of dossiers grouped by Laxmikanth chapter",
)
def get_chapters_summary(
    response: Response,
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """Provides high-level chapter statistics for category browsing."""
    cache_key = "dossiers:chapters:summary"
    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=300"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception:
            pass

    stmt = (
        select(
            IssueDossierModel.chapter_name,
            func.count(IssueDossierModel.issue_id).label("total_dossiers"),
            func.max(IssueDossierModel.last_updated_at).label("latest_update"),
        )
        .group_by(IssueDossierModel.chapter_name)
        .order_by(desc("total_dossiers"))
    )
    rows = db.execute(stmt).all()
    payload = [
        {
            "chapter_name": r.chapter_name,
            "total_dossiers": r.total_dossiers,
            "latest_update": r.latest_update.isoformat() if r.latest_update else None,
        }
        for r in rows
    ]

    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_DOSSIER, json.dumps(payload))
        except Exception:
            pass

    response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=300"
    response.headers["X-Cache"] = "MISS"
    return payload


@router.get(
    "/{issue_slug}",
    response_model=IssueDossierDetailOut,
    summary="Get complete topic dossier with chronological perspective matrix",
)
def get_dossier_detail(
    issue_slug: str,
    response: Response,
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """Fetches master dossier and all connected edges with Redis + Cloudflare edge caching."""
    normalized_slug = issue_slug.strip().lower()
    cache_key = f"dossier:detail:{normalized_slug}"

    # 1. Fast Path: In-memory Redis (~15ms)
    if r_cache:
        try:
            cached_data = r_cache.get(cache_key)
            if cached_data:
                response.headers["Cache-Control"] = "public, max-age=300, s-maxage=86400, stale-while-revalidate=600"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached_data)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    # 2. Slow Path: Neon DB Query
    stmt = (
        select(IssueDossierModel)
        .where(IssueDossierModel.issue_slug == normalized_slug)
        .options(selectinload(IssueDossierModel.edges))
    )
    dossier = db.scalars(stmt).first()

    if not dossier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue dossier '{issue_slug}' was not found.",
        )

    # 3. Serialize and save to Redis (24 Hours)
    payload = IssueDossierDetailOut.model_validate(dossier).model_dump(mode="json")
    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_DOSSIER, json.dumps(payload))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    # 4. Instruct Cloudflare Edge to cache for 24h
    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=86400, stale-while-revalidate=600"
    response.headers["X-Cache"] = "MISS"
    return payload


@router.get(
    "/{issue_slug}/timeline",
    response_model=List[GraphEdgeOut],
    summary="Get purely chronological perspective timeline",
)
def get_dossier_timeline(
    issue_slug: str,
    response: Response,
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """Lightweight endpoint returning sequential development steps and citations."""
    normalized_slug = issue_slug.strip().lower()
    cache_key = f"dossier:timeline:{normalized_slug}"

    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=300, s-maxage=86400, stale-while-revalidate=600"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception:
            pass

    stmt = (
        select(IssueGraphEdgeModel)
        .where(IssueGraphEdgeModel.issue_slug == normalized_slug)
        .order_by(IssueGraphEdgeModel.event_date.asc(), IssueGraphEdgeModel.created_at.asc())
    )
    edges = db.scalars(stmt).all()

    if not edges:
        exists = db.scalar(
            select(IssueDossierModel.issue_id).where(
                IssueDossierModel.issue_slug == normalized_slug
            )
        )
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Issue dossier '{issue_slug}' was not found.",
            )

    payload = [GraphEdgeOut.model_validate(e).model_dump(mode="json") for e in edges]
    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_DOSSIER, json.dumps(payload))
        except Exception:
            pass

    response.headers["Cache-Control"] = "public, max-age=300, s-maxage=86400, stale-while-revalidate=600"
    response.headers["X-Cache"] = "MISS"
    return payload


# ─────────────────────────────────────────────────────────────
# 4. INVALIDATION WEBHOOK / INTERNAL ADMIN ROUTE
# ─────────────────────────────────────────────────────────────
@router.post(
    "/{issue_slug}/purge-cache",
    summary="Purge Redis and Cloudflare edge cache when a dossier is updated",
    status_code=status.HTTP_200_OK,
)
def purge_dossier(
    issue_slug: str,
    r_cache=Depends(get_redis_cache),
):
    """Can be called directly by your daily news ingestion pipeline or admin bot."""
    invalidate_dossier_cache(issue_slug=issue_slug, r_cache=r_cache)
    return {
        "status": "purged",
        "issue_slug": issue_slug.strip().lower(),
        "timestamp": datetime.now(UTC).isoformat(),
    }