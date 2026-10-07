from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, or_, desc, func, text
from sqlalchemy.orm import Session, selectinload

from src.database.session import SessionLocal
from src.database.models import IssueDossierModel, IssueGraphEdgeModel
from src.schema.issues import (
    IssueDossierSummaryOut,
    IssueDossierDetailOut,
    GraphEdgeOut,
    PrelimsDrillItemOut,
)
import json
from collections import defaultdict
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
from src.api.schemas import ChapterDossierGroup, DossierSummaryItem
# Use your existing DB dependency/pool imported in issues.py
from src.database.session import get_db
router = APIRouter(prefix="/api/issues", tags=["Topic Evolution Engine"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/by-chapter", response_model=List[ChapterDossierGroup])
def get_dossiers_grouped_by_chapter(db: Session = Depends(get_db)):
    """
    Returns all active and historical dossiers grouped by syllabus chapter
    for the FlutterFlow ChapterDirectoryPage.
    """
    # 1. Query using SQLAlchemy ORM directly (no raw SQL / colon escaping issues)
    stmt = (
        select(IssueDossierModel)
        .order_by(IssueDossierModel.chapter_name.asc(), IssueDossierModel.last_updated_at.desc())
    )
    dossiers = db.scalars(stmt).all()

    if not dossiers:
        return []

    # 2. Group records by chapter_name
    grouped_data = defaultdict(list)
    for d in dossiers:
        chapter = d.chapter_name or "General Constitutional Issues"
        
        # Extract fields from ORM model safely
        mains_data = d.mains_framework or {}
        mains_hook = mains_data.get("introduction_hook") if isinstance(mains_data, dict) else None

        factsheet_data = d.prelims_factsheet or {}
        raw_articles = factsheet_data.get("constitutional_articles", []) if isinstance(factsheet_data, dict) else []
        
        if isinstance(raw_articles, str):
            try:
                articles = json.loads(raw_articles)
            except Exception:
                articles = [raw_articles]
        elif isinstance(raw_articles, list):
            articles = raw_articles
        else:
            articles = []

        item = DossierSummaryItem(
            issue_id=str(d.issue_id),
            issue_slug=d.issue_slug,
            title=d.title,
            status=d.status or "active",
            article_count=d.article_count or 1,
            mains_hook=mains_hook,
            constitutional_articles=articles,
            last_updated_at=d.last_updated_at.isoformat() if d.last_updated_at else None,
        )
        grouped_data[chapter].append(item)

    return [
        ChapterDossierGroup(
            chapter_name=chap,
            total_dossiers=len(items),
            dossiers=items,
        )
        for chap, items in grouped_data.items()
    ]



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


@router.get(
    "/{issue_slug}",
    response_model=IssueDossierDetailOut,
    summary="Get complete topic dossier with chronological perspective matrix",
)
def get_dossier_detail(issue_slug: str, db: Session = Depends(get_db)):
    """Fetches the master dossier and all connected chronological graph edges (sources, viewpoints, legal anchors)."""
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
    """Lightweight endpoint returning strictly the sequential development steps and citations for visual timelines."""
    stmt = (
        select(IssueGraphEdgeModel)
        .where(IssueGraphEdgeModel.issue_slug == issue_slug.strip().lower())
        .order_by(IssueGraphEdgeModel.event_date.asc(), IssueGraphEdgeModel.created_at.asc())
    )
    edges = db.scalars(stmt).all()

    if not edges:
        # Check if dossier exists at all
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

