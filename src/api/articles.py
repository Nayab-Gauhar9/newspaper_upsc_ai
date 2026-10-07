# src/api/routes/articles.py
import json
import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
import redis

from src.database.session import get_db
from src.database.models import ConstitutionalArticleModel, IssueDossierModel

router = APIRouter(prefix="/api/v1/articles", tags=["Constitutional Articles"])

# --- Redis Client Setup ---
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6380))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
    protocol=2
)

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
    cluster: Optional[str] = Query(None, description="Filter by doctrine cluster"),
    part: Optional[str] = Query(None, description="Filter by Part number"),
    search: Optional[str] = Query(None, description="Search article number or title"),
    session: Session = Depends(get_db),
):
    # Deterministic cache key based on query filters
    cache_key = f"articles:catalogue:cluster={cluster or 'all'}:part={part or 'all'}:search={search or 'none'}"

    # 1. Redis Cache Hit Check
    try:
        cached_data = redis_client.get(cache_key)
        if cached_data:
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
    try:
        redis_client.set(cache_key, json.dumps(response_data), ex=TTL_90_DAYS)
    except Exception as e:
        print(f"[!] Redis list cache write warning: {e}")

    return response_data


@router.get("/{slug}", response_model=ArticleDetailResponse)
def get_article_detail(
    slug: str,
    session: Session = Depends(get_db),
):
    cache_key = f"article:detail:{slug}"

    # 1. Redis Cache Hit Check
    try:
        cached_detail = redis_client.get(cache_key)
        if cached_detail:
            return json.loads(cached_detail)
    except Exception as e:
        print(f"[!] Redis detail cache read warning: {e}")

    # 2. Fetch Master Article from PostgreSQL
    stmt = select(ConstitutionalArticleModel).where(ConstitutionalArticleModel.article_slug == slug)
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
    try:
        redis_client.set(cache_key, json.dumps(response_payload), ex=TTL_90_DAYS)
    except Exception as e:
        print(f"[!] Redis detail cache write warning: {e}")

    return response_payload
