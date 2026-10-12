from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import json
import os
from fastapi import APIRouter, HTTPException, Query, Response
from src.storage.minio_client import NewspaperStorage

router = APIRouter(prefix="/api/v1/daily-press", tags=["Daily Current Affairs"])
storage = NewspaperStorage()

IST = timezone(timedelta(hours=5, minutes=30))

# ------------------------------------------------------------------------------
# Redis Cache Setup (with graceful in-memory fallback)
# ------------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = None

try:
    import redis
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
except Exception:
    redis_client = None

# In-memory dictionary fallback if Redis isn't running
_MEMORY_CACHE: Dict[str, tuple[float, Any]] = {}

def get_cache(key: str) -> Optional[Any]:
    if redis_client:
        try:
            val = redis_client.get(key)
            return json.loads(val) if val else None
        except Exception:
            pass
    # In-memory fallback
    item = _MEMORY_CACHE.get(key)
    if item:
        expires_at, data = item
        if datetime.now().timestamp() < expires_at:
            return data
        del _MEMORY_CACHE[key]
    return None

def set_cache(key: str, data: Any, ttl_seconds: int = 1800):
    if redis_client:
        try:
            redis_client.setex(key, ttl_seconds, json.dumps(data))
            return
        except Exception:
            pass
    # In-memory fallback
    expires_at = datetime.now().timestamp() + ttl_seconds
    _MEMORY_CACHE[key] = (expires_at, data)


# ------------------------------------------------------------------------------
# Routes with Caching
# ------------------------------------------------------------------------------

@router.get("/notes")
def get_daily_smart_notes(
    response: Response,
    target_date: Optional[str] = Query(
        None,
        description="Date in YYYY-MM-DD format (e.g. 2026-10-12). Defaults to today IST.",
    ),
) -> Dict[str, Any]:
    """
    Fetches smart notes partitioned by publication and section.
    Results are cached in Redis/memory to prevent repeated MinIO scans.
    """
    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    query_date = target_date or today_ist
    cache_key = f"daily_press:notes:{query_date}"

    # 1. Check Cache
    cached_data = get_cache(cache_key)
    if cached_data:
        # Client-side caching header
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "HIT"
        return cached_data

    # 2. Cache Miss: Query MinIO
    base_prefix = "daily_press/"
    all_objects = storage.list_objects(prefix=base_prefix)

    date_match = f"/{query_date}/"
    note_keys = [
        k for k in all_objects
        if date_match in k and "/smart_notes/" in k and k.endswith(".json")
    ]

    the_hindu_national: List[Dict[str, Any]] = []
    the_hindu_opinion: List[Dict[str, Any]] = []
    indian_express_articles: List[Dict[str, Any]] = []

    for key in sorted(note_keys):
        note = storage.get_json(key)
        if not note:
            continue

        pub = note.get("publication", "")
        cat = note.get("category", "")

        if pub == "the_hindu" and cat == "national":
            the_hindu_national.append(note)
        elif pub == "the_hindu":
            the_hindu_opinion.append(note)
        elif pub == "indian_express":
            indian_express_articles.append(note)

    total_count = (
        len(the_hindu_national)
        + len(the_hindu_opinion)
        + len(indian_express_articles)
    )

    result = {
        "status": "success",

        "date": query_date,
        "counts": {
            "total": total_count,
            "the_hindu_national": len(the_hindu_national),
            "the_hindu_opinion": len(the_hindu_opinion),
            "indian_express": len(indian_express_articles),
        },
        "sections": {
            "the_hindu_national": the_hindu_national,
            "the_hindu_opinion": the_hindu_opinion,
            "indian_express": indian_express_articles,
        },
    }

    # 3. Store in Cache
    # If it's a past date, cache for 24 hours (86400s) since historical data won't change.
    # If it's today's date, cache for 5 minutes (300s) to catch fresh morning syntheses.
    ttl = 300 if query_date == today_ist else 86400
    set_cache(cache_key, result, ttl_seconds=ttl)

    response.headers["Cache-Control"] = f"public, max-age={ttl}"
    response.headers["X-Cache"] = "MISS"
    return result


@router.get("/notes/{article_id}")
def get_single_daily_note(
    article_id: str,
    response: Response,
) -> Dict[str, Any]:
    """Fetches a specific smart note by article_id with caching."""
    cache_key = f"daily_press:note:{article_id}"

    # 1. Check Cache
    cached_note = get_cache(cache_key)
    if cached_note:
        response.headers["Cache-Control"] = "public, max-age=86400"
        response.headers["X-Cache"] = "HIT"
        return cached_note

    # 2. MinIO Lookup
    all_objects = storage.list_objects(prefix="daily_press/")
    target_file = f"smart_notes_{article_id}.json"

    for key in all_objects:
        if key.endswith(target_file) and "/smart_notes/" in key:
            payload = storage.get_json(key)
            if payload:
                result = {"status": "success", "note": payload}
                # A synthesized note never changes: cache for 24 hours
                set_cache(cache_key, result, ttl_seconds=86400)
                response.headers["Cache-Control"] = "public, max-age=86400"
                response.headers["X-Cache"] = "MISS"
                return result

    raise HTTPException(
        status_code=404,
        detail=f"Smart note for article_id '{article_id}' not found.",
    )
