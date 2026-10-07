import os
import json
import time
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
import voyageai

from src.storage.minio_client import NewspaperStorage

load_dotenv()

PG_CONN_STRING = os.getenv("DATABASE_URL")
if PG_CONN_STRING:
    if PG_CONN_STRING.startswith("postgresql+psycopg://"):
        PG_CONN_STRING = PG_CONN_STRING.replace(
            "postgresql+psycopg://", "postgresql://"
        )
    elif PG_CONN_STRING.startswith("postgresql+psycopg2://"):
        PG_CONN_STRING = PG_CONN_STRING.replace(
            "postgresql+psycopg2://", "postgresql://"
        )

VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")

if not PG_CONN_STRING:
    raise ValueError("DATABASE_URL is missing from .env")
if not VOYAGE_API_KEY:
    raise ValueError("VOYAGE_API_KEY is missing from .env")


class SmartNotesVectorizer:
    def __init__(self, model_name: str = "voyage-3-large"):
        self.model_name = model_name
        self.voyage = voyageai.Client(api_key=VOYAGE_API_KEY)
        self.storage = NewspaperStorage()
        self.conn = psycopg2.connect(PG_CONN_STRING)

    def is_already_vectorized(self, item_id: str) -> bool:
        """Checks if this article/PRID already has chunks in document_chunks."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM document_chunks WHERE prid = %s LIMIT 1;", (item_id,))
            return cur.fetchone() is not None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch generates 1024-dimension embeddings via Voyage AI."""
        if not texts:
            return []
        res = self.voyage.embed(
            texts=texts,
            model=self.model_name,
            input_type="document"
        )
        return res.embeddings

    def decompose_note_into_chunks(self, chapter: str, topic: str, data: dict) -> list[dict]:
        """Decomposes the smart note into atomic chunk_types supporting both
        UPSCPhDIntelligence and legacy PIB schemas.
        """
        chunks = []

        # 1. Summary & Significance
        headline = data.get("headline") or topic
        summary = data.get("summary") or data.get("executive_synthesis", "")
        why_matters = data.get("why_it_matters") or data.get("theoretical_and_constitutional_context", "")
        summary_text = f"Headline: {headline}\nSummary: {summary}\nSignificance: {why_matters}".strip()
        if summary_text:
            chunks.append({
                "chunk_type": "summary_and_significance",
                "chunk_text": summary_text
            })

        # 2. Backward Linkages / Constitutional Anchors
        linkages = data.get("constitutional_anchors") or data.get("backward_linkages") or []
        if linkages:
            link_text = "Backward Linkages and Constitutional Anchors:\n" + "\n".join([f"• {l}" for l in linkages])
            chunks.append({
                "chunk_type": "backward_linkages",
                "chunk_text": link_text
            })

        # 3. Mains Analysis & Analytical Framework
        mains_framework = data.get("mains_model_framework") or {}
        if isinstance(mains_framework, dict) and any(mains_framework.values()):
            hook = mains_framework.get("introduction_hook", "")
            body = mains_framework.get("body_dimensions", "")
            reforms = mains_framework.get("way_forward_reforms", "")
            chunks.append({
                "chunk_type": "mains_analysis",
                "chunk_text": f"Mains Analytical Framework:\n{hook}\n{body}\n{reforms}".strip()
            })
        elif data.get("mains_question"):
            chunks.append({
                "chunk_type": "mains_analysis",
                "chunk_text": f"Mains Syllabus Mapping & Question Framework:\n{data['mains_question']}"
            })

# 4. Dialectical Matrix (Thesis & Critique) / Smart Notes
        dialectics = data.get("dialectical_matrix") or {}
        for item in dialectics.get("thesis_affirmative_dimension", []):
            arg = item.get("argument", "") if isinstance(item, dict) else str(item)
            sub = item.get("substantiation", "") if isinstance(item, dict) else ""
            chunks.append({
                "chunk_type": "smart_note_bullet",
                "chunk_text": f"Affirmative Thesis: {arg} | Substantiation: {sub}".strip(" | ")
            })

        for item in dialectics.get("antithesis_critique_dimension", []):
            arg = item.get("argument", "") if isinstance(item, dict) else str(item)
            sub = item.get("substantiation", "") if isinstance(item, dict) else ""
            chunks.append({
                "chunk_type": "smart_note_bullet",
                "chunk_text": f"Critique / Antithesis: {arg} | Substantiation: {sub}".strip(" | ")
            })

        for note in data.get("smart_notes") or []:
            chunks.append({
                "chunk_type": "smart_note_bullet",
                "chunk_text": f"Smart Note Point: {note}"
            })

        # 5. Prelims Practice Statements & Invoked Provisions
        prelims_facts = data.get("prelims_event_facts") or {}
        provisions = prelims_facts.get("provisions_invoked") or []
        if provisions:
            chunks.append({
                "chunk_type": "constitutional_provisions",
                "chunk_text": f"Constitutional Articles and Statutory Provisions Invoked: {', '.join(provisions)}"
            })

        prelims_points = prelims_facts.get("prelims_statements") or data.get("prelims_practice_points") or []
        for p in prelims_points:
            stmt = p.get("statement", "")
            ans = "Correct" if p.get("is_correct") else "Incorrect"
            exp = p.get("explanation", "")
            if stmt:
                chunks.append({
                    "chunk_type": "prelims_practice",
                    "chunk_text": f"Prelims Practice Statement: {stmt}\nAnswer: {ans}\nExplanation: {exp}"
                })

        trap = data.get("prelims_trap_point") or {}
        if trap.get("statement"):
            chunks.append({
                "chunk_type": "prelims_practice",
                "chunk_text": f"Prelims Trap Point: {trap.get('statement')}\nAnswer: {trap.get('is_correct')}\nExplanation: {trap.get('explanation_under_200_chars', '')}"
            })

        return chunks

    def process_smart_notes(self, limit: int = 10, delay_seconds: float = 20.0):
        all_keys = [
            k for k in self.storage.list_objects(prefix="newspaper/smart_notes/")
            if k.endswith(".json") and "smart_notes_" in k
        ]

        print(f"[+] Found {len(all_keys)} smart note files in MinIO.")
        processed = 0

        for key in all_keys:
            if processed >= limit:
                break

            parts = key.split("/")
            chapter_name = parts[2]
            filename = parts[3]
            article_id = filename.replace("smart_notes_", "").replace(".json", "")

            # Deduplication: Check if already in NeonDB
            if self.is_already_vectorized(article_id):
                continue

            note_payload = self.storage.get_json(key)
            if not note_payload:
                continue

            topic = note_payload.get("topic") or chapter_name

            # 1. Decompose into chunk units
            chunk_items = self.decompose_note_into_chunks(chapter_name, topic, note_payload)
            if not chunk_items:
                continue

            print(f"\n[+] Processing: {article_id[:12]} | Chapter: {chapter_name}")
            print(f"    -> Decomposed into {len(chunk_items)} atomic chunks across all dimensions.")

            # 2. Embed via Voyage-3-large
            texts = [c["chunk_text"] for c in chunk_items]
            embeddings = self.embed_texts(texts)

        # 3. Prepare NeonDB rows
            rows = []
            for item, emb in zip(chunk_items, embeddings):
                token_count = int(len(item["chunk_text"].split()) * 1.3)

                rows.append((
                    article_id,
                    chapter_name,
                    topic,
                    item["chunk_type"],
                    item["chunk_text"],
                    token_count,
                    self.model_name,
                    emb
                ))

            # 4. Insert into document_chunks
            insert_sql = """
                INSERT INTO document_chunks (
                    prid, chapter_name, topic, chunk_type,
                    chunk_text, token_count, embedding_model, embedding_1024
                ) VALUES %s;
            """

            with self.conn.cursor() as cur:
                execute_values(cur, insert_sql, rows)
                self.conn.commit()

            processed += 1
            print(f"    [✓] Inserted {len(rows)} atomic chunks into document_chunks (NeonDB).")

            # 20-second delay between successful vectorizations to prevent API throttling
            if processed < limit:
                print(f"    [⏳] Pausing for {delay_seconds} seconds before next ingestion...")
                time.sleep(delay_seconds)

        print("\n" + "=" * 80)
        print(f"VECTOR INGESTION COMPLETE: Processed {processed} new smart notes.")
        print("=" * 80)


if __name__ == "__main__":
    vectorizer = SmartNotesVectorizer(model_name="voyage-3-large")
    vectorizer.process_smart_notes(limit=5, delay_seconds=30.0)
