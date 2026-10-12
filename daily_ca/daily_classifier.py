import time
from typing import Optional
from src.storage.minio_client import NewspaperStorage
from src.classifiers.editorial_classifier import (
    KeyRotator,
    SYSTEM_PROMPT,
    HUMAN_PROMPT_TEMPLATE,
    TAXONOMY_STRING,
    ClassificationResult,
    countdown_sleep,
)
from src.classifiers.taxonomy import is_valid_chapter, get_chapter_title


class DailyPolityClassifier:
    def __init__(self):
        self.storage = NewspaperStorage()
        self.rotator = KeyRotator()
        self.model = "openai/gpt-oss-120b"

    def evaluate_polity_relevance(self, title: str, text: str) -> ClassificationResult:
        """Evaluates article text using round-robin Groq API rotation."""
        prompt = HUMAN_PROMPT_TEMPLATE.format(
            chapters=TAXONOMY_STRING,
            title=title,
            article_text=text[:8000],
        )
        attempts = 0
        max_attempts = len(self.rotator.keys)

        while attempts < max_attempts:
            key, client = self.rotator.get_next_client()
            try:
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                return ClassificationResult.model_validate_json(
                    completion.choices[0].message.content
                )
            except Exception as e:
                attempts += 1
                print(f"    [!] Groq rotation on key ...{key[-6:]}: {e}")
                time.sleep(1.0)

        # Fallback pause if all keys hit rate limits
        print("    [!] All keys rate-limited. Pausing 15s...")
        time.sleep(15.0)
        _, client = self.rotator.get_next_client()
        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return ClassificationResult.model_validate_json(completion.choices[0].message.content)

    def run_classifier(
        self,
        target_date: Optional[str] = None,
        limit: Optional[int] = None,
        cooldown_seconds: int = 4,
    ):
        """
        Scans daily_press/ across all dates or a target date.
        - Idempotent: Skips if already in classified/ or unclassified/.
        - Non-destructive: Never removes files from raw/.
        """
        print("=" * 80)
        print("STARTING DAILY POLITY CLASSIFIER (IDEMPOTENT & NON-DESTRUCTIVE)")
        print(f"Bucket: {self.storage.bucket} | Model: {self.model}")
        print("=" * 80)

        # 1. Discover all raw objects across daily_press
        all_objects = self.storage.list_objects(prefix="daily_press/")
        raw_keys = [
            k for k in all_objects
            if "/raw/" in k and k.endswith(".json")
        ]

        # Filter by specific date if requested (e.g. "2026-09-17" or "2026-10-11")
        if target_date:
            raw_keys = [k for k in raw_keys if f"/{target_date}/" in k]

        # Sort chronologically so backlog from last month processes in order
        raw_keys.sort()

        print(f"Discovered {len(raw_keys)} total raw files.")

        # 2. Idempotency Check: Filter out already processed items
        unprocessed_keys = []
        for raw_key in raw_keys:
            # e.g., daily_press/the_hindu/2026-10-11/national/raw/TH_...json
            classified_key = raw_key.replace("/raw/", "/classified/")
            unclassified_key = raw_key.replace("/raw/", "/unclassified/")

            if not self.storage.object_exists(classified_key) and not self.storage.object_exists(unclassified_key):
                unprocessed_keys.append(raw_key)

        print(f"Remaining to classify: {len(unprocessed_keys)} articles.\n")

        processed = 0
        retained_polity = 0
        diverted_general = 0

        for raw_key in unprocessed_keys:
            if limit and processed >= limit:
                print(f"[LIMIT REACHED] Stopped after {limit} articles.")
                break

            payload = self.storage.get_json(raw_key)
            if not payload:
                continue

            article_id = payload.get("article_id") or raw_key.split("/")[-1].replace(".json", "")
            title = payload.get("title", "")
            text = payload.get("full_article", "")
            pub = payload.get("publication", "")
            cat = payload.get("category", "")
            art_date = payload.get("published_date") or payload.get("article_date", "")

            if not text or len(text.split()) < 50:
                continue

            print(f"[{art_date}] Evaluating: {title[:55]}... ({pub}/{cat})")
            res = self.evaluate_polity_relevance(title, text)

            classified_key = raw_key.replace("/raw/", "/classified/")
            unclassified_key = raw_key.replace("/raw/", "/unclassified/")

            # 3. Non-Destructive Partitioning
            if res.is_relevant and res.chapter_number and is_valid_chapter(res.chapter_number):
                chapter_name = get_chapter_title(res.chapter_number)
                classified_payload = {
                    **payload,
                    "classification": {
                        **res.model_dump(),
                        "chapter_name": chapter_name,
                    },
                }
                # Store in classified/ (Original raw file remains untouched)
                self.storage.put_json(classified_key, classified_payload)
                retained_polity += 1
                print(f"    [✓ POLITY STORED] -> {classified_key}")
                print(f"        Chapter {res.chapter_number}: {chapter_name} ({res.topic})")
            else:
                unclassified_payload = {
                    **payload,
                    "classification": res.model_dump(),
                }
                # Store in unclassified/ (Original raw file remains untouched)
                self.storage.put_json(unclassified_key, unclassified_payload)
                diverted_general += 1
                print(f"    [→ GENERAL ARCHIVE] (Not Polity) -> {unclassified_key}")
                print(f"        Reason: {res.reason}")

            processed += 1
            if cooldown_seconds > 0:
                countdown_sleep(cooldown_seconds)

        print("\n" + "=" * 80)
        print("DAILY CLASSIFICATION COMPLETED")
        print(f"Total Processed       : {processed}")
        print(f"Polity Articles       : {retained_polity}")
        print(f"General / Unclassified: {diverted_general}")
        print(f"Raw Files Preserved   : {len(raw_keys)} (100%)")
        print("=" * 80)


if __name__ == "__main__":
    classifier = DailyPolityClassifier()
    # Runs across all dates starting from your earliest folder in MinIO
    classifier.run_classifier(target_date="2026-10-12", limit=None, cooldown_seconds=3)
