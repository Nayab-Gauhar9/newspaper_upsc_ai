import os
import re
import json
import time
import hashlib
from typing import Optional, List, Dict, Tuple
from dotenv import load_dotenv

from groq import Groq
from sqlalchemy import select, text
from src.database.session import SessionLocal
from src.database.models import IssueDossierModel, IssueGraphEdgeModel
from src.storage.minio_client import NewspaperStorage
from src.classifiers.editorial_classifier import KeyRotator

load_dotenv()


DOSSIER_BROKER_SYSTEM_PROMPT = """You are a senior UPSC Legal Topic Arbiter specializing in Indian Constitutional and Governance developments.
Your job is twofold:
1. Determine if a new incoming event belongs to an existing ongoing active dossier or represents a new issue anchor.
2. Assess whether this event marks the DEFINITIVE CLOSURE of the issue.

TIMELINE CLUSTERING RULES:
- Merge follow-up hearings, contempt notices, affidavits, rejoinders, and ongoing debates into the SAME dossier.
- Only create a new dossier if the event is a fundamentally distinct dispute or involves a separate institution/state.

STATUS CLOSURE RULES:
- Mark "final_status": "closed" ONLY IF this development represents:
  a) A final, non-appealable verdict or Constitution Bench judgment settling the controversy.
  b) Presidential assent to a statutory enactment or constitutional amendment (Article 111).
  c) Complete withdrawal, definitive dismissal of the challenge, or formal resolution of the crisis.
- Otherwise, for interim orders, issued notices, arguments, ongoing committee hearings, or editorial commentaries, set "final_status": "active".

OUTPUT FORMAT (Strict JSON only):
{
  "match": true | false,
  "matched_slug": "<exact_matched_slug_from_candidates_or_empty_string>",
  "new_slug": "<broad-thematic-slug-if-no-match-or-empty_string>",
  "final_status": "active" | "closed",
  "reasoning": "<15-word concise explanation of matching and closure decision>"
}
"""

CHAPTER_CANONICAL_MAP = {
    "Advocate General of the State": "Advocate General",
    "Advocate General": "Advocate General",
    "Basic Structure of the Constitution": "Basic Structure",
    "Basic Structure": "Basic Structure",
    "Bar Council of India": "Advocate General",
    "Central Bureau of Investigation": "CBI",
    "Central Bureau Of Investigation": "CBI",
    "CBI": "CBI",
    "Centre State Relations": "Centre–State Relations",
    "Centre-State Relations": "Centre–State Relations",
    "Centre–State Relations": "Centre–State Relations",
    "Election Laws": "Election Commission",
    "Election Commission": "Election Commission",
}


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", cleaned)[:100]


def sanitize_prid(raw_id: str, clean_filename_id: str) -> str:
    for candidate in [raw_id, clean_filename_id]:
        if candidate and "_" in candidate and len(candidate) <= 30 and " " not in candidate:
            return candidate.strip()
    
    base = raw_id or clean_filename_id
    short_hash = hashlib.md5(base.encode("utf-8")).hexdigest()[:10]
    return f"NOTE_{short_hash}"


class DossierGraphSync:
    """Stage 2: Graph Synchronizer with Fast LLM Semantic Broker.
    Consumes smart notes persisted by NewspaperSynthesisPipeline (Stage 1)
    and dynamically constructs/evolves the constitutional issue graph.
    """

    def __init__(self):
        self.storage = NewspaperStorage()
        self.rotator = KeyRotator()
        self.broker_model = "openai/gpt-oss-120b"

    def _resolve_clustering_decision(
        self,
        chapter_name: str,
        headline: str,
        summary: str,
        candidates: List[Dict[str, str]],
    ) -> Tuple[bool, str, str, str]:
        if not candidates:
            return False, "", "active", "Initial dossier for chapter"

        candidate_blocks = [
            f"- Slug: '{c['slug']}'\n  Title: {c['title']}\n  Context: {c['summary'][:160]}..."
            for c in candidates
        ]
        candidates_str = "\n\n".join(candidate_blocks)

        user_prompt = f"""CHAPTER: {chapter_name}

NEW INCOMING EVENT:
Headline: {headline}
Summary: {summary}

EXISTING ACTIVE DOSSIERS IN THIS CHAPTER:
{candidates_str}

Evaluate if this new incoming event is a timeline development, aftermath, or parallel reporting of any active dossier above."""

        attempts = 0
        max_attempts = len(self.rotator.keys)
        last_error = ""

        while attempts < max_attempts:
            key, client = self.rotator.get_next_client()
            try:
                resp = client.chat.completions.create(
                    model=self.broker_model,
                    messages=[
                        {"role": "system", "content": DOSSIER_BROKER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                )
                data = json.loads(resp.choices[0].message.content)
                match = data.get("match", False)
                matched_slug = data.get("matched_slug", "").strip().lower()
                new_slug = data.get("new_slug", "").strip().lower()
                final_status = data.get("final_status", "active").strip().lower()
                reasoning = data.get("reasoning", "")

                target_slug = matched_slug if match and matched_slug else new_slug
                return match, target_slug, final_status, reasoning

            except Exception as e:
                last_error = str(e)
                attempts += 1
                time.sleep(1.0)

        print(f"  [⚠️ GROQ BROKER FALLBACK] {last_error[:80]}")
        return False, "", "active", "Key exhaustion fallback"

    def get_chapter_candidates(self, session, chapter_name: str, limit: int = 15) -> List[Dict[str, str]]:
        stmt = (
            select(
                IssueDossierModel.issue_slug,
                IssueDossierModel.title,
                IssueDossierModel.canonical_summary,
            )
            .where(
                IssueDossierModel.chapter_name == chapter_name,
                IssueDossierModel.status == "active",
            )
            .order_by(IssueDossierModel.last_updated_at.desc())
            .limit(limit)
        )
        records = session.execute(stmt).all()
        return [
            {
                "slug": r.issue_slug,
                "title": r.title,
                "summary": r.canonical_summary or "",
            }
            for r in records
        ]

    def sync_note_to_graph(
        self, session, note_payload: dict, article_id: str, chapter_name: str
    ):
        # 1. Base Attributes directly from Stage 1 schema
        pub = note_payload.get("publication") or note_payload.get("source") or "editorial"
        headline = (
            note_payload.get("headline")
            or note_payload.get("title")
            or "Constitutional Analysis"
        )
        summary = (
            note_payload.get("executive_synthesis")
            or note_payload.get("summary")
            or note_payload.get("synthesis")
            or ""
        )
        mains_framework = (
            note_payload.get("mains_model_framework")
            or note_payload.get("mains_framework")
            or {}
        )
        if not mains_framework and note_payload.get("mains_question"):
            mains_framework = {
                "introduction_hook": note_payload.get("why_it_matters", ""),
                "body_dimensions": note_payload.get("mains_question", ""),
                "way_forward_reforms": "; ".join(note_payload.get("smart_notes", [])),
            }

        # 2. Prelims Facts & Factsheet Normalization
        incoming_event_facts = (
            note_payload.get("prelims_event_facts")
            or note_payload.get("prelims_facts")

        or {}
        )
        if not incoming_event_facts and note_payload.get("prelims_practice_points"):
            incoming_event_facts = {
                "prelims_statements": note_payload.get("prelims_practice_points"),
                "provisions_invoked": note_payload.get("backward_linkages", []),
            }
        elif not incoming_event_facts and note_payload.get("prelims_trap_point"):
            incoming_event_facts = {
                "prelims_statements": [note_payload.get("prelims_trap_point")],
                "provisions_invoked": note_payload.get("constitutional_anchors", []),
            }

        incoming_factsheet = note_payload.get("prelims_factsheet") or {}
        if not incoming_factsheet:
            constitutional_anchors = (
                note_payload.get("constitutional_anchors", [])
                + note_payload.get("backward_linkages", [])
            )
            raw_articles = [a for a in constitutional_anchors if "Article" in a]
            raw_acts = [a for a in constitutional_anchors if "Article" not in a]
            incoming_factsheet = {
                "constitutional_articles": raw_articles,
                "statutory_acts_sections": raw_acts,
                "key_reform_committees": [],
                "nodal_body": incoming_event_facts.get("nodal_authority", ""),
                "body_character": incoming_event_facts.get("legal_status", ""),
                "tenure_and_removal": "",
            }

        # 3. Idempotency Check
        existing_edge = session.scalars(
            select(IssueGraphEdgeModel).where(IssueGraphEdgeModel.prid == article_id)
        ).first()
        if existing_edge:
            print(f"  [-] Edge already exists for {article_id}. Skipping.")
            return

        # 4. Safe Deterministic Fallback Slug
        headline_slug = slugify(headline) if headline else ""
        raw_slug = (
            note_payload.get("issue_slug")
            or headline_slug
            or f"issue-{article_id[:12]}"
        ).strip().lower()

        # 5. Semantic Arbiter Decision
        candidates = self.get_chapter_candidates(session, chapter_name)
        match_found, chosen_slug, final_status, reasoning = self._resolve_clustering_decision(
            chapter_name=chapter_name,
            headline=headline,
            summary=summary,
            candidates=candidates,
        )

        final_slug = (chosen_slug if chosen_slug else raw_slug).strip().lower()

        # 6. Target Dossier Retrieval (handles matched slugs or identical fallbacks)
        dossier = session.scalars(
            select(IssueDossierModel).where(IssueDossierModel.issue_slug == final_slug)
        ).first()

        # 7. Create or Merge Node
        if not dossier:
            dossier = IssueDossierModel(
                issue_slug=final_slug,
                title=headline,
                chapter_name=chapter_name,
                canonical_summary=summary,
                mains_framework=mains_framework,
                prelims_factsheet=incoming_factsheet,
                article_count=1,
                status=final_status,
            )
            session.add(dossier)
            session.flush()
            print(f"  [+] INITIALIZED DOSSIER: '{dossier.issue_slug}' | Status: {final_status} | Reason: {reasoning}")
        else:
            dossier.article_count += 1
            if final_status == "closed":
                dossier.status = "closed"

            # Prepend update chronologically to timeline
            if summary:
                if dossier.canonical_summary:
                    dossier.canonical_summary = f"[Update: {headline}] {summary}\n\n[Prior Context]: {dossier.canonical_summary}"
                else:
                    dossier.canonical_summary = summary

            if mains_framework:
                dossier.mains_framework = mains_framework

# Cumulative set union on factsheet
            existing_factsheet = dossier.prelims_factsheet or {}
            merged_articles = sorted(list(set(
                existing_factsheet.get("constitutional_articles", [])
                + incoming_factsheet.get("constitutional_articles", [])
                + incoming_event_facts.get("provisions_invoked", [])
            )))
            merged_acts = sorted(list(set(
                existing_factsheet.get("statutory_acts_sections", [])
                + incoming_factsheet.get("statutory_acts_sections", [])
            )))
            merged_committees = sorted(list(set(
                existing_factsheet.get("key_reform_committees", [])
                + incoming_factsheet.get("key_reform_committees", [])
            )))

            existing_factsheet["constitutional_articles"] = merged_articles
            existing_factsheet["statutory_acts_sections"] = merged_acts
            existing_factsheet["key_reform_committees"] = merged_committees

            for k in ["nodal_body", "body_character", "tenure_and_removal"]:
                v = incoming_factsheet.get(k)
                if v and not existing_factsheet.get(k):
                    existing_factsheet[k] = v

            dossier.prelims_factsheet = existing_factsheet
            session.flush()
            print(f"  [~] MERGED INTO DOSSIER: '{dossier.issue_slug}' (Count: {dossier.article_count}) | Status: {dossier.status} | Reason: {reasoning}")

        # 8. Create Directed Edge
        matrix = note_payload.get("dialectical_matrix") or note_payload.get("dialectics") or {}
        thesis_pts = [
            f"{p.get('argument')} (Ref: {p.get('substantiation')})"
            for p in matrix.get("thesis_affirmative_dimension", [])
            if p.get("argument")
        ]
        critique_pts = [
            f"{p.get('argument')} (Ref: {p.get('substantiation')})"
            for p in matrix.get("antithesis_critique_dimension", [])
            if p.get("argument")
        ]

        if thesis_pts or critique_pts:
            combined_claim = (
                "THESIS: " + "; ".join(thesis_pts[:2]) +
                " | CRITIQUE: " + "; ".join(critique_pts[:2])
            )
        else:
            combined_claim = summary[:300] if summary else headline

        edge = IssueGraphEdgeModel(
            issue_slug=dossier.issue_slug,
            prid=article_id,
            publication=pub,
            perspective_stance="DIALECTICAL_CRITIQUE",
            core_claim=combined_claim,
            legal_anchors=note_payload.get("constitutional_anchors", []),
            prelims_event_facts=incoming_event_facts,
        )
        session.add(edge)
        session.commit()
        print(f"  [✓] Linked edge: '{article_id}' -> '{dossier.issue_slug}'")

    def run_sync(self, reset_db: bool = False):
        if reset_db:
            with SessionLocal() as db:
                print("⚠️ [RESET] Truncating issue_graph_edges and issue_dossiers tables...")
                db.execute(text("TRUNCATE TABLE issue_graph_edges, issue_dossiers RESTART IDENTITY CASCADE;"))
                db.commit()
                print("✓ Tables successfully truncated.")

        note_keys = [
            k
            for k in self.storage.list_objects(prefix="newspaper/smart_notes/")
            if k.endswith(".json")
        ]
        if not note_keys:
            note_keys = [
                k
                for k in self.storage.list_objects(prefix="smart_notes/")
                if k.endswith(".json")
            ]

        print(f"\n[GRAPH SYNC] Found {len(note_keys)} smart note files in MinIO.")

        for key in note_keys:
            try:
                payload = self.storage.get_json(key)
                if not payload:
                    print(f"  [!] Skipping empty payload: {key}")
                    continue

                parts = [p for p in key.split("/") if p]
                filename = parts[-1]
                folder_chapter = parts[-2] if len(parts) >= 2 else "General Governance"

                chapter_name = (
                    payload.get("chapter_name")
                    or payload.get("chapter")
                    or folder_chapter
                ).strip()

                chapter_name = CHAPTER_CANONICAL_MAP.get(chapter_name, chapter_name)

                clean_filename_id = filename.replace("smart_notes_", "").replace(".json", "").strip()
                raw_article_id = str(payload.get("source_article_id") or "").strip()
                article_id = sanitize_prid(raw_article_id, clean_filename_id)

                with SessionLocal() as session:
                    self.sync_note_to_graph(session, payload, article_id, chapter_name)

            except Exception as e:
                print(f"  [ERROR] Failed processing {key}: {e}")

        print("\n" + "=" * 60)
        print("GRAPH SYNCHRONIZATION FINISHED")
        print("=" * 60)


if __name__ == "__main__":
    syncer = DossierGraphSync()
    # Production default: incremental sync
    syncer.run_sync(reset_db=False)
