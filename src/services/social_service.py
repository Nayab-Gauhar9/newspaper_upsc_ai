import os
import json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import or_

from src.database.models import ConstitutionalArticleModel, SocialCampaignQueue
from src.services.social_slide_renderer import (
    render_slide_1,
    render_slide_2,
    render_slide_3,
    render_slide_4,
    render_slide_5
)

# Groq API endpoint
import requests

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
STATIC_OUTPUT_DIR = os.path.join("static", "social_previews")

GROQ_SYSTEM_PROMPT = """
You are a senior constitutional scholar and UPSC GS-II mentor.
Analyze the provided database record of a Constitutional Article in rigorous depth.

CRITICAL INSTRUCTIONS:
1. Stay strictly factual to the provided provision. (e.g., if Article 200, strictly focus on the Governor and State Legislature; do not confuse with Article 111 / President / Parliament).
2. For Slide 2: Ensure cad_quote contains a substantive 2-3 sentence debate excerpt from the Constituent Assembly. Never leave it blank.
3. For Slide 3: Use the exact landmark case name from the database context as headline. Output 3 dynamic points with clear short titles and rigorous legal analysis.
4. For Slide 5: Provide complete, polished academic sentences. NEVER use trailing ellipses (...) anywhere in your output.

Return STRICT JSON ONLY matching this exact structure:
{
  "slides": [
    {
      "slide_num": "1 / 5",
      "tier_badge": "JURISPRUDENTIAL ARCHITECTURE • GS-II",
      "headline": "ARTICLE NUMBER",
      "subheadline": "CORE DOCTRINAL CATCHPHRASE",
      "thesis": "Concise 30-word thesis capturing the core constitutional friction.",
      "chips": ["Cluster: ...", "Domain: ...", "Pillar: ..."]
    },
    {
      "slide_num": "2 / 5",
      "tier_badge": "CONSTITUENT ASSEMBLY CRUCIBLE",
      "headline": "Colonial Genesis vs. Framers' Vision",
      "colonial_title": "COLONIAL ROOTS (STATUTE ANCESTRY)",
      "colonial_context": "Statute ancestry from Government of India Act 1935...",
      "cad_speaker": "Speaker name (e.g. Dr. B.R. Ambedkar)",
      "cad_quote": "Substantive Constituent Assembly debate excerpt...",
      "analytical_insight": "The structural constitutional paradox..."
    },
    {
      "slide_num": "3 / 5",
      "tier_badge": "THE JURISPRUDENTIAL TURNING POINT",
      "headline": "Exact Landmark Case Name from database",
      "subheadline": "Core Doctrinal Catchphrase",
      "points": [
        {"title": "1. Short Point Title", "desc": "Legal analysis..."},
        {"title": "2. Short Point Title", "desc": "Legal analysis..."},
        {"title": "3. Short Point Title", "desc": "Legal analysis..."}
      ]
    },
    {
      "slide_num": "4 / 5",
      "tier_badge": "PROCEDURAL MATRIX & EXAM TRAPS",
      "headline": "Constitutional Parameters & Traps",
      "rows": [
        {"param": "Parameter 1", "rule": "Exact rule", "trap": "Verified exam trap"},
        {"param": "Parameter 2", "rule": "Exact rule", "trap": "Verified exam trap"},
        {"param": "Parameter 3", "rule": "Exact rule", "trap": "Verified exam trap"},
        {"param": "Parameter 4", "rule": "Exact rule", "trap": "Verified exam trap"}
      ]
    },
    {
      "slide_num": "5 / 5",
      "tier_badge": "MAINS ANSWER-BUILDING BLUEPRINT",
      "headline": "GS-II Dialectical Framework",
      "dimensions": [
        ["1. Constitutional Anchor", "Complete sentence without ellipses..."],
        ["2. Jurisprudential Evolution", "Complete sentence without ellipses..."],
        ["3. Federal Friction Points", "Complete sentence without ellipses..."],
        ["4. Commission Recommendations", "Complete sentence without ellipses..."]
      ]
    }
  ]
}
"""

def synthesize_article_with_groq(article: ConstitutionalArticleModel) -> dict:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY environment variable is missing.")

    evolution = article.evolution_trajectory or {}
    cad = evolution.get("cad_crucible", {})
    cad_quote = cad.get("pivotal_quote", "")

    db_payload = {
        "article_number": article.article_number,
        "title": article.title,
        "part_number": article.part_number,
        "doctrine_cluster_id": article.doctrine_cluster_id,
        "aspirant_summary": article.aspirant_summary,
        "evolution_trajectory": evolution,
        "stored_cad_quote": cad_quote
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": GROQ_SYSTEM_PROMPT},
            {"role": "user", "content": f"Deconstruct and synthesize this constitutional article record:\n{json.dumps(db_payload)}"}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }

    res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body, timeout=45)
    res.raise_for_status()
    payload = json.loads(res.json()["choices"][0]["message"]["content"])

    # Fallback to DB quote if Groq missed it
    if not payload["slides"][1].get("cad_quote") and cad_quote:
        payload["slides"][1]["cad_quote"] = cad_quote

    return payload

def render_campaign_slides(article_number: str, slides: list, campaign_id: int) -> list[str]:
    """Renders all 5 slides to static storage and returns relative URLs."""
    clean_num = article_number.lower().replace(" ", "_").replace(".", "")
    camp_dir = os.path.join(STATIC_OUTPUT_DIR, f"{clean_num}_camp_{campaign_id}")
    os.makedirs(camp_dir, exist_ok=True)

    paths = []
    renderers = [render_slide_1, render_slide_2, render_slide_3, render_slide_4, render_slide_5]
    for idx, (slide, render_fn) in enumerate(zip(slides, renderers), start=1):
        rel_path = f"/static/social_previews/{clean_num}_camp_{campaign_id}/slide_{idx}.png"
        abs_path = os.path.join(camp_dir, f"slide_{idx}.png")
        render_fn(slide, abs_path)
        paths.append(rel_path)
    return paths

def generate_campaign_for_article(db: Session, article_query: str) -> SocialCampaignQueue:
    """Manually triggers generation for an article query (e.g., '200' or 'article-200')."""
    article = db.query(ConstitutionalArticleModel).filter(
        or_(
            ConstitutionalArticleModel.article_number.ilike(f"%{article_query}%"),
            ConstitutionalArticleModel.article_slug.ilike(f"%{article_query}%")
        )
    ).first()

    if not article:
        raise ValueError(f"Article '{article_query}' not found in database.")

    # 1. Groq Synthesis
    payload = synthesize_article_with_groq(article)
    slides = payload.get("slides", [])

    # 2. Persist queue row
    campaign = SocialCampaignQueue(
        article_id=article.id,
        article_number=article.article_number,
        title=article.title,
        status="PENDING_APPROVAL",
        slides_payload=payload,
        image_paths=[],
        caption=(
            f"Master {article.article_number}: {article.title}\n\n"
            f"Explore the CAD crucible, colonial origin, and Prelims traps on politymentor.com.\n\n"
            f"#UPSC #IndianPolity #GS2 #{article.article_number.replace(' ', '')}"
        )
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    # 3. Render initial images
    image_paths = render_campaign_slides(article.article_number, slides, campaign.id)
    campaign.image_paths = image_paths
    db.commit()
    db.refresh(campaign)

    return campaign