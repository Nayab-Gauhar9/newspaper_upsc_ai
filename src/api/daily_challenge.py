from datetime import date
from typing import Optional, List, Any, Dict
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from src.database.session import get_db
from src.database.models import DailyChallengeModel
from src.services.daily_challenge import get_or_create_daily_challenge

router = APIRouter(prefix="/daily-challenge", tags=["Daily Challenge"])


@router.get("/today")
async def get_today_daily_challenge(
    target_date: Optional[date] = Query(
        default=None,
        description="Optional custom date in YYYY-MM-DD. Defaults to today's date.",
    ),
    db: Session = Depends(get_db),
):
    """
    Fetches the 15 static MCQs for today (or a specific date).
    If not already in the DB, triggers LLM generation and persists it.
    Returns payload structured directly for FlutterFlow consumption.
    """
    drill_date = target_date or date.today()

    try:
        challenge = await get_or_create_daily_challenge(session=db, target_date=drill_date)
    except Exception as e:
        print(f"❌ [Error] Failed to fetch or generate daily challenge: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

    # Eager-load questions using the synchronous session
    query = (
        select(DailyChallengeModel)
        .where(DailyChallengeModel.id == challenge.id)
        .options(selectinload(DailyChallengeModel.questions))
    )
    result = db.execute(query)
    full_challenge = result.scalars().first()

    if not full_challenge:
        raise HTTPException(status_code=404, detail="Challenge record not found.")

    formatted_questions: List[Dict[str, Any]] = []
    for q in full_challenge.questions:
        formatted_questions.append({
            "id": str(q.id),
            "question_order": q.question_order,
            "archetype": q.archetype,
            "theme": q.theme,
            "primary_article_ref": q.primary_article_ref or "",
            "question_text": q.question_text,
            "statements": q.statements or [],
            "options": q.options,
            "correct_option": q.correct_option,
            "explanation": q.explanation,
            "traps_analyzed": q.traps_analyzed or "",
        })

    return {
        "status": "success",
        "challenge_id": str(full_challenge.id),
        "challenge_date": full_challenge.challenge_date.isoformat(),
        "title": full_challenge.title,
        "total_questions": full_challenge.total_questions,
        "questions": formatted_questions,
    }
