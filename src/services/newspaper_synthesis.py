import os
import time
from typing import Optional
from dotenv import load_dotenv

from sqlalchemy import select
from src.database.session import SessionLocal
from src.database.models import IssueDossierModel, IssueGraphEdgeModel

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
    """Dedicated pipeline for editorial, judicial, and governance articles.
    Operates on flattened 'newspaper/classified/{chapter}/{article_id}.json' paths.
    """

    def __init__(self):
        self.storage = NewspaperStorage()
        self.rotator = KeyRotator()
        self.notifier = TelegramSmartNotesNotifier()
        self.model = "openai/gpt-oss-120b"

    def synthesize_intelligence(
        self, chapter: str, topic: str, pub: str, title: str, text: str
    ) -> UPSCPhDIntelligence:
        prompt = TOPIC_EVOLUTION_USER_PROMPT.format(
            chapter_name=chapter,
            topic=topic,
            publication=pub,
            title=title,
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

    def record_graph_edge(
        self,
        session,
        intel: UPSCPhDIntelligence,
        article_id: str,
        pub: str,
        default_chapter: str,
    ):
        slug = intel.issue_slug.strip().lower()
        canonical_chapter = intel.chapter_name or default_chapter

        # Convert Pydantic payloads to plain dicts
        incoming_event_facts = intel.prelims_event_facts.model_dump()
        incoming_factsheet = intel.prelims_factsheet.model_dump()

        # 1. Update or create the living issue dossier node
        stmt = select(IssueDossierModel).where(IssueDossierModel.issue_slug == slug)
        dossier = session.scalars(stmt).first()

        if not dossier:
            dossier = IssueDossierModel(
                issue_slug=slug,
                title=intel.headline,
                chapter_name=canonical_chapter,
                canonical_summary=intel.executive_synthesis,
                mains_framework=intel.mains_model_framework,
                prelims_factsheet=incoming_factsheet,  # Set initial factsheet
                article_count=1,
            )
            session.add(dossier)
        else:
            dossier.article_count += 1
            dossier.chapter_name = canonical_chapter
            dossier.canonical_summary = intel.executive_synthesis
            dossier.mains_framework = intel.mains_model_framework
            if intel.suggested_status == "resolved":
                dossier.status = "resolved"

            # CUMULATIVE UPDATE: Merge new articles, acts, and committees into the existing factsheet
            existing_factsheet = dossier.prelims_factsheet or {}
            
            merged_articles = sorted(list(set(
                existing_factsheet.get("constitutional_articles", []) + 
                incoming_factsheet.get("constitutional_articles", []) +
                incoming_event_facts.get("provisions_invoked", [])
            )))
            merged_acts = sorted(list(set(
                existing_factsheet.get("statutory_acts_sections", []) + 
                incoming_factsheet.get("statutory_acts_sections", [])
            )))
            merged_committees = sorted(list(set(
                existing_factsheet.get("key_reform_committees", []) + 
                incoming_factsheet.get("key_reform_committees", [])
            )))

            existing_factsheet["constitutional_articles"] = merged_articles
            existing_factsheet["statutory_acts_sections"] = merged_acts
            existing_factsheet["key_reform_committees"] = merged_committees
            
            if incoming_factsheet.get("nodal_body"):
                existing_factsheet["nodal_body"] = incoming_factsheet["nodal_body"]
            if incoming_factsheet.get("body_character"):
                existing_factsheet["body_character"] = incoming_factsheet["body_character"]
            if incoming_factsheet.get("tenure_and_removal"):
                existing_factsheet["tenure_and_removal"] = incoming_factsheet["tenure_and_removal"]

            dossier.prelims_factsheet = existing_factsheet

        session.flush()

        # 2. Add perspective edge with granular event facts
        thesis_points = [
            f"{p.argument} (Ref: {p.substantiation})"
            for p in intel.dialectical_matrix.thesis_affirmative_dimension
        ]
        critique_points = [
            f"{p.argument} (Ref: {p.substantiation})"
            for p in intel.dialectical_matrix.antithesis_critique_dimension
        ]

        combined_claim = (
            "THESIS: "
            + "; ".join(thesis_points[:2])
            + " | CRITIQUE: "
            + "; ".join(critique_points[:2])
        )

        edge = IssueGraphEdgeModel(
            issue_slug=slug,
            prid=article_id,
            publication=pub,
            perspective_stance="DIALECTICAL_CRITIQUE",
            core_claim=combined_claim,
            legal_anchors=intel.constitutional_anchors,
            prelims_event_facts=incoming_event_facts,  # Stored here
        )
        session.add(edge)
        session.commit()



    def process_all_classified(
        self,
        limit: Optional[int] = 5,
        delay_between_calls: float = 5.0,
        broadcast_telegram: bool = True,
    ):
        # Scan 4-part flat newspaper structure: newspaper/classified/{chapter}/{article_id}.json
        objects = [
            k
            for k in self.storage.list_objects(prefix="newspaper/classified/")
            if k.endswith(".json") and "smart_notes_" not in k
        ]
        print(f"\n[PIPELINE] Found {len(objects)} classified newspaper/legal articles.")

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

            notes_object_name = f"newspaper/smart_notes/{chapter_name}/smart_notes_{article_id}.json"

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
                # 1. Synthesize via Ph.D. prompt & Groq key rotator
                intel = self.synthesize_intelligence(
                    chapter_name, topic, pub, title, text
                )

                # 2. Persist to NeonDB Graph Tables
                with SessionLocal() as db_session:
                    self.record_graph_edge(
                        db_session, intel, article_id, pub, chapter_name
                    )
                print(f" -> [GRAPH SUCCESS] Edge linked to slug: '{intel.issue_slug}'")

                # 3. Save to MinIO
                self.storage.put_json(notes_object_name, intel.model_dump())
                synthesized += 1
                print(f" -> [STORAGE SUCCESS] Uploaded to: '{notes_object_name}'")

                # 4. Telegram Capsule & Quiz
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

                    print(" -> [TELEGRAM SUCCESS] Capsule & Quiz published!")

                if synthesized < limit:
                    time.sleep(delay_between_calls)

            except Exception as e:
                print(f"[ERROR] Failed synthesizing {article_id}: {e}")

        print(f"\n{'='*75}")
        print("NEWSPAPER SYNTHESIS SUMMARY")
        print(f"Total Scanned : {processed}")
        print(f"Skipped       : {skipped}")
        print(f"Synthesized   : {synthesized}")
        print(f"{'='*75}")


if __name__ == "__main__":
    pipeline = NewspaperSynthesisPipeline()
    pipeline.process_all_classified(limit=3, delay_between_calls=20)
