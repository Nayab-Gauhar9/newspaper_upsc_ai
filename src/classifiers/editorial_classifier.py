import os
import json
import re
import time
import sys
import itertools
from typing import Optional, List
from dotenv import load_dotenv
from groq import Groq, RateLimitError
from pydantic import BaseModel, Field, model_validator

from src.storage.minio_client import NewspaperStorage
from src.classifiers.taxonomy import LAXMIKANTH_8TH_EDITION, is_valid_chapter, get_chapter_title

load_dotenv()

# Build chapter list formatted for the prompt
TAXONOMY_STRING = "\n".join([f"{num}: {title}" for num, title in LAXMIKANTH_8TH_EDITION.items()])


class KeyRotator:
    """Manages round-robin rotation across multiple Groq API keys with rate-limit failover."""

    def __init__(self):
        keys = []
        # 1. Check comma-separated variable
        env_keys = os.getenv("GROQ_API_KEYS", "")
        if env_keys:
            keys.extend([k.strip() for k in env_keys.split(",") if k.strip()])

        # 2. Check individual GROQ_API_KEY / GROQ_API_KEY_1, _2, etc.
        single_key = os.getenv("GROQ_API_KEY")
        if single_key and single_key not in keys:
            keys.append(single_key.strip())

        idx = 1
        while True:
            numbered_key = os.getenv(f"GROQ_API_KEY_{idx}")
            if numbered_key and numbered_key.strip() not in keys:
                keys.append(numbered_key.strip())
                idx += 1
            else:
                break

        if not keys:
            raise ValueError("No GROQ API keys found in .env (set GROQ_API_KEYS or GROQ_API_KEY)")

        self.keys = keys
        self._pool = itertools.cycle(keys)
        self.clients = {k: Groq(api_key=k) for k in keys}
        print(f"[✓] KeyRotator initialized with {len(self.keys)} active Groq keys.")

    def get_next_client(self) -> tuple[str, Groq]:
        key = next(self._pool)
        return key, self.clients[key]


class ClassificationResult(BaseModel):
    is_relevant: Optional[bool] = Field(
        default=None,
        description="True if the article is relevant for Indian Polity (UPSC GS-II), False otherwise."
    )
    chapter_number: Optional[int] = Field(
        default=None,
        description="Exact Laxmikanth chapter number (1 to 92) if relevant, else null."
    )
    topic: Optional[str] = Field(
        default=None,
        description="Broad topic under the chapter (stored as metadata)."
    )
    subtopic: Optional[str] = Field(
        default=None,
        description="Specific concise subtopic (stored as metadata)."
    )
    reason: str = Field(
        default="",
        description="Concise reason for relevance or irrelevance (no more than 25 words)."
    )

    @model_validator(mode="after")
    def infer_relevance(self) -> "ClassificationResult":
        if self.is_relevant is None:
            self.is_relevant = bool(self.chapter_number is not None and self.chapter_number > 0)
        return self


SYSTEM_PROMPT = """You are a UPSC CSE Indian Polity and Governance (GS-II) evaluator.
You must output strictly valid JSON conforming to this schema:
{
  "is_relevant": true or false,
  "chapter_number": <int 1-92 or null>,
  "topic": <string or null>,
  "subtopic": <string or null>,
  "reason": <concise string under 25 words>
}"""

HUMAN_PROMPT_TEMPLATE = """Classify the following article for Indian Polity relevance.
Use exactly one Laxmikanth chapter when the article is relevant.
If it is not relevant, set is_relevant to false, and chapter_number, topic, and subtopic to null.
Keep the reason concise, no more than 25 words.
Return only the requested JSON object.

Laxmikanth chapters:
{chapters}

Article title:
{title}

Article text:
{article_text}"""


def sanitize_path(value: Optional[str]) -> str:
    if not value:
        return "General"
    val = str(value).strip().replace("/", "-").replace("\\", "-")
    val = re.sub(r'[:*?"<>|]', '', val)
    return val[:60].strip() or "General"

def countdown_sleep(seconds: int = 5):
    for remaining in range(seconds, 0, -1):
        sys.stdout.write(f"\r    [⏳ Pace Cooldown] {remaining:2d}s...")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 80 + "\r")
    sys.stdout.flush()


class EditorialPIBClassifier:
    def __init__(self):
        self.rotator = KeyRotator()
        self.model = "openai/gpt-oss-120b"
        self.storage = NewspaperStorage()

    def classify_article(self, title: str, text: str) -> ClassificationResult:
        truncated_text = text[:8000]
        prompt_content = HUMAN_PROMPT_TEMPLATE.format(
            chapters=TAXONOMY_STRING,
            title=title,
            article_text=truncated_text
        )

        # Retry through all available keys if a 429 rate limit is encountered
        attempts = 0
        max_attempts = len(self.rotator.keys)

        while attempts < max_attempts:
            key, client = self.rotator.get_next_client()
            key_preview = f"...{key[-6:]}"
            try:
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt_content}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
                return ClassificationResult.model_validate_json(completion.choices[0].message.content)
            except RateLimitError:
                attempts += 1
                print(f"\n    [!] Rate limited on key {key_preview}. Rotating immediately to next key...")
                time.sleep(1)
            except Exception as e:
                print(f"\n    [!] Error on key {key_preview}: {e}")
                raise e

        # If all keys were exhausted due to rate limiting, pause briefly before one final attempt
        print("    [!] All keys currently rate limited. Waiting 15s...")
        time.sleep(15)
        _, client = self.rotator.get_next_client()
        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        return ClassificationResult.model_validate_json(completion.choices[0].message.content)

    def process_object(self, raw_key: str) -> bool:
        filename = raw_key.split("/")[-1]
        article_id = filename.replace(".json", "")

        # 1. Deduplication check: Has it been classified already?
        classification_marker = f"newspaper/classifications/{article_id}.json"
        if self.storage.object_exists(classification_marker):
            return False

        payload = self.storage.get_json(raw_key)
        if not payload:
            return False

        article_id = payload.get("article_id", article_id)
        classification_marker = f"newspaper/classifications/{article_id}.json"
        if self.storage.object_exists(classification_marker):
            return False

        title = payload.get("title", "")
        pub = payload.get("publication", "")
        text = payload.get("full_article", "")

        if not text or len(text.split()) < 50:
            return False

        print(f"\n[+] Evaluating: {title[:55]}... ({pub})")
        res = self.classify_article(title, text)

        # 2. Persist classification metadata index
        classification_data = res.model_dump()
        classification_data["article_id"] = article_id
        classification_data["publication"] = pub
        classification_data["title"] = title
        classification_data["source_key"] = raw_key

        self.storage.put_json(classification_marker, classification_data)

# 3. Flat Polity Path: newspaper/classified/{chapter_name}/{article_id}.json
        if res.is_relevant and res.chapter_number and is_valid_chapter(res.chapter_number):
            chapter_name = get_chapter_title(res.chapter_number)
            chapter_dir = sanitize_path(chapter_name)

            dest_key = f"newspaper/classified/{chapter_dir}/{article_id}.json"

            stored_data = {
                **payload,
                "classification": {
                    **res.model_dump(),
                    "chapter_name": chapter_name
                }
            }
            self.storage.put_json(dest_key, stored_data)
            print(f"    [✓ POLITY SELECTED] -> {dest_key}")
            print(f"        Chapter {res.chapter_number}: {chapter_name}")
            print(f"        Topic: {res.topic} | Subtopic: {res.subtopic}")
            print(f"        Reason: {res.reason}")
        else:
            print(f"    [→ ARCHIVED] (Not Polity) -> {classification_marker}")
            print(f"        Reason: {res.reason}")

        return True


def run_classifier(limit: int = 15, cooldown_seconds: int = 5):
    classifier = EditorialPIBClassifier()
    storage = classifier.storage

    print("=" * 80)
    print("STARTING ROUND-ROBIN UPSC CLASSIFIER (FLAT CHAPTER SCHEMA)")
    print(f"Target Bucket: {storage.bucket} | Model: {classifier.model} | Pacing: {cooldown_seconds}s")
    print("=" * 80)

    # 1. Fetch raw items
    all_newspaper_objects = storage.list_objects(prefix="newspaper/")

    # 2. Filter strictly for raw sources
    raw_keys = [
        k for k in all_newspaper_objects
        if not k.startswith(("newspaper/classified/", "newspaper/classifications/"))
    ]

    # 3. Filter out files already classified
    unprocessed_keys = []
    for k in raw_keys:
        art_id = k.split("/")[-1].replace(".json", "")
        if not storage.object_exists(f"newspaper/classifications/{art_id}.json"):
            unprocessed_keys.append(k)

    print(f"Found {len(raw_keys)} total raw files. {len(unprocessed_keys)} remaining to classify.")

    processed = 0
    for key in unprocessed_keys:
        if processed >= limit:
            break

        did_run = classifier.process_object(key)
        if did_run:
            processed += 1
            if processed < limit:
                countdown_sleep(cooldown_seconds)

    print("\n" + "=" * 80)
    print(f"COMPLETED: Processed {processed} new articles.")
    print("=" * 80)


if __name__ == "__main__":
    run_classifier(limit=400,cooldown_seconds=5)
