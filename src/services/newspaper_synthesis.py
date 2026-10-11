import os
import time
from typing import Optional
from dotenv import load_dotenv

from src.storage.minio_client import NewspaperStorage
from src.classifiers.editorial_classifier import KeyRotator
from src.services.telegram_notifier import TelegramSmartNotesNotifier
from src.classifiers.prompts import (
    PHD_UPSC_SYSTEM_PROMPT,
    TOPIC_EVOLUTION_USER_PROMPT,
    UPSCPhDIntelligence,
)

load_dotenv()


class NewspaperSynthesisPipeline:
    """Stage 1: Dedicated synthesis pipeline.
    Reads classified articles from MinIO, invokes the LLM, and persists
    synthesized smart notes back to MinIO (newspaper/smart_notes/...).
    """

    def __init__(self):
        self.storage = NewspaperStorage()
        self.rotator = KeyRotator()
        self.notifier = TelegramSmartNotesNotifier()
        self.model = "openai/gpt-oss-120b"

    def synthesize_intelligence(
        self,
        chapter: str,
        topic: str,
        pub: str,
        title: str,
        text: str,
    ) -> UPSCPhDIntelligence:
        # Prompt formatted without demanding live DB slugs in Stage 1
        prompt = TOPIC_EVOLUTION_USER_PROMPT.format(
            chapter_name=chapter,
            topic=topic,
            publication=pub,
            title=title,
            existing_candidates="None (Standalone synthesis pass)",
            text=text[:8500],
        )

        attempts = 0
        max_attempts = len(self.rotator.keys)

        while attempts < max_attempts:
            key, client = self.rotator.get_next_client()
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": PHD_UPSC_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                return UPSCPhDIntelligence.model_validate_json(
                    resp.choices[0].message.content
                )
            except Exception as e:
                attempts += 1
                print(
                    f"    [!] Groq failure on key ...{key[-6:]}: {e}. Retrying next key..."
                )
                time.sleep(1)

        raise RuntimeError("All Groq API keys exhausted during synthesis.")

    def process_all_classified(
        self,
        limit: Optional[int] = None,
        delay_between_calls: float = 5.0,
        broadcast_telegram: bool = True,
    ):
        objects = [
            k
            for k in self.storage.list_objects(prefix="newspaper/classified/")
            if k.endswith(".json") and "smart_notes_" not in k
        ]
        print(f"\n[SYNTHESIS STAGE] Found {len(objects)} classified articles in MinIO.")

        processed = 0
        synthesized = 0
        skipped = 0

        for object_name in objects:
            if limit is not None and synthesized >= limit:
                print(f"\n[LIMIT REACHED] Stopped after {limit} articles.")
                break

            processed += 1
            parts = object_name.split("/")
            if len(parts) < 4:
                continue

            chapter_name = parts[2]
            filename = parts[3]
            article_id = filename.replace(".json", "")

            notes_object_name = (
                f"newspaper/smart_notes/{chapter_name}/smart_notes_{article_id}.json"
            )

            if self.storage.object_exists(notes_object_name):
                skipped += 1
                continue

            payload = self.storage.get_json(object_name)
            if not payload:
                continue

            pub = payload.get("publication", "editorial")
            title = payload.get("title", "")
            text = payload.get("full_article", "")
            classification = payload.get("classification", {})
            topic = classification.get("topic") or chapter_name

            if not text or len(text.split()) < 60:
                continue

            print(f"\n{'='*75}")
            print(f"[SYNTHESIS START] ID: {article_id} | Source: {pub.upper()}")
            print(f"Chapter: {chapter_name} | Topic: {topic}")
            print(f"Title: {title[:55]}...")
            print(f"{'='*75}")

            try:
                # 1. Synthesize via LLM
                intel = self.synthesize_intelligence(
                    chapter=chapter_name,
                    topic=topic,
                    pub=pub,
                    title=title,
                    text=text,
                )

                # 2. Persist directly to MinIO
                intel_dict = intel.model_dump()
                intel_dict["source_article_id"] = article_id
                intel_dict["publication"] = pub
                self.storage.put_json(notes_object_name, intel_dict)
                synthesized += 1
                print(f" -> [MINIO SUCCESS] Uploaded to: '{notes_object_name}'")

                # 3. Optional Telegram Broadcast
                if broadcast_telegram and self.notifier.is_configured():
                    prelims_pts = [
                        {
                            "statement": s.statement,
                            "is_correct": s.is_correct,
                            "explanation": s.explanation,
                        }
                        for s in intel.prelims_event_facts.prelims_statements
                    ]
                    tg_payload = {
                        "headline": intel.headline,
                        "summary": intel.executive_synthesis,
                        "why_it_matters": intel.theoretical_and_constitutional_context,
                        "smart_notes": [
                            f"⚖️ [Affirmative] {p.argument}"
                            for p in intel.dialectical_matrix.thesis_affirmative_dimension[:2]
                        ]
                        + [
                            f"🔍 [Critique] {p.argument}"
                            for p in intel.dialectical_matrix.antithesis_critique_dimension[:2]
                        ],
                        "backward_linkages": intel.constitutional_anchors[:4],
                        "mains_question": (
                            intel.mains_model_framework.get("introduction_hook", "")
                            + "\n"
                            + intel.mains_model_framework.get("body_dimensions", "")
                        ),
                        "prelims_practice_points": prelims_pts,
                    }
                    self.notifier.broadcast_note_and_quiz(
                        study_intelligence=tg_payload,
                        chapter=chapter_name,
                        topic=topic,
                        source_label=pub,
                        article_id=article_id,
                        object_key=notes_object_name,
                    )
                    print(" -> [TELEGRAM SUCCESS] Capsule published!")

                if synthesized < (limit or float("inf")):
                    time.sleep(delay_between_calls)

            except Exception as e:
                print(f"[ERROR] Failed synthesizing {article_id}: {e}")

        print(f"\n{'='*75}")
        print("STAGE 1 SYNTHESIS SUMMARY")
        print(f"Total Scanned : {processed}")
        print(f"Skipped       : {skipped}")
        print(f"Synthesized   : {synthesized}")
        print(f"{'='*75}")


if __name__ == "__main__":
    pipeline = NewspaperSynthesisPipeline()
    pipeline.process_all_classified(limit=None, delay_between_calls=5)
