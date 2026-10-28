from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.database.models import ContentReport, User


# ============================================================================
# 1. Pydantic Schemas
# ============================================================================
class ContentReportCreate(BaseModel):
    firebase_uid: str = Field(..., max_length=128, description="Firebase UID of reporting user")
    issue_category: str = Field(..., max_length=64, description="Category of reported issue")
    source_page: str = Field(..., max_length=128, description="Origin page or component")
    flagged_content: Optional[str] = Field(None, description="Problematic AI response snippet or text")
    user_feedback: str = Field(..., min_length=3, description="Student's explanation of the issue")
    metadata_info: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Model, prompt, or article metadata")


class ContentReportResponse(BaseModel):
    id: int
    firebase_uid: str
    issue_category: str
    source_page: str
    flagged_content: Optional[str]
    user_feedback: str
    metadata_info: Optional[Dict[str, Any]]
    status: str
    created_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================================
# 2. FastAPI Route Handler
# ============================================================================
router = APIRouter(prefix="/api/reports", tags=["Content Reports"])


@router.post(
    "",
    response_model=ContentReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a content discrepancy report",
)
def submit_content_report(
    report_in: ContentReportCreate,
    db: Session = Depends(get_db),
):
    # Synchronous query — no await
    user_check = db.scalar(
        select(User).where(User.firebase_uid == report_in.firebase_uid)
    )
    if not user_check:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not registered in platform database.",
        )

    new_report = ContentReport(
        firebase_uid=report_in.firebase_uid,
        issue_category=report_in.issue_category,
        source_page=report_in.source_page,
        flagged_content=report_in.flagged_content,
        user_feedback=report_in.user_feedback,
        metadata_info=report_in.metadata_info or {},
        status="PENDING",
    )

    db.add(new_report)
    db.commit()
    db.refresh(new_report)
    return new_report


@router.get(
    "/user/{firebase_uid}",
    response_model=List[ContentReportResponse],
    summary="Get report history for a specific student",
)
def get_user_reports(
    firebase_uid: str,
    db: Session = Depends(get_db),
):
    # Synchronous query — no await
    query = (
        select(ContentReport)
        .where(ContentReport.firebase_uid == firebase_uid)
        .order_by(desc(ContentReport.created_at))
    )
    result = db.scalars(query)
    return result.all()
