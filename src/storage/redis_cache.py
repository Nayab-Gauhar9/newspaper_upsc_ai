import os
import redis
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

redis_url = os.getenv("REDIS_URL")
try:
    if redis_url:
        redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            protocol=2,
        )
    else:
        host = os.getenv("REDIS_HOST", "127.0.0.1")
        port = int(os.getenv("REDIS_PORT", "6379"))
        db = int(os.getenv("REDIS_DB", "0"))
        redis_client = redis.Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=True,
            socket_connect_timeout=1,
            protocol=2,
        )
except Exception as e:
    print(f"[WARN] Failed to initialize Redis Cache: {e}")
    redis_client = None


def get_redis_cache() -> Optional[redis.Redis]:
    return redis_client

def delete_cached_key(key: str) -> bool:
    """Instantly evicts a single specific cache key from Redis."""
    try:
        if redis_client:
            redis_client.delete(key)
            return True
    except Exception as e:
        print(f"[CACHE DELETE ERROR] {key}: {e}")
    return False


def delete_cached_pattern(pattern: str) -> int:
    """
    Safely finds and deletes all keys matching a wildcard pattern (e.g. 'articles:*').
    Uses SCAN so it doesn't lock Upstash Redis in production.
    """
    if not redis_client:
        return 0

    deleted_count = 0
    try:
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                redis_client.delete(*keys)
                deleted_count += len(keys)
            if cursor == 0:
                break
    except Exception as e:
        print(f"[CACHE PATTERN DELETE ERROR] {pattern}: {e}")

    return deleted_count