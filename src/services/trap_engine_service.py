import os
import json
import requests
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

ANALYTICAL_TRAP_PROMPT = """
You are a senior UPSC Civil Services Examination Indian Polity question framer and constitutional jurist.
Your task is to transform the provided legal/constitutional context into a high-stakes, deeply conceptual, and analytical UPSC GS-II Prelims question with an exhaustive Distractor Trap analysis, strictly matching the requested format archetype.

STRICT GROUNDING & VERACITY DIRECTIVE (CRITICAL):
1. GROUNDED IN DATABASE DETAILS ONLY: You must derive all premises, statements, thresholds, authorities, and legal doctrines STRICTLY and EXCLUSIVELY from the provided database records (verbatim text, bare act analysis, aspirant summary, prelims factsheet, and comparative matrices).
2. ZERO HALLUCINATION / ZERO DOCTRINE FABRICATION:
   - Do NOT invent case names, misattribute Article clauses, or invent procedural thresholds not supported by the input context.
   - For Article 1 to 4: The admission or establishment of new States (Article 2) and formation/alteration of areas/boundaries (Article 3) is done by Parliament by ordinary law (simple majority) under Article 4(2), NOT Article 368. Ceding territory to a foreign power requires an amendment under Article 368 (Berubari Union, 1960), but ordinary acquisition does not.
   - For Emergency Powers: Article 352 proclamation approval is strictly 1 MONTH by SPECIAL MAJORITY (post-44th Amendment 1978). Article 356 and Article 360 are 2 MONTHS by SIMPLE MAJORITY.
   - If a statement is marked correct, it MUST be 100% legally and constitutionally indisputable in modern Indian constitutional law.
3. FORMAT-SPECIFIC SCHEMAS (MANDATORY MATCH):
   - If target_format is "STATEMENT_I_II":
     * question_stem must be: "Consider the following statements:"
     * statements_payload must contain: "format": "STATEMENT_I_II", "statement_1": "...", "statement_2": "..."
     * options must be standard A/B/C/D causality options.
   - If target_format is "HOW_MANY":
     * question_stem must ask a precise counting question (e.g., "Consider the following statements regarding [Topic]:").
     * statements_payload must contain: "format": "HOW_MANY", "statement_1": "...", "statement_2": "...", "statement_3": "..." (3 distinct legal propositions for aspirants to count).
     * options must be exactly: {"A": "Only one", "B": "Only two", "C": "All three", "D": "None"}.
     * correct_option must be "A", "B", "C", or "D".
   - If target_format is "STANDARD_BRACKET":
     * question_stem must be: "Consider the following statements:"
     * statements_payload must contain: "format": "STANDARD_BRACKET", "statement_1": "...", "statement_2": "...", "statement_3": "..."
     * options must be combination codes like {"A": "1 and 2 only", "B": "2 and 3 only", "C": "1 and 3 only", "D": "1, 2 and 3"}.
     * correct_option must be "A", "B", "C", or "D".

Return STRICT JSON ONLY matching this exact structure:
{
  "topic": "Concise Analytical Topic",
  "question_format": "STATEMENT_I_II", 
  "trap_archetype": "CAUSAL_DOCTRINAL_DISCONNECT",
  "question_stem": "Consider the following statements:",
  "statements_payload": {
    "format": "STATEMENT_I_II",
    "statement_1": "Statement testing the operational rule or institutional action...",
    "statement_2": "Statement asserting the purported constitutional justification or ratio...",
    "statement_3": "Statement testing an exception or boundary proviso..."
  },
  "options": {
    "A": "Both Statement-I and Statement-II are correct and Statement-II is the correct explanation for Statement-I",
    "B": "Both Statement-I and Statement-II are correct and Statement-II is not the correct explanation for Statement-I",
    "C": "Statement-I is correct but Statement-II is incorrect",
    "D": "Statement-I is incorrect but Statement-II is correct"
  },
  "correct_option": "B",
  "conceptual_analysis": {
    "core_constitutional_doctrine": "Name of doctrine (e.g., Non-Arbitrariness, Basic Structure, Territorial Integrity)",
    "why_candidates_falter": "Detailed breakdown of the cognitive blindspot aspirants suffer from...",
    "substantive_legal_holding": "The authentic constitutional mechanism or Supreme Court ratio that governs this boundary...",
    "distractor_dissection": "Precise forensic explanation of how the distractor statement deceived the candidate..."
  },
  "elimination_heuristic": "How an alert candidate analyzes the constitutional provision to eliminate incorrect options...",
  "source_citation": "Exact Constitutional Provision & Landmark Precedent"
}
"""

def generate_analytical_trap_from_article(db: Session, article_number: str, preferred_format: str = "STATEMENT_I_II") -> Dict[str, Any]:
    """Generates an analytical conceptual trap strictly anchored to bare act clauses and curated traps in the DB."""
    
    clean_num = str(article_number).lower().replace("article", "").strip()
    
    row = db.execute(
        text("SELECT * FROM constitutional_articles WHERE LOWER(article_number) = :num OR article_slug = :slug LIMIT 1"),
        {"num": f"article {clean_num}", "slug": f"article-{clean_num}"}
    ).mappings().first()

    if not row:
        raise ValueError(f"Article '{clean_num}' not found in constitutional_articles.")

    context = {
        "source_type": "CONSTITUTIONAL_ARTICLE",
        "article_number": row["article_number"],
        "title": row["title"],
        "part_number": row.get("part_number"),
        "verbatim_text": row["verbatim_text"][:3500],
        "bare_act_analysis": row.get("bare_act_analysis", []),
        "aspirant_summary": row.get("aspirant_summary", {}),
        "comparative_matrix": row.get("comparative_matrix"),
        "evolution_trajectory": row.get("evolution_trajectory", {}),
        "target_format": preferred_format
    }
    
    result = _call_analytical_engine(context)
    
    # INJECTION: Pass the DB's verified prelims_traps to the payload for Slide 3 rendering
    db_traps = row.get("aspirant_summary", {}).get("prelims_traps", [])
    result["db_prelims_traps"] = db_traps if isinstance(db_traps, list) else []
    
    return result

def generate_analytical_trap_from_dossier(db: Session, issue_slug: str, preferred_format: str = "STATEMENT_I_II") -> Dict[str, Any]:
    """Generates an analytical conceptual trap strictly anchored to verified factsheets and edge claims."""
    dossier = db.execute(
        text("SELECT * FROM issue_dossiers WHERE issue_slug = :slug LIMIT 1"),
        {"slug": issue_slug}
    ).mappings().first()

    if not dossier:
        raise ValueError(f"Dossier '{issue_slug}' not found.")

    edges = db.execute(
        text("SELECT * FROM issue_graph_edges WHERE issue_slug = :slug ORDER BY event_date DESC LIMIT 4"),
        {"slug": issue_slug}
    ).mappings().all()

    context = {
        "source_type": "LIVING_DOSSIER",
        "title": dossier["title"],
        "chapter_name": dossier["chapter_name"],
        "canonical_summary": dossier.get("canonical_summary"),
        "mains_framework": dossier.get("mains_framework"),
        "prelims_factsheet": dossier.get("prelims_factsheet"),
        "verified_disputes": [
            {
                "claim": e["core_claim"],
                "anchors": e["legal_anchors"],
                "facts": e.get("prelims_event_facts", {})
            }
            for e in edges
        ],
        "target_format": preferred_format
    }
    return _call_analytical_engine(context)

def generate_analytical_trap_from_pyq(db: Session, pyq_id: int, preferred_format: str = "STATEMENT_I_II") -> Dict[str, Any]:
    """Mutates an authentic 30-year UPSC Prelims PYQ into a contemporary conceptual trap variant using its DB explanation."""
    pyq = db.execute(
        text("SELECT * FROM prelims_pyqs WHERE id = :id LIMIT 1"),
        {"id": pyq_id}
    ).mappings().first()

    if not pyq:
        raise ValueError(f"PYQ #{pyq_id} not found.")

    context = {
        "source_type": "PYQ_MUTATION",
        "original_year": pyq["year"],
        "chapter_name": pyq["chapter_name"],
        "question_text": pyq["question_text"],
        "options": pyq["options"],
        "correct_option": pyq["correct_option"],
        "explanation": pyq.get("explanation", ""),
        "target_format": preferred_format
    }
    return _call_analytical_engine(context)

def _call_analytical_engine(payload: dict) -> Dict[str, Any]:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY environment variable is missing.")

    target_fmt = payload.get("target_format", "STATEMENT_I_II")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": ANALYTICAL_TRAP_PROMPT},
            {
                "role": "user", 
                "content": (
                    f"TARGET QUESTION FORMAT: {target_fmt}\n"
                    "Using the following database record as the absolute single source of truth, "
                    "construct an authentic, analytically precise UPSC Prelims Distractor Trap question. "
                    "Ensure all threshold numbers, article provisos, and legal claims strictly mirror "
                    "the verified law and match the requested format archetype:\n"
                    f"{json.dumps(payload, ensure_ascii=False)}"
                )
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }

    res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body, timeout=45)
    res.raise_for_status()
    return json.loads(res.json()["choices"][0]["message"]["content"])