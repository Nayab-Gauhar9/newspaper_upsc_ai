# src/api/routes/pyqs.py
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.database.models import PrelimsPYQModel
from src.classifiers.taxonomy import LAXMIKANTH_8TH_EDITION
from src.storage.redis_cache import get_redis_cache

router = APIRouter(prefix="/api/v1/pyqs", tags=["Prelims PYQs"])

CACHE_TTL_PYQ_30_DAYS = 30 * 24 * 60 * 60  # 30 days
CACHE_TTL_PYQ_7_DAYS = 7 * 24 * 60 * 60    # 7 days


# ---------------------------------------------------------
# Pydantic Schemas for Structured FlutterFlow Responses
# ---------------------------------------------------------
class PYQQuestionOut(BaseModel):
    id: int
    year: int
    question_number: int
    question_text: str
    options: dict
    correct_option: str
    chapter_number: int
    chapter_name: str
    mapped_articles: List[int]
    explanation: Optional[str] = None
    difficulty_level: Optional[str] = "Moderate"
    is_conceptual: bool = False

    class Config:
        from_attributes = True


class ChapterCatalogueItem(BaseModel):
    chapter_number: int
    chapter_name: str
    question_count: int


class ArticleCatalogueItem(BaseModel):
    article_number: int
    display_title: str
    question_count: int
    frequency_ratio: float
    yield_tag: str


# ---------------------------------------------------------
# 1. CATALOGUE ENDPOINTS (For FlutterFlow Selector Screens)
# ---------------------------------------------------------

@router.get("/chapters", response_model=List[ChapterCatalogueItem])
def get_chapters_catalogue(
    response: Response,
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """
    Returns all 92 Laxmikanth chapters with their available PYQ question counts.
    Chapters with 0 questions are still listed so the UI shows full syllabus coverage.
    """
    cache_key = "pyqs:catalogue:chapters"

    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    counts_query = text("""
        SELECT chapter_number, COUNT(*) AS total
        FROM prelims_pyqs
        GROUP BY chapter_number;
    """)
    counts_map = {row.chapter_number: row.total for row in db.execute(counts_query).all()}

    catalogue = []
    for num, title in LAXMIKANTH_8TH_EDITION.items():
        catalogue.append(
            {
                "chapter_number": num,
                "chapter_name": title,
                "question_count": counts_map.get(num, 0),
            }
        )

    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_PYQ_30_DAYS, json.dumps(catalogue))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    return catalogue


@router.get("/articles", response_model=List[ArticleCatalogueItem])
def get_articles_catalogue(
    response: Response,
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    cache_key = "pyqs:catalogue:articles"

    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    query = text("""
        SELECT unnest(mapped_articles) AS article_no, COUNT(*) AS count
        FROM prelims_pyqs
        GROUP BY article_no
        ORDER BY count DESC, article_no ASC;
    """)
    rows = db.execute(query).all()

    if not rows:
        return []

    max_count = float(rows[0].count) if rows[0].count > 0 else 1.0

    result = []
    for row in rows:
        count = row.count

        if count >= 15:
            tag = "High Yield Core"
        elif count >= 8:
            tag = "Frequently Asked"
        elif count >= 4:
            tag = "Moderate Yield"
        else:
            tag = "Occasional Reference"

        result.append(
            {
                "article_number": row.article_no,
                "display_title": f"Article {row.article_no}",
                "question_count": count,
                "frequency_ratio": round(max(0.12, count / max_count), 2),
                "yield_tag": tag,
            }
        )

    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_PYQ_30_DAYS, json.dumps(result))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    return result


# ---------------------------------------------------------
# 2. DRILL ENDPOINTS (For Quiz / Practice Screens)
# ---------------------------------------------------------

@router.get("/by-chapter/{chapter_number}", response_model=List[PYQQuestionOut])
def get_pyqs_by_chapter(
    chapter_number: int,
    response: Response,
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """
    Fetch all PYQs under a specific Laxmikanth Chapter (1-92).
    Sorted chronologically from newest to oldest.
    """
    if chapter_number not in LAXMIKANTH_8TH_EDITION:
        raise HTTPException(status_code=404, detail="Invalid chapter number.")

    cache_key = f"pyqs:by-chapter:{chapter_number}"

    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=604800, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    questions = (
        db.query(PrelimsPYQModel)
        .filter(PrelimsPYQModel.chapter_number == chapter_number)
        .order_by(PrelimsPYQModel.year.desc(), PrelimsPYQModel.question_number.asc())
        .all()
    )

    payload = [PYQQuestionOut.model_validate(q).model_dump(mode="json") for q in questions]

    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_PYQ_7_DAYS, json.dumps(payload))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=604800, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    return payload


@router.get("/by-article/{article_number}", response_model=List[PYQQuestionOut])
def get_pyqs_by_article(
    article_number: int,
    response: Response,
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """
    Fetch all PYQs testing a specific Constitutional Article (1-395).
    Leverages PostgreSQL GIN index and Redis for caching.
    """
    if not (1 <= article_number <= 395):
        raise HTTPException(status_code=400, detail="Article number must be between 1 and 395.")

    cache_key = f"pyqs:by-article:{article_number}"

    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=604800, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    query = text("""
        SELECT * FROM prelims_pyqs
        WHERE :art = ANY(mapped_articles)
        ORDER BY year DESC, question_number ASC;
    """)
    rows = db.execute(query, {"art": article_number}).mappings().all()
    payload = [dict(r) for r in rows]

    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_PYQ_7_DAYS, json.dumps(payload))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=604800, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    return payload


@router.get("/yearly-trend")
def get_yearly_trend(
    response: Response,
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """
    Returns total Polity questions asked per year (1995–2026).
    Feeds directly into FlutterFlow Line/Bar Charts.
    """
    cache_key = "pyqs:trends:yearly"

    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    query = text("""
        SELECT year, COUNT(*) AS count
        FROM prelims_pyqs
        GROUP BY year
        ORDER BY year ASC;
    """)
    rows = [dict(r) for r in db.execute(query).mappings().all()]

    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_PYQ_30_DAYS, json.dumps(rows))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    return rows


@router.get("/top-chapters")
def get_top_chapters(
    response: Response,
    limit: int = Query(10, ge=5, le=30),
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """
    Returns top high-weightage Laxmikanth chapters sorted by frequency.
    """
    cache_key = f"pyqs:trends:top-chapters:{limit}"

    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    query = text("""
        SELECT 
            chapter_number, 
            chapter_name, 
            COUNT(*) AS count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM prelims_pyqs), 1) AS percentage
        FROM prelims_pyqs
        GROUP BY chapter_number, chapter_name
        ORDER BY count DESC
        LIMIT :limit;
    """)
    rows = [dict(r) for r in db.execute(query, {"limit": limit}).mappings().all()]

    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_PYQ_30_DAYS, json.dumps(rows))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    return rows


@router.get("/top-articles")
def get_top_articles(
    response: Response,
    limit: int = Query(10, ge=5, le=25),
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """
    Returns the most frequently tested Constitutional Articles.
    """
    cache_key = f"pyqs:trends:top-articles:{limit}"

    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    query = text("""
        SELECT 
            unnest(mapped_articles) AS article_no, 
            COUNT(*) AS frequency
        FROM prelims_pyqs
        GROUP BY article_no
        ORDER BY frequency DESC
        LIMIT :limit;
    """)
    rows = db.execute(query, {"limit": limit}).mappings().all()
    payload = [{"article": f"Article {r['article_no']}", "count": r["frequency"]} for r in rows]

    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_PYQ_30_DAYS, json.dumps(payload))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    return payload


@router.get("/difficulty-and-nature")
def get_nature_breakdown(
    response: Response,
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """
    Returns factual vs conceptual ratio and difficulty breakdown for Pie/Donut charts.
    """
    cache_key = "pyqs:trends:nature-breakdown"

    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    query = text("""
        SELECT 
            COUNT(*) FILTER (WHERE is_conceptual = TRUE) AS conceptual_count,
            COUNT(*) FILTER (WHERE is_conceptual = FALSE) AS factual_count,
            COUNT(*) FILTER (WHERE difficulty_level = 'Easy') AS easy_count,
            COUNT(*) FILTER (WHERE difficulty_level = 'Moderate') AS moderate_count,
            COUNT(*) FILTER (WHERE difficulty_level = 'Tough') AS tough_count
        FROM prelims_pyqs;
    """)
    row = dict(db.execute(query).mappings().one())

    if r_cache:
        try:
            r_cache.setex(cache_key, CACHE_TTL_PYQ_30_DAYS, json.dumps(row))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    response.headers["Cache-Control"] = "public, max-age=86400, s-maxage=2592000, stale-while-revalidate=86400"
    response.headers["X-Cache"] = "MISS"
    return row