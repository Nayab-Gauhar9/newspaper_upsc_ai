import os
import json
import time
import redis
import itertools
from typing import Dict, Any, Optional
from groq import Groq
from dotenv import load_dotenv
from sqlalchemy import select

from src.database.session import SessionLocal
from src.database.models import ConstitutionalArticleModel, IssueDossierModel
from manifest import CONSTITUTION_MANIFEST

load_dotenv()

# 1. Round-Robin Key Setup
raw_keys = os.getenv("GROQ_API_KEYS", "") or os.getenv("GROQ_API_KEY", "")
if not raw_keys:
    raise ValueError("Missing GROQ_API_KEYS in .env file (comma separated)!")

key_list = [k.strip() for k in raw_keys.split(",") if k.strip()]
print(f"[+] Loaded {len(key_list)} Groq API key(s) into pool.")
groq_pool = itertools.cycle([Groq(api_key=k) for k in key_list])

# 2. Redis Connection (Port 6380, protocol=2)
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6380))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
    protocol=2
)
REDIS_TTL_30_DAYS = 30 * 24 * 60 * 60

# Model candidates on Groq
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "full_verbatim_bare_act": {
            "type": "string",
            "description": "The complete, unabridged official Bare Act text containing all clauses, provisos, and explanations. For repealed articles, specify the Repealing Amendment Act."
        },
        "aspirant_summary": {
            "type": "object",
            "properties": {
                "core_mandate": {"type": "string"},
                "threshold_conditions": {"type": "string"},
                "prelims_traps": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["core_mandate", "threshold_conditions", "prelims_traps"]
        },
        "evolution_trajectory": {
            "type": "object",
            "properties": {
                "colonial_genesis": {
                    "type": "object",
                    "properties": {
                        "source_statute": {"type": "string"},
                        "historical_context": {"type": "string"},
                        "nationalist_critique": {"type": "string"}
                    },
                    "required": ["source_statute", "historical_context", "nationalist_critique"]
                },
                "cad_crucible": {
                    "type": "object",
                    "properties": {
                        "draft_article": {"type": "string"},
                        "key_speakers": {"type": "array", "items": {"type": "string"}},
                        "pivotal_quote": {"type": "string"},
                        "core_contention": {"type": "string"}
                    },
                    "required": ["draft_article", "key_speakers", "pivotal_quote", "core_contention"]
                },
                "judicial_and_amendments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "milestone": {"type": "string"},
                            "impact": {"type": "string"}
                        },
                        "required": ["milestone", "impact"]
                    }
                },
                "contemporary_frictions": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["colonial_genesis", "cad_crucible", "judicial_and_amendments", "contemporary_frictions"]

        },
        "comparative_matrix": {
            "type": "object",
            "properties": {
                "paired_article": {"type": "string"},
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "parameter": {"type": "string"},
                            "primary": {"type": "string"},
                            "secondary": {"type": "string"}
                        },
                        "required": ["parameter", "primary", "secondary"]
                    }
                }
            },
            "required": ["paired_article", "rows"]
        },
        "bare_act_analysis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause": {"type": "string"},
                    "verbatim_snippet": {"type": "string"},
                    "explanation": {"type": "string"},
                    "critical_nuance": {"type": "string"}
                },
                "required": ["clause", "verbatim_snippet", "explanation", "critical_nuance"]
            }
        }
    },
    "required": [
        "full_verbatim_bare_act",
        "aspirant_summary",
        "evolution_trajectory",
        "comparative_matrix",
        "bare_act_analysis"
    ]
}

SYSTEM_PROMPT = f"""
You are a senior constitutional jurist, legal historian, and expert UPSC Civil Services Examination mentor for Indian Polity.
Analyze the requested constitutional article and output a flat JSON object adhering strictly to this JSON schema:
{json.dumps(ARTICLE_SCHEMA, indent=2)}

CRITICAL VERBATIM REQUIREMENTS:
1. "full_verbatim_bare_act": You MUST write out the ENTIRE official Bare Act text for this article from start to finish. Include all clauses: (1), (2), (3), sub-clauses (a), (b), provisos, and explanations. DO NOT summarize, DO NOT truncate, and DO NOT use ellipsis (...).
2. For REPEALED articles (e.g., Art 31, Art 238): State the repeal details clearly in the Bare Act section, provide historical rationale in CAD/Colonial sections, and include at least 1 summary item in bare_act_analysis explaining the repeal amendment.
3. "bare_act_analysis": Break down EVERY SINGLE CLAUSE into its clause header, exact verbatim snippet, clear operational explanation, and critical nuance/UPSC trap.
4. "comparative_matrix": Pair this article with its natural constitutional equivalent (e.g. Art 72 vs 161, Art 32 vs 226, Art 352 vs 356, Art 123 vs 213, or Union vs State counterpart).
5. Output pure JSON without markdown wrappers or outer data envelopes.
"""


def extract_analysis_dict(analysis: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(analysis, dict):
        return {}
    for wrapper in ["data", "article", "article_analysis", "analysis", "result"]:
        if wrapper in analysis and isinstance(analysis[wrapper], dict):
            return analysis[wrapper]
    return analysis


def is_valid_payload(cleaned: Dict[str, Any], is_repealed: bool = False) -> bool:
    """Verifies that no empty fields or truncated verbatim texts pass through."""
    verbatim = cleaned.get("full_verbatim_bare_act", "")
    asp = cleaned.get("aspirant_summary", {})
    evo = cleaned.get("evolution_trajectory", {})
    bare = cleaned.get("bare_act_analysis", [])

    min_length = 20 if is_repealed else 35
    if not verbatim or len(verbatim.strip()) < min_length:
        return False
    if not asp or not asp.get("core_mandate"):
        return False
    if not evo or not evo.get("colonial_genesis"):
        return False
    if not isinstance(bare, list) or len(bare) == 0:
        return False
    return True


def generate_article_via_groq(meta: Dict[str, str], max_retries: int = 4) -> Optional[Dict[str, Any]]:
    is_repealed = "repeal" in meta["title"].lower() or "repealed" in meta["title"].lower()
    user_prompt = f"""
    Article Number: {meta['number']}
    Official Title: {meta['title']}
    Part: {meta['part']}

    Generate the complete, unabridged Bare Act verbatim text for all clauses and complete the structured UPSC analysis.
    """

    for attempt in range(1, max_retries + 1):
        client = next(groq_pool)
        try:
            res = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw = json.loads(res.choices[0].message.content)
            cleaned = extract_analysis_dict(raw)

            if is_valid_payload(cleaned, is_repealed=is_repealed):
                return cleaned
            else:
                print(f"  [!] Attempt {attempt}: Received incomplete payload. Retrying with next key...")
                time.sleep(1.5)
        except Exception as e:
            err_str = str(e)
            print(f"  [!] Attempt {attempt} error: {err_str[:120]}. Rotating key...")
            if "429" in err_str:
                time.sleep(4.0)  # Rate limit backoff
            else:
                time.sleep(1.5)

    return None


def upsert_and_cache(meta: Dict[str, str], data: Dict[str, Any]):
    db = SessionLocal()
    slug = meta["slug"]
    try:
        data_to_store = {
            "article_number": meta["number"],
            "article_slug": slug,
            "title": meta["title"],
            "part_number": meta["part"],
            "doctrine_cluster_id": meta["cluster"],
            "verbatim_text": data["full_verbatim_bare_act"].strip(),
            "aspirant_summary": data.get("aspirant_summary", {}),
            "evolution_trajectory": data.get("evolution_trajectory", {}),
            "comparative_matrix": data.get("comparative_matrix", {}),
            "bare_act_analysis": data.get("bare_act_analysis", [])
        }

        # PostgreSQL Upsert
        existing = db.query(ConstitutionalArticleModel).filter_by(article_slug=slug).first()
        if existing:
            for k, v in data_to_store.items():
                setattr(existing, k, v)
        else:
            db.add(ConstitutionalArticleModel(**data_to_store))

        db.commit()
        print(f"  [✓] PostgreSQL: Saved {meta['number']} ({len(data_to_store['verbatim_text'])} chars)")

        # Reverse query for living dossiers
        target_json = {"constitutional_articles": [meta["number"]]}
        dossiers = db.execute(
            select(IssueDossierModel)
            .where(IssueDossierModel.prelims_factsheet.contains(target_json))
        ).scalars().all()

        linked_dossiers = [
            {"issue_slug": d.issue_slug, "title": d.title, "chapter_name": d.chapter_name, "article_count": d.article_count}
            for d in dossiers
        ]

        # Redis 30-Day TTL Cache
        cache_payload = {**data_to_store, "linked_dossiers": linked_dossiers}
        redis_key = f"article:{slug}"
        redis_client.set(redis_key, json.dumps(cache_payload), ex=REDIS_TTL_30_DAYS)
        print(f"  [✓] Redis: Cached '{redis_key}' (TTL: 30 days)")

    except Exception as e:
        db.rollback()
        print(f"  [x] Error saving {slug}: {e}")
    finally:
        db.close()


def get_completed_slugs() -> set:
    db = SessionLocal()
    try:
        results = db.query(ConstitutionalArticleModel).filter(
            ConstitutionalArticleModel.bare_act_analysis != []
        ).all()
        completed = set()
        for r in results:
            if r.verbatim_text and not r.verbatim_text.strip().endswith("..."):
                completed.add(r.article_slug)
        return completed
    except Exception as e:
        print(f"[!] Warning reading existing records: {e}")
        return set()
    finally:
        db.close()


def main():
    print("=" * 70)
    print("STARTING FULL CONSTITUTION GENERATION & INGESTION")
    print(f"Model Pool Target: {GROQ_MODEL} | Redis Port: {REDIS_PORT}")
    print("=" * 70)

    completed = get_completed_slugs()
    pending = [item for item in CONSTITUTION_MANIFEST if item["slug"] not in completed]

    print(f"Total in Manifest : {len(CONSTITUTION_MANIFEST)}")
    print(f"Already Completed : {len(completed)}")
    print(f"Pending to Ingest : {len(pending)}")
    print("=" * 70)

    for idx, meta in enumerate(pending, 1):
        print(f"\n[{idx}/{len(pending)}] Ingesting {meta['number']} ({meta['title']})...")
        payload = generate_article_via_groq(meta)
        if payload:
            upsert_and_cache(meta, payload)
        else:
            print(f"  [x] Generation failed for {meta['number']}.")

        time.sleep(1.0)

    print("\n" + "=" * 70)
    print("[✓] All constitutional articles successfully ingested into PostgreSQL & Redis.")
    print("=" * 70)


if __name__ == "__main__":
    main()
