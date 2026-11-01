# src/api/routes/daily_challenge.py
import json
import time
from datetime import date, datetime, timezone, timedelta, time as dtime
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, Query, HTTPException, Response
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from src.database.session import get_db
from src.database.models import DailyChallengeModel
from src.services.daily_challenge import get_or_create_daily_challenge
from src.storage.redis_cache import get_redis_cache

router = APIRouter(prefix="/daily-challenge", tags=["Daily Challenge"])

IST = timezone(timedelta(hours=5, minutes=30))


def get_current_ist_date() -> date:
    return datetime.now(IST).date()


def get_seconds_until_ist_midnight() -> int:
    """Calculates remaining seconds until 23:59:59 IST to cleanly expire today's drill cache."""
    now_ist = datetime.now(IST)
    midnight_ist = datetime.combine(now_ist.date() + timedelta(days=1), dtime.min, tzinfo=IST)
    seconds_remaining = int((midnight_ist - now_ist).total_seconds())
    return max(seconds_remaining, 300)


@router.get("/today")
async def get_today_daily_challenge(
    response: Response,
    target_date: Optional[date] = Query(
        default=None,
        description="Optional custom date in YYYY-MM-DD. Defaults to today's date IST.",
    ),
    db: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    """
    Fetches the 15 static MCQs for today (or a specific date).
    If not already in the DB, triggers LLM generation and persists it.
    Cached in Upstash Redis and Cloudflare edge to prevent repeated Neon execution.
    """
    start_time = time.perf_counter()
    today_ist = get_current_ist_date()
    drill_date = target_date or today_ist
    is_today = drill_date == today_ist

    cache_key = f"daily_challenge:drill:{drill_date.isoformat()}"

    # 1. Fast Path: In-memory Redis Cache
    if r_cache:
        try:
            cached_data = r_cache.get(cache_key)
            if cached_data:
                duration_ms = (time.perf_counter() - start_time) * 1000
                edge_ttl = 3600 if is_today else 2592000
                response.headers["Cache-Control"] = f"public, max-age=300, s-maxage={edge_ttl}, stale-while-revalidate=60"
                response.headers["X-Cache"] = "HIT"
                response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
                return json.loads(cached_data)
        except Exception as e:
            print(f"[!] Redis read error for {cache_key}: {e}")

    # 2. Slow Path: Fetch or Generate from Service / Neon
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

    payload = {
        "status": "success",
        "challenge_id": str(full_challenge.id),
        "challenge_date": full_challenge.challenge_date.isoformat(),
        "title": full_challenge.title,
        "total_questions": full_challenge.total_questions,
        "questions": formatted_questions,
    }

    # 3. Save to Redis
    # Today's challenge expires at midnight IST; historical dates get 30 days TTL
    ttl_seconds = get_seconds_until_ist_midnight() if is_today else (30 * 24 * 60 * 60)
    if r_cache:
        try:
            r_cache.setex(cache_key, ttl_seconds, json.dumps(payload))
        except Exception as e:
            print(f"[!] Redis write error for {cache_key}: {e}")

    # 4. Attach Cache-Control Headers for Cloudflare Edge
    edge_ttl = 3600 if is_today else 2592000
    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["Cache-Control"] = f"public, max-age=300, s-maxage={edge_ttl}, stale-while-revalidate=60"
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

    return payload