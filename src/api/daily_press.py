from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import json
import os
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from src.storage.minio_client import NewspaperStorage

router = APIRouter(prefix="/api/v1/daily-press", tags=["Daily Current Affairs"])
storage = NewspaperStorage()

IST = timezone(timedelta(hours=5, minutes=30))
DAILY_PRESS_PREFIX = "daily_press/"

PUBLICATION_DISPLAY_MAP = {
    "indian_express": "INDIAN EXPRESS",
    "the_hindu": "THE HINDU",
}

def format_publication(pub: Optional[str]) -> str:
    if not pub:
        return ""
    cleaned = pub.strip().lower()
    return PUBLICATION_DISPLAY_MAP.get(cleaned, cleaned.replace("_", " ").upper())

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

def delete_cache_key(key: str):
    if redis_client:
        try:
            redis_client.delete(key)
        except Exception:
            pass
    if key in _MEMORY_CACHE:
        del _MEMORY_CACHE[key]

def delete_cache_pattern(pattern: str):
    if redis_client:
        try:
            keys = redis_client.keys(pattern)
            if keys:
                redis_client.delete(*keys)
        except Exception:
            pass
    keys_to_del = [k for k in _MEMORY_CACHE.keys() if pattern.replace("*", "") in k]
    for k in keys_to_del:
        del _MEMORY_CACHE[k]


# ------------------------------------------------------------------------------
# Backoffice Admin Review & Edit Endpoints
# ------------------------------------------------------------------------------

class AdminDailyPressUpdateRequest(BaseModel):
    object_key: str
    headline: Optional[str] = None
    chapter_name: Optional[str] = None
    issue_framing: Optional[str] = None
    backward_linkages: Optional[dict] = None
    thesis_affirmative: Optional[list] = None
    antithesis_critique: Optional[list] = None
    edge_case_and_unintended_consequences: Optional[str] = None
    prelims_edge_traps: Optional[list] = None
    mains_framework: Optional[dict] = None
    aspirant_blindspot: Optional[str] = None
    raw_json_override: Optional[dict] = None


@router.get("/admin/queue")
def get_daily_press_admin_queue(
    limit: int = Query(250, ge=1, le=500),
    publication: Optional[str] = Query(None, description="the_hindu, indian_express, or All"),
    target_date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
) -> Dict[str, Any]:
    """
    Scans storage for daily press smart notes, extracting metadata
    and sorting by date/article_id identically to PIB Smart Notes Studio.
    """
    try:
        all_objects = storage.list_objects(prefix=DAILY_PRESS_PREFIX)
        note_keys = [
            k for k in all_objects 
            if "/smart_notes/" in k and k.endswith(".json")
        ]

        if target_date:
            note_keys = [k for k in note_keys if f"/{target_date}/" in k]

        if publication and publication.lower() != "all":
            note_keys = [k for k in note_keys if f"/{publication.lower()}/" in k]

        note_keys.sort(reverse=True)
        items = []

        for key in note_keys[:limit]:
            payload = storage.get_json(key)
            if not payload or not isinstance(payload, dict):
                continue

            headline = (
                payload.get("headline")
                or payload.get("title")
                or key.split("/")[-1].replace(".json", "")
            )

            items.append({
                "object_key": key,
                "filename": key.split("/")[-1],
                "article_id": payload.get("article_id", ""),
                "headline": headline,
                "title": payload.get("title", ""),
                "publication": payload.get("publication", "National Press"),
                "category": payload.get("category", "Current Affairs"),
                "chapter_name": payload.get("chapter_name", "Constitutional Framework"),
                "article_date": payload.get("article_date") or payload.get("published_date") or "",
                "url": payload.get("url", ""),
            })

        return {
            "status": "success",
            "total": len(items),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scan press notes: {str(e)}")


@router.get("/admin/detail")
def get_daily_press_admin_detail(
    object_key: str = Query(..., description="Storage object key"),
) -> Dict[str, Any]:
    """
    Retrieves full smart note JSON directly from storage and normalizes
    prelims_edge_traps to guarantee explicit boolean states.
    """
    try:
        data = storage.get_json(object_key)
        if not isinstance(data, dict):
            raise HTTPException(status_code=404, detail="Smart note not found in storage")

        raw_traps = data.get("prelims_edge_traps") or []
        normalized_traps = []
        for t in raw_traps:
            if isinstance(t, dict):
                normalized_traps.append({
                    "statement": t.get("statement", ""),
                    "is_correct": bool(t.get("is_correct", False)),
                    "trap_mechanism": t.get("trap_mechanism", "Conceptual Distractor"),
                    "explanation": t.get("explanation", ""),
                })
            else:
                normalized_traps.append({
                    "statement": str(t),
                    "is_correct": False,
                    "trap_mechanism": "Conceptual Distractor",
                    "explanation": "",
                })
        data["prelims_edge_traps"] = normalized_traps

        return {
            "status": "success",
            "object_key": object_key,
            "data": data,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/save")
def save_daily_press_admin_note(payload: AdminDailyPressUpdateRequest) -> Dict[str, Any]:
    """
    Overwrites the amended smart note JSON in storage using NewspaperStorage,
    preserves existing fields, and flushes Redis cache keys immediately.
    """
    try:
        current_data = {}
        try:
            existing = storage.get_json(payload.object_key)
            if isinstance(existing, dict):
                current_data = existing
        except Exception:
            current_data = {}

        if payload.raw_json_override:
            updated_data = payload.raw_json_override
        else:
            updated_data = dict(current_data)

            if payload.headline is not None:
                updated_data["headline"] = payload.headline.strip()
            if payload.chapter_name is not None:
                updated_data["chapter_name"] = payload.chapter_name.strip()
            if payload.issue_framing is not None:
                updated_data["issue_framing"] = payload.issue_framing.strip()
            if payload.backward_linkages is not None:
                updated_data["backward_linkages"] = payload.backward_linkages
            if payload.thesis_affirmative is not None:
                updated_data["thesis_affirmative"] = payload.thesis_affirmative
            if payload.antithesis_critique is not None:
                updated_data["antithesis_critique"] = payload.antithesis_critique
            if payload.edge_case_and_unintended_consequences is not None:
                updated_data["edge_case_and_unintended_consequences"] = payload.edge_case_and_unintended_consequences.strip()
            if payload.prelims_edge_traps is not None:
                updated_data["prelims_edge_traps"] = payload.prelims_edge_traps
            if payload.mains_framework is not None:
                updated_data["mains_framework"] = payload.mains_framework
            if payload.aspirant_blindspot is not None:
                updated_data["aspirant_blindspot"] = payload.aspirant_blindspot.strip()

        updated_data["last_manually_edited_at"] = datetime.utcnow().isoformat()

        # Save to storage using NewspaperStorage's native put_json
        storage.put_json(payload.object_key, updated_data)

        # Invalidate daily press cache keys
        art_date = updated_data.get("article_date")
        art_id = updated_data.get("article_id")
        if art_date:
            delete_cache_key(f"daily_press:notes:{art_date}")
        if art_id:
            delete_cache_key(f"daily_press:note:{art_id}")
        delete_cache_pattern("daily_press:*")

        return {
            "status": "success",
            "message": "Daily Press Smart Note persisted and cache purged",
            "object_key": payload.object_key,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to persist smart note: {str(e)}")


# ------------------------------------------------------------------------------
# Public Routes (Existing Structure 100% Preserved)
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
    Results are cached in Redis/memory to prevent repeated storage scans.
    """
    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    query_date = target_date or today_ist
    cache_key = f"daily_press:notes:{query_date}"

    # 1. Check Cache
    cached_data = get_cache(cache_key)
    if cached_data:
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "HIT"
        return cached_data

    # 2. Cache Miss: Query Storage
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

        raw_pub = note.get("publication", "")
        cat = note.get("category", "")

        # Normalize publication for UI display while keeping raw value accessible
        note["publication_raw"] = raw_pub
        note["publication"] = format_publication(raw_pub)

        if raw_pub == "the_hindu" and cat == "national":
            the_hindu_national.append(note)
        elif raw_pub == "the_hindu":
            the_hindu_opinion.append(note)
        elif raw_pub == "indian_express":
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

    # 2. Storage Lookup
    all_objects = storage.list_objects(prefix="daily_press/")
    target_file = f"smart_notes_{article_id}.json"

    for key in all_objects:
        if key.endswith(target_file) and "/smart_notes/" in key:
            payload = storage.get_json(key)
            if payload:
                # Format publication label
                raw_pub = payload.get("publication", "")
                payload["publication_raw"] = raw_pub
                payload["publication"] = format_publication(raw_pub)

                result = {"status": "success", "note": payload}
                set_cache(cache_key, result, ttl_seconds=86400)
                response.headers["Cache-Control"] = "public, max-age=86400"
                response.headers["X-Cache"] = "MISS"
                return result

    raise HTTPException(
        status_code=404,
        detail=f"Smart note for article_id '{article_id}' not found.",
    )