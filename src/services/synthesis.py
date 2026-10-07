import time
from typing import Optional
from src.classifiers.editorial_classifier import KeyRotator
from src.analyser.study_llm import UPSCStudySynthesizer
from src.storage.minio_client import NewspaperStorage
from src.services.telegram_notifier import TelegramSmartNotesNotifier


class StudySynthesisPipeline:
    """Synthesizes in-depth UPSC smart notes from classified articles, persists to MinIO/R2, and broadcasts to Telegram."""

    def __init__(self):
        self.storage = NewspaperStorage()
        self.rotator = KeyRotator()
        self.notifier = TelegramSmartNotesNotifier()

    def synthesize_with_failover(self, chapter_name: str, topic: str, record: dict):
        """Runs synthesis with round-robin key failover."""
        attempts = 0
        max_attempts = len(self.rotator.keys)

        while attempts < max_attempts:
            key, client = self.rotator.get_next_client()
            try:
                synthesizer = UPSCStudySynthesizer(client=client)
                return synthesizer.synthesize(chapter_name, topic, record)
            except Exception as e:
                attempts += 1
                print(f"    [!] Synthesizer error with key ...{key[-6:]}: {e}. Retrying next key...")
                time.sleep(1)

        raise RuntimeError("All Groq keys exhausted during study synthesis.")

    def process_all_classified(
        self,
        limit: Optional[int] = 3,
        delay_between_calls: float = 5.0,
        broadcast_telegram: bool = True
    ):
        processed = 0
        synthesized = 0
        skipped = 0

        # Scan classified newspaper/judiciary articles
        objects = [k for k in self.storage.list_objects(prefix="newspaper/classified/")]
        print(f"\n[PIPELINE] Found {len(objects)} classified articles under 'newspaper/classified/'.")

        for object_name in objects:
            if object_name.endswith("/") or "smart_notes_" in object_name:
                continue

            if limit is not None and synthesized >= limit:
                print(f"\n[LIMIT REACHED] Stopped after synthesizing {limit} articles.")
                break

            processed += 1
            # Path structure: newspaper/classified/{chapter_name}/{article_id}.json
            parts = object_name.split("/")
            if len(parts) < 4:
                continue

            chapter_name = parts[2]
            filename = parts[3]
            article_id = filename.replace(".json", "")

            notes_object_name = f"newspaper/smart_notes/{chapter_name}/smart_notes_{article_id}.json"

            if self.storage.object_exists(notes_object_name):
                print(f"[SKIP] Smart notes already exist for ID: {article_id[:8]} ({chapter_name})")
                skipped += 1
                continue

            payload = self.storage.get_json(object_name)
            classification = payload.get("classification", {})
            topic = classification.get("topic") or chapter_name
            source_label = payload.get("publication", "Judiciary/Editorial")

            print(f"\n==================================================")
            print(f" [SYNTHESIS START] ID: {article_id[:8]}")
            print(f" Chapter: {chapter_name} | Source: {source_label.upper()}")
            print(f" Title: {payload.get('title', '')[:55]}...")
            print(f"==================================================")

            try:
                # 1. Synthesize intelligence via Groq
                print(" -> Generating deep UPSC smart note...")
                study_result = self.synthesize_with_failover(chapter_name, topic, payload)

                # 2. Persist to MinIO
                self.storage.put_json(notes_object_name, study_result.model_dump(mode="json"))
                synthesized += 1
                print(f" -> [STORAGE SUCCESS] Uploaded to: '{notes_object_name}'")

# 3. Publish Telegram Capsule + Prelims Quiz
                if broadcast_telegram and self.notifier.is_configured():
                    print(f" -> [TELEGRAM] Broadcasting capsule & quiz...")
                    sent = self.notifier.broadcast_note_and_quiz(
                        study_intelligence=study_result,
                        chapter=chapter_name,
                        topic=topic,
                        source_label=source_label,
                        article_id=article_id,
                        object_key=notes_object_name
                    )
                    if sent:
                        print("    [TELEGRAM SUCCESS] Capsule post and Quiz Poll published!")
                    else:
                        print("    [TELEGRAM WARNING] Telegram dispatch failed.")
                else:
                    print(" -> [TELEGRAM SKIPPED] Bot credentials not set or broadcast disabled.")

                if synthesized < limit:
                    print(f" -> Pausing for {delay_between_calls}s...")
                    time.sleep(delay_between_calls)

            except Exception as e:
                print(f"[ERROR] Failed synthesizing article {article_id}: {e}")

        print(f"\n==================================================")
        print(f" STUDY SYNTHESIS PIPELINE SUMMARY")
        print(f" Total Checked               : {processed}")
        print(f" Skipped (Already Exists)    : {skipped}")
        print(f" Newly Synthesized & Alerted : {synthesized}")
        print(f"==================================================")


if __name__ == "__main__":
    pipeline = StudySynthesisPipeline()
    pipeline.process_all_classified(limit=2, delay_between_calls=5.0, broadcast_telegram=True)
