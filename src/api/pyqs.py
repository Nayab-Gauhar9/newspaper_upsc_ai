from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import List, Optional
from pydantic import BaseModel

from src.database.session import get_db
from src.database.models import PrelimsPYQModel
from src.classifiers.taxonomy import LAXMIKANTH_8TH_EDITION, get_chapter_title

router = APIRouter(prefix="/api/v1/pyqs", tags=["Prelims PYQs"])

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
def get_chapters_catalogue(db: Session = Depends(get_db)):
    """
    Returns all 92 Laxmikanth chapters with their available PYQ question counts.
    Chapters with 0 questions are still listed so the UI shows full syllabus coverage.
    """
    counts_query = text("""
        SELECT chapter_number, COUNT(*) AS total
        FROM prelims_pyqs
        GROUP BY chapter_number;
    """)
    counts_map = {row.chapter_number: row.total for row in db.execute(counts_query).all()}

    catalogue = []
    for num, title in LAXMIKANTH_8TH_EDITION.items():
        catalogue.append(
            ChapterCatalogueItem(
                chapter_number=num,
                chapter_name=title,
                question_count=counts_map.get(num, 0)
            )
        )
    return catalogue

@router.get("/articles", response_model=List[ArticleCatalogueItem])
def get_articles_catalogue(db: Session = Depends(get_db)):
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
        
        # Categorize into realistic UPSC tiers
        if count >= 15:
            tag = "High Yield Core"
        elif count >= 8:
            tag = "Frequently Asked"
        elif count >= 4:
            tag = "Moderate Yield"
        else:
            tag = "Occasional Reference"

        result.append(
            ArticleCatalogueItem(
                article_number=row.article_no,
                display_title=f"Article {row.article_no}",
                question_count=count,
                frequency_ratio=round(max(0.12, count / max_count), 2),
                yield_tag=tag
            )
        )
    return result




# ---------------------------------------------------------
# 2. DRILL ENDPOINTS (For Quiz / Practice Screens)
# ---------------------------------------------------------

@router.get("/by-chapter/{chapter_number}", response_model=List[PYQQuestionOut])
def get_pyqs_by_chapter(
    chapter_number: int,
    db: Session = Depends(get_db)
):
    """
    Fetch all PYQs under a specific Laxmikanth Chapter (1-92).
    Sorted chronologically from newest to oldest.
    """
    if chapter_number not in LAXMIKANTH_8TH_EDITION:
        raise HTTPException(status_code=404, detail="Invalid chapter number.")

    questions = (
        db.query(PrelimsPYQModel)
        .filter(PrelimsPYQModel.chapter_number == chapter_number)
        .order_by(PrelimsPYQModel.year.desc(), PrelimsPYQModel.question_number.asc())
        .all()
    )
    return questions

@router.get("/by-article/{article_number}", response_model=List[PYQQuestionOut])
def get_pyqs_by_article(
    article_number: int,
    db: Session = Depends(get_db)
):
    """
    Fetch all PYQs testing a specific Constitutional Article (1-395).
    Leverages the PostgreSQL GIN index on mapped_articles for fast execution.
    """
    if not (1 <= article_number <= 395):
        raise HTTPException(status_code=400, detail="Article number must be between 1 and 395.")

    # High-speed GIN index match: WHERE :art = ANY(mapped_articles)
    query = text("""
        SELECT * FROM prelims_pyqs
        WHERE :art = ANY(mapped_articles)
        ORDER BY year DESC, question_number ASC;
    """)
    rows = db.execute(query, {"art": article_number}).mappings().all()
    return list(rows)

@router.get("/yearly-trend")
def get_yearly_trend(db: Session = Depends(get_db)):
    """
    Returns the total number of Polity questions asked per year (1995–2026).
    Feeds directly into FlutterFlow's Line Chart or Bar Chart.
    """
    query = text("""
        SELECT year, COUNT(*) AS count
        FROM prelims_pyqs
        GROUP BY year
        ORDER BY year ASC;
    """)
    rows = db.execute(query).mappings().all()
    # Format: [{"year": 2018, "count": 13}, {"year": 2019, "count": 15}, ...]
    return list(rows)


@router.get("/top-chapters")
def get_top_chapters(
    limit: int = Query(10, ge=5, le=30),
    db: Session = Depends(get_db)
):
    """
    Returns top high-weightage Laxmikanth chapters sorted by frequency.
    Feeds directly into a Horizontal Bar Chart or Ranked List.
    """
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
    rows = db.execute(query, {"limit": limit}).mappings().all()
    return list(rows)


@router.get("/top-articles")
def get_top_articles(
    limit: int = Query(10, ge=5, le=25),
    db: Session = Depends(get_db)
):
    """
    Returns the most frequently tested Constitutional Articles.
    Feeds into Bar Chart or Top 10 badges.
    """
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
    return [{"article": f"Article {r['article_no']}", "count": r["frequency"]} for r in rows]


@router.get("/difficulty-and-nature")
def get_nature_breakdown(db: Session = Depends(get_db)):
    """
    Returns factual vs conceptual ratio and difficulty breakdown for Pie/Donut charts.
    """
    query = text("""
        SELECT 
            COUNT(*) FILTER (WHERE is_conceptual = TRUE) AS conceptual_count,
            COUNT(*) FILTER (WHERE is_conceptual = FALSE) AS factual_count,
            COUNT(*) FILTER (WHERE difficulty_level = 'Easy') AS easy_count,
            COUNT(*) FILTER (WHERE difficulty_level = 'Moderate') AS moderate_count,
            COUNT(*) FILTER (WHERE difficulty_level = 'Tough') AS tough_count
        FROM prelims_pyqs;
    """)
    row = db.execute(query).mappings().one()
    return dict(row)
