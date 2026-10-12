import os
import re
import hashlib
from urllib.parse import urlparse, urlunparse
from typing import Optional
import redis
from dotenv import load_dotenv

load_dotenv()

SOURCE_PREFIX_MAP = {
    "the_hindu": "TH",
    "indian_express": "IE",
    "livelaw": "LL",
    "bar_and_bench": "BB",
    "prsindia": "PRS",
    "scobserver": "SCO",
    "pib": "PIB",
}


class DeduplicationManager:
    def __init__(self, namespace: Optional[str] = "newspaper"):
        self.namespace = namespace or "newspaper"
        
        redis_url = os.getenv("REDIS_URL")
        try:
            if redis_url:
                self.r = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    protocol=2,
                )
            else:
                host = os.getenv("REDIS_HOST", "127.0.0.1")
                port = int(os.getenv("REDIS_PORT", "6379"))
                db = int(os.getenv("REDIS_DB", "0"))
                self.r = redis.Redis(
                    host=host,
                    port=port,
                    db=db,
                    decode_responses=True,
                    socket_connect_timeout=1,
                    protocol=2,
                )
        except Exception as e:
            print(f"[WARN] Failed to initialize Redis in DeduplicationManager: {e}")
            self.r = None

        self.url_set_key = f"{self.namespace}:seen_urls"
        self.title_set_key = f"{self.namespace}:seen_titles"

    @staticmethod
    def canonicalize_url(raw_url: str) -> str:
        """Strips query parameters (utm_*, ref, etc.) and fragments."""
        p = urlparse(raw_url.strip())
        clean_path = p.path.rstrip("/")
        return urlunparse((p.scheme.lower(), p.netloc.lower(), clean_path, "", "", ""))

    @staticmethod
    def normalize_title(title: str) -> str:
        """Removes punctuation and whitespace to catch identical cross-feed titles."""
        clean = re.sub(r"[^\w\s]", "", title.lower())
        return " ".join(clean.split())

    def generate_id(self, clean_url: str, publication: str = None) -> str:
        raw_hash = hashlib.md5(clean_url.encode("utf-8")).hexdigest()[:12]
        prefix = SOURCE_PREFIX_MAP.get(publication, "DOC") if publication else ""
        return f"{prefix}_{raw_hash}" if prefix else raw_hash

    def is_duplicate(self, raw_url: str, raw_title: str) -> tuple[bool, str]:
        """
        Checks Redis for duplicate URL or title.
        Returns (is_duplicate: bool, reason: str).
        """
        if not self.r:
            return False, ""

        clean_url = self.canonicalize_url(raw_url)
        normalized_title = self.normalize_title(raw_title)

        try:
            if self.r.sismember(self.url_set_key, clean_url):
                return True, "URL already processed"

            if normalized_title and self.r.sismember(self.title_set_key, normalized_title):
                return True, "Title already exists in another category/feed"

            return False, ""
        except redis.RedisError as e:
            print(f"[WARN] Redis check failed: {e}. Defaulting to non-duplicate.")
            return False, ""

    def mark_as_seen(self, raw_url: str, raw_title: str):
        """Records the canonical URL and normalized title into Redis sets."""
        if not self.r:
            return

        clean_url = self.canonicalize_url(raw_url)
        normalized_title = self.normalize_title(raw_title)

        try:
            pipe = self.r.pipeline()
            pipe.sadd(self.url_set_key, clean_url)
            if normalized_title:
                pipe.sadd(self.title_set_key, normalized_title)
            pipe.execute()
        except redis.RedisError as e:
            print(f"[WARN] Failed to write seen keys to Redis: {e}")