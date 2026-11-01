# src/api/routes/articles.py
import json
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.database.models import ConstitutionalArticleModel, IssueDossierModel
from src.storage.redis_cache import get_redis_cache

router = APIRouter(prefix="/api/v1/articles", tags=["Constitutional Articles"])

# 90 days TTL (3 months)
TTL_90_DAYS = 90 * 24 * 60 * 60


# --- Pydantic Schemas ---
class ArticleListItem(BaseModel):
    article_number: str
    article_slug: str
    title: str
    part_number: str
    doctrine_cluster_id: Optional[str] = None

    class Config:
        from_attributes = True


class LinkedDossierItem(BaseModel):
    issue_slug: str
    title: str
    chapter_name: str
    article_count: int

    class Config:
        from_attributes = True


class BareActClauseAnalysis(BaseModel):
    clause: str = Field(..., description="e.g. 'Clause (1) — Union Executive Takeover'")
    verbatim_snippet: str = Field(..., description="Excerpt of statutory text")
    explanation: str = Field(..., description="Operational and constitutional breakdown")
    critical_nuance: str = Field(..., description="Judicial bounds, traps, or procedural requirements")

    class Config:
        from_attributes = True


class ArticleDetailResponse(BaseModel):
    article_number: str
    article_slug: str
    title: str
    part_number: str
    doctrine_cluster_id: Optional[str] = None
    verbatim_text: str
    bare_act_analysis: List[BareActClauseAnalysis] = Field(default_factory=list)
    aspirant_summary: Dict[str, Any]
    evolution_trajectory: Dict[str, Any]
    comparative_matrix: Optional[Dict[str, Any]] = None
    linked_dossiers: List[LinkedDossierItem] = Field(default_factory=list)

    class Config:
        from_attributes = True


# --- Endpoints ---
@router.get("", response_model=List[ArticleListItem])
def list_articles(
    response: Response,
    cluster: Optional[str] = Query(None, description="Filter by doctrine cluster"),
    part: Optional[str] = Query(None, description="Filter by Part number"),
    search: Optional[str] = Query(None, description="Search article number or title"),
    session: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    start_time = time.perf_counter()
    cache_key = f"articles:catalogue:cluster={cluster or 'all'}:part={part or 'all'}:search={search or 'none'}"

    # 1. Redis Cache Hit Check
    if r_cache:
        try:
            cached_data = r_cache.get(cache_key)
            if cached_data:
                duration_ms = (time.perf_counter() - start_time) * 1000
                response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=7776000, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
                return json.loads(cached_data)
        except Exception as e:
            print(f"[!] Redis list cache read warning: {e}")

    # 2. Database Query
    stmt = select(ConstitutionalArticleModel)
    if cluster:
        stmt = stmt.where(ConstitutionalArticleModel.doctrine_cluster_id == cluster)
    if part:
        stmt = stmt.where(ConstitutionalArticleModel.part_number == part)
    if search:
        search_filter = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                ConstitutionalArticleModel.article_number.ilike(search_filter),
                ConstitutionalArticleModel.title.ilike(search_filter),
            )
        )

    stmt = stmt.order_by(ConstitutionalArticleModel.id.asc())
    result = session.execute(stmt)
    articles = result.scalars().all()

    response_data = [
        {
            "article_number": a.article_number,
            "article_slug": a.article_slug,
            "title": a.title,
            "part_number": a.part_number,
            "doctrine_cluster_id": a.doctrine_cluster_id,
        }
        for a in articles
    ]

    # 3. Store in Redis with 90-day TTL
    if r_cache:
        try:
            r_cache.set(cache_key, json.dumps(response_data), ex=TTL_90_DAYS)
        except Exception as e:
            print(f"[!] Redis list cache write warning: {e}")

    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=7776000, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
    return response_data


@router.get("/{slug}", response_model=ArticleDetailResponse)
def get_article_detail(
    slug: str,
    response: Response,
    session: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    start_time = time.perf_counter()
    clean_slug = slug.strip().lower()
    cache_key = f"article:detail:{clean_slug}"

    # 1. Redis Cache Hit Check
    if r_cache:
        try:
            cached_detail = r_cache.get(cache_key)
            if cached_detail:
                duration_ms = (time.perf_counter() - start_time) * 1000
                response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=7776000, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
                return json.loads(cached_detail)
        except Exception as e:
            print(f"[!] Redis detail cache read warning: {e}")

    # 2. Fetch Master Article from PostgreSQL
    stmt = select(ConstitutionalArticleModel).where(ConstitutionalArticleModel.article_slug == clean_slug)
    result = session.execute(stmt)
    article = result.scalar_one_or_none()

    if not article:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Constitutional article '{slug}' not found.",
        )

    # 3. Reverse-query living dossiers citing this article
    target_json = {"constitutional_articles": [article.article_number]}
    dossier_stmt = (
        select(IssueDossierModel)
        .where(IssueDossierModel.prelims_factsheet.contains(target_json))
        .order_by(IssueDossierModel.last_updated_at.desc())
    )

    dossiers = session.execute(dossier_stmt).scalars().all()
    linked_dossiers = [
        {
            "issue_slug": d.issue_slug,
            "title": d.title,
            "chapter_name": d.chapter_name,
            "article_count": d.article_count,
        }
        for d in dossiers
    ]

    response_payload = {
        "article_number": article.article_number,
        "article_slug": article.article_slug,
        "title": article.title,
        "part_number": article.part_number,
        "doctrine_cluster_id": article.doctrine_cluster_id,
        "verbatim_text": article.verbatim_text,
        "bare_act_analysis": article.bare_act_analysis or [],
        "aspirant_summary": article.aspirant_summary or {},
        "evolution_trajectory": article.evolution_trajectory or {},
        "comparative_matrix": article.comparative_matrix or {},
        "linked_dossiers": linked_dossiers,
    }

    # 4. Cache Article Detail in Redis with 90-day TTL
    if r_cache:
        try:
            r_cache.set(cache_key, json.dumps(response_payload), ex=TTL_90_DAYS)
        except Exception as e:
            print(f"[!] Redis detail cache write warning: {e}")

    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=7776000, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
    return response_payload