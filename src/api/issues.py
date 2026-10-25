import json
import time
import zoneinfo
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
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

CACHE_TTL_2_HOURS = 7200
CACHE_TTL_TODAY = 600  # 10 minutes TTL

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
UTC = zoneinfo.ZoneInfo("UTC")


def get_ist_today_utc_bounds():
    """Calculates IST 00:00:00 to 23:59:59 converted to UTC timestamps for DB queries."""
    now_ist = datetime.now(IST)
    start_ist = datetime.combine(now_ist.date(), dtime.min, tzinfo=IST)
    end_ist = datetime.combine(now_ist.date(), dtime.max, tzinfo=IST)
    return start_ist.astimezone(UTC), end_ist.astimezone(UTC)


def _serialize_dossier_item(d: IssueDossierModel) -> dict:
    """Helper to safely extract model fields and nested JSON structures matching Neon schema."""
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
                print(f"\033[92m[REDIS HIT]\033[0m Key: {cache_key} ({duration_ms:.2f}ms)")
                response.headers["X-Cache"] = "HIT"
                response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
                return json.loads(cached_data)
        except Exception as e:
            print(f"\033[91m[REDIS ERROR]\033[0m Cache read failed for {cache_key}: {e}")

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
        print("\033[93m[FALLBACK TRIGGERED]\033[0m 0 dossiers updated today. Fetching latest 5 recent dossiers.")
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
            print(f"\033[94m[REDIS SET]\033[0m Key: {cache_key} (TTL: {CACHE_TTL_TODAY}s, Fallback: {is_fallback})")
        except Exception as e:
            print(f"\033[91m[REDIS ERROR]\033[0m Cache write failed for {cache_key}: {e}")

    duration_ms = (time.perf_counter() - start_time) * 1000
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

    # 1. Attempt Redis Read
    if r_cache:
        try:
            cached_data = r_cache.get(cache_key)
            if cached_data:
                duration_ms = (time.perf_counter() - start_time) * 1000
                print(f"\033[92m[REDIS HIT]\033[0m Key: {cache_key} ({duration_ms:.2f}ms)")
                response.headers["X-Cache"] = "HIT"
                response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
                return json.loads(cached_data)
        except Exception as e:
            print(f"\033[91m[REDIS ERROR]\033[0m Failed reading {cache_key}: {e}")

    # 2. Database Fallback (Cache Miss)
    print(f"\033[93m[REDIS MISS]\033[0m Querying PostgreSQL for key: {cache_key}...")
    response.headers["X-Cache"] = "MISS"

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
    ttl = CACHE_TTL_TODAY if normalized_status == "today" else CACHE_TTL_2_HOURS
    if r_cache:
        try:
            r_cache.setex(
                name=cache_key,
                time=ttl,
                value=json.dumps(response_payload),
            )
            print(f"\033[94m[REDIS SET]\033[0m Key: {cache_key} (TTL: {ttl}s)")
        except Exception as e:
            print(f"\033[91m[REDIS ERROR]\033[0m Failed saving {cache_key}: {e}")

    duration_ms = (time.perf_counter() - start_time) * 1000
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
):
    """Returns a list of living topic dossiers ordered by latest update."""
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
    return db.scalars(stmt).all()


@router.get(
    "/prelims/drills",
    response_model=List[PrelimsDrillItemOut],
    summary="Get recent Prelims True/False statements across all active dossiers",
)
def get_prelims_drills(
    limit: int = Query(20, ge=1, le=50),
    chapter_name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Flattens recent edge prelims_statements into an interactive drill feed."""
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
                drills.append(
                    PrelimsDrillItemOut(
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
                )
            if len(drills) >= limit:
                break
        if len(drills) >= limit:
            break

    return drills


@router.get(
    "/chapters/summary",
    summary="Get count of dossiers grouped by Laxmikanth chapter",
)
def get_chapters_summary(db: Session = Depends(get_db)):
    """Provides high-level chapter statistics for category browsing."""
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
    return [
        {
            "chapter_name": r.chapter_name,
            "total_dossiers": r.total_dossiers,
            "latest_update": r.latest_update,
        }
        for r in rows
    ]


@router.get(
    "/{issue_slug}",
    response_model=IssueDossierDetailOut,
    summary="Get complete topic dossier with chronological perspective matrix",
)
def get_dossier_detail(issue_slug: str, db: Session = Depends(get_db)):
    """Fetches the master dossier and all connected chronological graph edges."""
    stmt = (
        select(IssueDossierModel)
        .where(IssueDossierModel.issue_slug == issue_slug.strip().lower())
        .options(selectinload(IssueDossierModel.edges))
    )
    dossier = db.scalars(stmt).first()

    if not dossier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Issue dossier '{issue_slug}' was not found.",
        )
    return dossier


@router.get(
    "/{issue_slug}/timeline",
    response_model=List[GraphEdgeOut],
    summary="Get purely chronological perspective timeline",
)
def get_dossier_timeline(issue_slug: str, db: Session = Depends(get_db)):
    """Lightweight endpoint returning sequential development steps and citations."""
    stmt = (
        select(IssueGraphEdgeModel)
        .where(IssueGraphEdgeModel.issue_slug == issue_slug.strip().lower())
        .order_by(IssueGraphEdgeModel.event_date.asc(), IssueGraphEdgeModel.created_at.asc())
    )
    edges = db.scalars(stmt).all()

    if not edges:
        exists = db.scalar(
            select(IssueDossierModel.issue_id).where(
                IssueDossierModel.issue_slug == issue_slug.strip().lower()
            )
        )
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Issue dossier '{issue_slug}' was not found.",
            )
    return edges