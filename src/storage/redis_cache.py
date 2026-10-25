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