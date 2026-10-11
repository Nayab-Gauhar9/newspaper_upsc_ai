from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from src.database.session import get_db
from src.database.models import QuestionReport, User
from src.schema.qreport import QuestionReportCreate, QuestionReportResponse

router = APIRouter(prefix="/api/v1/drill", tags=["Drill Reports"])

@router.post(
    "/report-issue",
    response_model=QuestionReportResponse,
    status_code=status.HTTP_201_CREATED
)
def report_question_issue(
    payload: QuestionReportCreate,
    db: Session = Depends(get_db)
):
    # Verify user exists using firebase_uid (String), matching the frontend ID
    user = db.scalar(select(User).where(User.firebase_uid == payload.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with identifier '{payload.user_id}' does not exist."
        )

    try:
        report = QuestionReport(
            user_id=payload.user_id,
            drill_date=payload.drill_date,
            question_index=payload.question_index,
            question_text=payload.question_text,
            issue_type=payload.issue_type,
            user_notes=payload.user_notes,
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return report

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error saving report: {str(e)}"
        )
