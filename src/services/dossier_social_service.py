import os
import re
import json
import tempfile
import requests
from typing import List, Dict, Any

from src.storage.minio_client import NewspaperStorage
from src.services.dossier_slide_renderer import (
    render_dossier_slide_1,
    render_dossier_slide_2,
    render_dossier_slide_3,
    render_dossier_slide_4,
    render_dossier_slide_5,
    render_dossier_slide_6
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

def format_clean_boundary(text: str, max_chars: int = 42) -> str:
    """Truncates text cleanly at a word boundary without cutting through words or brackets."""
    if not text:
        return ""
    cleaned = str(text).strip()
    if len(cleaned) <= max_chars:
        return cleaned

    truncated = cleaned[:max_chars].rsplit(" ", 1)[0]
    
    if "(" in truncated and ")" not in truncated[truncated.rfind("("):]:
        truncated = truncated[:truncated.rfind("(")].strip()
        
    return truncated.rstrip(",;:- ")

GROQ_DOSSIER_SYSTEM_PROMPT = """
You are an expert constitutional jurist and UPSC GS-II senior mentor.
Transform the provided Evolving Constitutional Dossier record and its chronological graph edge updates into an authoritative, clean, and punchy 6-slide Instagram carousel payload.

STRICT CONSTRAINTS:
1. Stay strictly anchored to the facts, legal anchors, statutes, and claims in the payload. Do not invent unrelated case laws or statutes.
2. Slide 1 (Headline & Genesis): Headline must be concise, punchy (maximum 14 words), avoiding any cutoffs. Genesis must be 2-3 clean, well-formed sentences summarizing the trigger.
3. Slide 2 (Static Anchors): Provide 2 to 3 anchors. For EACH anchor, write a crisp 1-sentence legal rationale explaining why this specific provision is contested in THIS dispute. NEVER provide generic boilerplate or identical descriptions across cards.
4. Slide 3 & 4 (Event Nodes / Ramifications): Distill each node into clear legal actions (2-3 sentences max).
5. Slide 5 (Dialectical Standoff): Frame Thesis (State/Union/Statutory authority) and Critique (Constitutional/Fundamental Rights/Federalism challenge) as complete, polished sentences. Never leave trailing ellipses (...).

Return STRICT JSON ONLY matching this exact structure:
{
  "slides": [
    {
      "slide_num": "1 / 6",
      "tier_badge": "DOSSIER • [CHAPTER NAME IN UPPERCASE]",
      "headline": "Punchy 10-14 word headline without cutoffs",
      "subheadline": "Dynamic Dispute • Mapped to GS-II",
      "summary": "Crisp 2-3 sentence overview of the dispute genesis.",
      "nodal_body": "Nodal institution name"
    },
    {
      "slide_num": "2 / 6",
      "tier_badge": "STATIC CONSTITUTIONAL ANCHORS",
      "headline": "Constitutional & Statutory Anchors",
      "subheadline": "Static Law Grounding the Dynamic Dispute",
      "anchors": [
        {"title": "Article / Act Name", "desc": "Context-specific legal reason why it applies here."},
        {"title": "Article / Act Name", "desc": "Context-specific legal reason why it applies here."}
      ]
    },
    {
      "slide_num": "3 / 6",
      "tier_badge": "DISPUTE TIMELINE",
      "headline": "Dispute Genesis & Early Trajectory",
      "subheadline": "Documenting Initial Legal Escalation",
      "nodes": [
        {"title": "Milestone Title", "body": "Clean 2-sentence description of the event and its legal claim."}
      ]
    },
    {
      "slide_num": "4 / 6",
      "tier_badge": "LEGAL FRICTION & HORIZON",
      "headline": "Recent Escalation & Contestation",
      "subheadline": "Current Institutional Posture & Thresholds",
      "points": [
        {"title": "1. Active Contestation", "desc": "What is currently being challenged."},
        {"title": "2. Executive / Statutory Stance", "desc": "Institutional response or notice status."},
        {"title": "3. Judicial Horizon", "desc": "Expected constitutional ratio or procedural test."}
      ]
    },
    {
      "slide_num": "5 / 6",
      "tier_badge": "THE DIALECTICAL STANDOFF",
      "headline": "The Constitutional Stand-Off",
      "subheadline": "Thesis vs. Jurisprudential Critique",
      "thesis": "Complete legal argument supporting state or administrative authority.",
      "critique": "Complete legal argument challenging the action under constitutional doctrines."
    }
  ]
}
"""

def synthesize_dossier_with_groq(dossier: Dict[str, Any], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Uses Groq to synthesize nuanced, context-aware slides for the dossier."""
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY environment variable is missing.")

    num_edges = len(edges)
    sorted_edges = sorted(edges, key=lambda x: str(x.get("event_date", "")))

    db_context = {
        "title": dossier.get("title"),
        "chapter_name": dossier.get("chapter_name"),
        "status": dossier.get("status"),
        "canonical_summary": dossier.get("canonical_summary"),
        "prelims_factsheet": dossier.get("prelims_factsheet"),
        "mains_framework": dossier.get("mains_framework"),
        "total_updates_count": num_edges,
        "chronological_edges": [
            {
                "date": str(e.get("event_date")),
                "publication": str(e.get("publication")),
                "legal_anchors": e.get("legal_anchors"),
                "core_claim": e.get("core_claim")
            }
            for e in sorted_edges[:4]
        ]
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": GROQ_DOSSIER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Deconstruct and synthesize this dossier record into social slides:\n{json.dumps(db_context)}"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }

    res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body, timeout=45)
    res.raise_for_status()
    payload = json.loads(res.json()["choices"][0]["message"]["content"])
    slides = payload.get("slides", [])

    status_str = str(dossier.get("status", "ACTIVE")).upper()
    chapter_str = str(dossier.get("chapter_name", "Polity"))

    # Tracking banner text if more than 3 updates exist
    more_updates_notice = None
    if num_edges > 3:
        more_updates_notice = f"Tracking all {num_edges} updates • Full graph at politymentor.com"

    # Enrich Slides 1 through 5 with status, numbering, and bottom tracking banner
    for idx, s in enumerate(slides[:5], start=1):
        s["slide_num"] = f"{idx} / 6"
        s["status"] = status_str
        if more_updates_notice:
            s["more_updates_notice"] = more_updates_notice

    # Slide 1 specific chips setup
    if len(slides) > 0:
        slide_1 = slides[0]
        nodal = slide_1.get("nodal_body") or "Constitutional Bench"
        chips = [
            f"Nodal Body: {format_clean_boundary(nodal, max_chars=48)}",
            f"Subject: {chapter_str}"
        ]
        if num_edges == 1:
            chips.insert(1, "Status: Stage 1 (Genesis)")
        elif num_edges <= 3:
            chips.insert(1, f"Status: {num_edges} Milestones Documented")
        else:
            chips.insert(1, f"Status: {num_edges} Updates Documented")

        slide_1["chips"] = chips

    # Inject Slide 3 dates & publications directly from edges if missing
    if len(slides) > 2 and sorted_edges:
        raw_nodes = slides[2].get("nodes", [])
        for i, node in enumerate(raw_nodes):
            if i < len(sorted_edges):
                node["date"] = str(sorted_edges[i].get("event_date", "2026"))
                node["publication"] = str(sorted_edges[i].get("publication", "Apex Court")).upper()

    # Append Slide 6 (Ecosystem)
    slides = slides[:5]
    slides.append({
        "slide_num": "6 / 6",
        "tier_badge": "JOIN THE ECOSYSTEM",
        "headline": "MASTER UPSC POLITY WITH AI PRECISION",
        "subheadline": "Your GS-II Constitutional Intelligence Terminal",
        "website": "politymentor.com",
        "telegram": "t.me/polity_mentor_ai",
        "instagram": "@politymentor_ai"
    })

    return {"slides": slides}

def render_dossier_campaign_slides(campaign_id: int, slides: list) -> list[str]:
    scratch_dir = os.path.join(tempfile.gettempdir(), f"dossier_camp_{campaign_id}")
    os.makedirs(scratch_dir, exist_ok=True)

    storage = NewspaperStorage(force_r2=True)
    urls = []
    renderers = [
        render_dossier_slide_1,
        render_dossier_slide_2,
        render_dossier_slide_3,
        render_dossier_slide_4,
        render_dossier_slide_5,
        render_dossier_slide_6
    ]

    cdn_base = os.getenv("R2_PUBLIC_DOMAIN", "https://media.politymentor.com").rstrip("/")

    for idx, (slide, render_fn) in enumerate(zip(slides, renderers), start=1):
        filename = f"slide_{idx}.png"
        local_png_path = os.path.join(scratch_dir, filename)

        render_fn(slide, local_png_path)

        object_key = f"campaigns/dossiers/camp_{campaign_id}/{filename}"
        if hasattr(storage, "upload_file"):
            storage.upload_file(local_file_path=local_png_path, object_name=object_key)
        else:
            storage.upload_and_get_presigned_url(local_file_path=local_png_path, object_name=object_key)

        urls.append(f"{cdn_base}/{object_key}")

    return urls