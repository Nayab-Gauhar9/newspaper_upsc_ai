import os
import re
import textwrap
import tempfile
from typing import Any
from sqlalchemy.orm import Session

from src.database.models import ConstitutionalArticleModel, SocialCampaignQueue
from src.storage.minio_client import NewspaperStorage
from src.services.pib_social_slide_renderer import (
    render_pib_slide_1,
    render_pib_slide_2,
    render_pib_slide_3,
    render_pib_slide_4,
    render_pib_slide_5,
    render_pib_slide_6,
)


def clean_unicode_for_pillow(text: Any) -> str:
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)
    replacements = {
        "₹": "Rs. ",
        "\u202f": " ",
        "\u00a0": " ",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "…": "...",
        "\t": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def coerce_linkage_to_str(link_item: Any) -> str:
    """Safely extracts title and description whether linkage is a dict or string."""
    if isinstance(link_item, dict):
        title = link_item.get("title", "").strip()
        desc = link_item.get("description", "").strip() or link_item.get("desc", "").strip()
        if title and desc:
            return f"{title} – {desc}"
        return title or desc
    return str(link_item or "")


def sanitize_topic_badge(topic_label: str) -> str:
    clean = topic_label.replace("_", " ").strip()
    clean = re.sub(r"(?i)relating to certain classes", "", clean)
    clean = re.sub(r"(?i)of the constitution", "", clean)
    clean = clean.strip().upper()
    return clean[:20] if len(clean) > 20 else clean


def clean_linkage_title(raw_link: str) -> tuple[str, str]:
    """Purely dynamic cleaner: splits titles and extracts parentheticals into descriptions."""
    text = clean_unicode_for_pillow(raw_link)
    text = re.sub(r"(?i)^m\.?\s*laxmi[a-z]*\s*(chapter:?)?\s*", "", text).strip()
    text = re.sub(r"(?i)^laxmi[a-z]*\s*(chapter:?)?\s*", "", text).strip()
    text = re.sub(r"^[\d\.\-\)\s•\*]+", "", text).strip()
    text = text.strip(":'\"- ").strip()

    title, desc = "", ""
    for sep in ["–", "—", ":", " - "]:
        if sep in text:
            parts = text.split(sep, 1)
            title = parts[0].strip(" '\"")
            desc = parts[1].strip(" '\"")
            break

    if not title:
        title = text.strip(" '\"")

    if not desc and "(" in title and title.endswith(")"):
        m = re.match(r"^(.*?)\s*\((.*?)\)$", title)
        if m:
            title = m.group(1).strip()
            desc = m.group(2).strip()

    if "(" in title and ")" not in title:
        title = title.replace("(", "").strip()
    if title.endswith(")") and "(" not in title:
        title = title[:-1].strip()
    if desc.endswith(")") and "(" not in desc:
        desc = desc[:-1].strip()

    return title, desc


def build_slides_from_pib_note(
    note_data: dict, topic_label: str = "Constitutional Milestone"
) -> dict:
    badge_text = sanitize_topic_badge(topic_label)

    # -------------------------------------------------------------------------
    # 1. Slide 1 (Title, Short Core Hook & Anchor Capsules)
    # -------------------------------------------------------------------------
    headline = "PIB DAILY DIGEST"
    raw_head = clean_unicode_for_pillow(note_data.get("headline", topic_label))
    first_phrase = raw_head.split("–")[0].split(":")[0].split(" - ")[0].strip(" '\"")
    subheadline = f"{first_phrase.upper()} • CONSTITUTIONAL LINKAGE"

    summary_raw = clean_unicode_for_pillow(note_data.get("summary", ""))

    clean_summary_for_split = re.sub(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.\s*", r"\1 ", summary_raw)
    sentences = re.split(r"(?<=[a-zA-Z0-9\)])[.!?]\s+", clean_summary_for_split)
    
    if sentences:
        core_hook = sentences[0].strip()
        if not core_hook.endswith((".", "!", "?")):
            core_hook += "."
    else:
        core_hook = textwrap.shorten(summary_raw, width=180, placeholder="...")

    raw_linkages = [
        clean_unicode_for_pillow(coerce_linkage_to_str(x))
        for x in note_data.get("backward_linkages", [])
    ]
    filtered_linkages = []
    structured_chips = []

    for link in raw_linkages:
        title, desc = clean_linkage_title(link)
        if not title:
            continue
        filtered_linkages.append({"title": title, "desc": desc})
        
        if len(structured_chips) < 3:
            structured_chips.append({
                "article": title,
                "tagline": desc if desc else "Constitutional & Statutory Anchor"
            })

    slide_1 = {
        "slide_num": "1 / 6",
        "tier_badge": f"PIB INTELLIGENCE • {badge_text}",
        "headline": headline,
        "subheadline": subheadline,
        "thesis": core_hook,
        "core_hook": core_hook,
        "chips": structured_chips,
    }

    # -------------------------------------------------------------------------
    # 2. Slide 2 (Full Summary & Strategic UPSC Value Analysis)
    # -------------------------------------------------------------------------
    why_matters = clean_unicode_for_pillow(note_data.get("why_it_matters", ""))

    slide_2 = {
        "slide_num": "2 / 6",
        "tier_badge": "WHY IT MATTERS FOR UPSC",
        "headline": "Strategic Governance & Institutional Analysis",
        "subheadline": "GS-II Syllabus & Doctrinal Value",
        "full_summary": summary_raw,
        "analytical_insight": why_matters,
        "points": [],
    }

    # -------------------------------------------------------------------------
    # 3. Slide 3 (Smart Notes Dossier)
    # -------------------------------------------------------------------------
    smart_notes = [
        clean_unicode_for_pillow(x) for x in note_data.get("smart_notes", [])
    ]
    formatted_notes = []
    for idx, item in enumerate(smart_notes[:4], 1):
        title_part = ""
        desc_part = item
        for sep in ["–", "—", ":", " - "]:
            if sep in item:
                parts = item.split(sep, 1)
                title_part = parts[0].strip(" '\"")
                desc_part = parts[1].strip(" '\"")
                break
        
        if not title_part:
            title_part = f"Directive #{idx}"

        formatted_notes.append({
            "title": title_part,
            "desc": desc_part,
        })

    slide_3 = {
        "slide_num": "3 / 6",
        "tier_badge": "SMART NOTES DOSSIER",
        "headline": "Key Facts, Data & Directives",
        "subheadline": "Targeted UPSC Current Affairs Deconstruction",
        "notes": formatted_notes,
    }

    # -------------------------------------------------------------------------
    # 4. Slide 4 (100% Dynamic Backward Linkages)
    # -------------------------------------------------------------------------
    slide_4 = {
        "slide_num": "4 / 6",
        "tier_badge": "BACKWARD LINKAGES",
        "headline": "Constitutional & Statutory Anchors",
        "subheadline": "Relevant Articles, Doctrines & Precedents",
        "points": filtered_linkages[:10],
    }

    # -------------------------------------------------------------------------
    # 5. Slide 5 (Dynamic Prelims Traps & Mains Question)
    # -------------------------------------------------------------------------
    practice_points = note_data.get("prelims_practice_points", [])
    rows = []
    
    for idx, pt in enumerate(practice_points[:2], 1):
        if not isinstance(pt, dict):
            continue
        stmt = clean_unicode_for_pillow(pt.get("statement", "") or pt.get("rule", ""))
        expl = clean_unicode_for_pillow(pt.get("explanation", ""))
        trap_val = clean_unicode_for_pillow(pt.get("trap", ""))

        rule_text = expl if expl else stmt
        if trap_val:
            trap_text = trap_val
        elif pt.get("is_correct") is False:
            trap_text = stmt
        else:
            trap_text = f"Assuming provision is absolute or without statutory limitations: {stmt}"

        rows.append({
            "param": f"Prelims Fact #{idx}",
            "rule": rule_text if rule_text.endswith(".") else f"{rule_text}.",
            "trap": trap_text if trap_text.endswith(".") else f"{trap_text}.",
        })

    mains_q = clean_unicode_for_pillow(note_data.get("mains_question", ""))

    slide_5 = {
        "slide_num": "5 / 6",
        "tier_badge": "PRELIMS DRILL & MAINS QUESTION",
        "headline": "Exam Crucible & Application",
        "rows": rows,
        "mains_question": mains_q,
    }

    # -------------------------------------------------------------------------
    # 6. Slide 6 (Platform Call-To-Action)
    # -------------------------------------------------------------------------
    slide_6 = {
        "slide_num": "6 / 6",
        "tier_badge": "JOIN THE ECOSYSTEM",
        "headline": "MASTER UPSC POLITY WITH AI PRECISION",
        "subheadline": "Your GS-II Constitutional Intelligence Terminal",
        "website": "politymentor.com",
        "telegram": "t.me/polity_mentor_ai",
        "instagram": "@politymentor_ai",
    }

    return {"slides": [slide_1, slide_2, slide_3, slide_4, slide_5, slide_6]}


def render_pib_campaign_slides(campaign_id: int, slides: list) -> list[str]:
    scratch_dir = os.path.join(tempfile.gettempdir(), f"pib_camp_{campaign_id}")
    os.makedirs(scratch_dir, exist_ok=True)

    storage = NewspaperStorage(force_r2=True)
    urls = []
    renderers = [
        render_pib_slide_1,
        render_pib_slide_2,
        render_pib_slide_3,
        render_pib_slide_4,
        render_pib_slide_5,
        render_pib_slide_6,
    ]

    cdn_base = os.getenv(
        "R2_PUBLIC_DOMAIN", "https://media.politymentor.com"
    ).rstrip("/")

    for idx, (slide, render_fn) in enumerate(zip(slides, renderers), start=1):
        filename = f"slide_{idx}.png"
        local_png_path = os.path.join(scratch_dir, filename)

        render_fn(slide, local_png_path)

        object_key = f"campaigns/pib/camp_{campaign_id}/{filename}"

        if hasattr(storage, "upload_file"):
            storage.upload_file(
                local_file_path=local_png_path, object_name=object_key
            )
        else:
            storage.upload_and_get_presigned_url(
                local_file_path=local_png_path, object_name=object_key
            )

        public_cdn_url = f"{cdn_base}/{object_key}"
        urls.append(public_cdn_url)

    return urls


def fetch_actual_latest_pib_note() -> tuple[dict, str]:
    storage = NewspaperStorage(force_r2=True)

    if hasattr(storage, "list_latest_smart_notes"):
        try:
            notes = storage.list_latest_smart_notes(limit=1)
            if notes and isinstance(notes, list):
                note = notes[0]
                obj_key = (
                    note.get("object_key")
                    or note.get("minio_key")
                    or note.get("key", "")
                )
                note_payload = note.get("smart_notes", note)
                return note_payload, obj_key
        except Exception:
            pass

    if hasattr(storage, "get_latest_pib_smart_note"):
        return storage.get_latest_pib_smart_note()

    raise FileNotFoundError(
        "Unable to retrieve latest PIB smart note from NewspaperStorage."
    )


def generate_campaign_for_latest_pib(db: Session) -> SocialCampaignQueue:
    note_data, object_key = fetch_actual_latest_pib_note()

    parts = object_key.split("/") if object_key else []
    if len(parts) >= 4:
        topic_label = parts[-2].replace("_", " ")
    elif len(parts) > 2:
        topic_label = parts[2].replace("_", " ")
    else:
        topic_label = "Current Affairs"

    payload = build_slides_from_pib_note(note_data, topic_label)
    slides = payload.get("slides", [])

    headline = note_data.get("headline", "PIB Constitutional Dossier")
    raw_linkages = [
        clean_unicode_for_pillow(coerce_linkage_to_str(x))
        for x in note_data.get("backward_linkages", [])
    ]
    top_linkages = [
        b.split("–")[0].split("-")[0].split(":")[0].strip(" '\"")
        for b in raw_linkages[:3]
    ]

    resolved_article = None
    for link in raw_linkages:
        match = re.search(r"Article\s+(\d+[A-Za-z]*)", link, re.IGNORECASE)
        if match:
            art_str = f"Article {match.group(1)}"
            resolved_article = (
                db.query(ConstitutionalArticleModel)
                .filter(ConstitutionalArticleModel.article_number.ilike(art_str))
                .first()
            )
            if resolved_article:
                break

    if not resolved_article:
        resolved_article = db.query(ConstitutionalArticleModel).first()

    article_id = resolved_article.id if resolved_article else 1

    campaign = SocialCampaignQueue(
        article_id=article_id,
        article_number=f"PIB: {sanitize_topic_badge(topic_label)}",
        title=headline[:250],
        status="PENDING_APPROVAL",
        slides_payload=payload,
        image_paths=[],
        caption=(
            f"PIB Constitutional Brief: {headline}\n\n"
            f"Key Anchors: {', '.join(top_linkages)}\n\n"
            f"Read the complete smart note dossier on politymentor.com.\n\n"
            f"#UPSC #IndianPolity #GS2 #PIB #CurrentAffairs"
        ),
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    image_urls = render_pib_campaign_slides(campaign.id, slides)
    campaign.image_paths = image_urls
    db.commit()
    db.refresh(campaign)

    return campaign