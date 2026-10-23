import os
import threading
from typing import List
from dotenv import load_dotenv
from groq import Groq

# Ensure environment variables from .env are loaded
load_dotenv()


class GroqKeyPool:
    """
    Thread-safe Round-Robin Groq Client Pool.
    Reads comma-separated keys from GROQ_API_KEYS or single GROQ_API_KEY.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._index = 0
        self.clients: List[Groq] = []  # Guarantees attribute always exists
        self._load_clients()

    def _load_clients(self):
        raw_keys = os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY", "")
        # Split by comma or newline, strip whitespace and quotes
        keys = [
            k.strip().strip("'").strip('"')
            for k in raw_keys.replace("\n", ",").split(",")
            if k.strip()
        ]

        # Deduplicate keys while preserving order
        seen = set()
        unique_keys = [k for k in keys if not (k in seen or seen.add(k))]

        if not unique_keys:
            print("[!] WARNING: No GROQ API keys found in environment.")
            self.clients = []
            return

        self.clients = [Groq(api_key=key) for key in unique_keys]
        print(f"[*] GroqKeyPool initialized with {len(self.clients)} active API keys.")

    def get_client(self) -> Groq:
        """Atomically fetch the next Groq client in round-robin order."""
        if not self.clients:
            raise RuntimeError("Groq key pool is empty. Please set GROQ_API_KEYS in .env.")

        with self._lock:
            client = self.clients[self._index]
            self._index = (self._index + 1) % len(self.clients)
            return client

    def execute_with_failover(self, func, max_retries: int = 4):
        """
        Executes a call with automatic rotation across keys if 429 occurs.
        """
        if not self.clients:
            raise RuntimeError("No Groq clients available in key pool.")

        attempts = min(len(self.clients), max_retries)
        last_error = None

        for attempt in range(attempts):
            client = self.get_client()
            try:
                return func(client)
            except Exception as e:
                err_str = str(e).lower()
                last_error = e

                if any(x in err_str for x in ["429", "rate_limit", "rate limit", "resource_exhausted", "too many requests"]):
                    print(f"[!] Groq rate limit hit (attempt {attempt + 1}/{attempts}). Cycling to next key...")
                    continue

                raise e

        raise last_error


# Global singleton instance
groq_pool = GroqKeyPool()
