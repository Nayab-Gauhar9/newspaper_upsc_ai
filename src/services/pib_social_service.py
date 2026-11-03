import os
import re
import tempfile
from sqlalchemy.orm import Session

from src.database.models import ConstitutionalArticleModel, SocialCampaignQueue
from src.storage.minio_client import NewspaperStorage
from src.services.pib_social_slide_renderer import (
    render_pib_slide_1,
    render_pib_slide_2,
    render_pib_slide_3,
    render_pib_slide_4,
    render_pib_slide_5,
    render_pib_slide_6
)

def clean_unicode_for_pillow(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "₹": "Rs. ", "\u202f": " ", "\u00a0": " ",
        "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "…": "", "\t": " "
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()

def sanitize_topic_badge(topic_label: str) -> str:
    clean = topic_label.replace("_", " ").strip()
    clean = re.sub(r"(?i)relating to certain classes", "", clean)
    clean = re.sub(r"(?i)of the constitution", "", clean)
    clean = clean.strip().upper()
    return clean[:20] if len(clean) > 20 else clean

def build_slides_from_pib_note(note_data: dict, topic_label: str = "Constitutional Milestone") -> dict:
    badge_text = sanitize_topic_badge(topic_label)

    # 1. Slide 1 (Overview & Thesis)
    headline = "PIB DAILY DIGEST"
    raw_head = clean_unicode_for_pillow(note_data.get("headline", topic_label))
    first_phrase = raw_head.split("–")[0].split(":")[0].split("-")[0].strip()
    subheadline = f"{first_phrase.upper()[:26]} • CONSTITUTIONAL LINKAGE"

    summary_raw = clean_unicode_for_pillow(note_data.get("summary", ""))
    first_sentence = summary_raw.split(". ")[0].strip()
    thesis = first_sentence if first_sentence.endswith(".") else f"{first_sentence}."

    raw_linkages = [clean_unicode_for_pillow(x) for x in note_data.get("backward_linkages", [])]
    chips = [link.split("–")[0].split("-")[0].split(":")[0].strip()[:20] for link in raw_linkages[:3]]

    slide_1 = {
        "slide_num": "1 / 6",
        "tier_badge": f"PIB INTELLIGENCE • {badge_text}",
        "headline": headline,
        "subheadline": subheadline,
        "thesis": thesis,
        "chips": chips or ["GS-II", "Polity", "Current Affairs"]
    }

    # 2. Slide 2 (Why It Matters for UPSC)
    why_matters = clean_unicode_for_pillow(note_data.get("why_it_matters", summary_raw))
    smart_notes = [clean_unicode_for_pillow(x) for x in note_data.get("smart_notes", [])]

    slide_2 = {
        "slide_num": "2 / 6",
        "tier_badge": "WHY IT MATTERS FOR UPSC",
        "headline": "Strategic Governance & Institutional Analysis",
        "subheadline": "GS-II Syllabus & Doctrinal Value",
        "analytical_insight": why_matters,
        "points": [
            {"title": "Core Policy Focus", "desc": smart_notes[0] if smart_notes else summary_raw},
            {"title": "Administrative Milestone", "desc": smart_notes[1] if len(smart_notes) > 1 else "Establishes key federal policy precedents."}
        ]
    }

    # 3. Slide 3 (Smart Notes Dossier)
    formatted_notes = []
    for idx, item in enumerate(smart_notes[:4], 1):
        if "–" in item:
            parts = item.split("–", 1)
        elif ":" in item:
            parts = item.split(":", 1)
        elif "-" in item:
            parts = item.split("-", 1)
        else:
            parts = [f"Directive #{idx}", item]

        formatted_notes.append({
            "title": parts[0].strip()[:32],
            "desc": parts[1].strip() if len(parts) > 1 else parts[0].strip()
        })

    slide_3 = {
        "slide_num": "3 / 6",
        "tier_badge": "SMART NOTES DOSSIER",
        "headline": "Key Facts, Data & Directives",
        "subheadline": "Targeted UPSC Current Affairs Deconstruction",
        "notes": formatted_notes
    }

    # 4. Slide 4 (Backward Linkages - All Items)
    linkage_tiles = []
    for idx, link in enumerate(raw_linkages, 1):
        if "–" in link:
            parts = link.split("–", 1)
        elif "-" in link:
            parts = link.split("-", 1)
        elif ":" in link:
            parts = link.split(":", 1)
        else:
            parts = [link, ""]

        linkage_tiles.append({
            "title": parts[0].strip(),
            "desc": parts[1].strip() if len(parts) > 1 else ""
        })

    slide_4 = {
        "slide_num": "4 / 6",
        "tier_badge": "BACKWARD LINKAGES",
        "headline": "Constitutional & Statutory Anchors",
        "subheadline": "Relevant Articles, Doctrines & Precedents",
        "points": linkage_tiles
    }

    # 5. Slide 5 (Prelims Drill & Mains Question)
    practice_points = note_data.get("prelims_practice_points", [])
    rows = []
    for idx, pt in enumerate(practice_points[:2], 1):
        stmt = clean_unicode_for_pillow(pt.get("statement", ""))
        expl = clean_unicode_for_pillow(pt.get("explanation", ""))
        is_corr = pt.get("is_correct", False)

        rule_text = expl if expl else stmt
        trap_text = "Assuming this provision is discretionary or subject to executive dilution." if is_corr else stmt

        rows.append({
            "param": f"Prelims Fact #{idx}",
            "rule": rule_text if rule_text.endswith(".") else f"{rule_text}.",
            "trap": trap_text if trap_text.endswith(".") else f"{trap_text}."
        })

    mains_q = clean_unicode_for_pillow(note_data.get("mains_question", ""))

    slide_5 = {
        "slide_num": "5 / 6",
        "tier_badge": "PRELIMS DRILL & MAINS QUESTION",
        "headline": "Exam Crucible & Application",
        "rows": rows,
        "mains_question": mains_q
    }

    # 6. Slide 6 (CTA Card)
    slide_6 = {
        "slide_num": "6 / 6",
        "tier_badge": "JOIN THE ECOSYSTEM",
        "headline": "MASTER UPSC POLITY WITH AI PRECISION",
        "subheadline": "Your GS-II Constitutional Intelligence Terminal",
        "website": "politymentor.com",
        "telegram": "t.me/polity_mentor_ai",
        "instagram": "@politymentor_ai"
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
        render_pib_slide_6
    ]

    # Set expiry to maximum 7 days (60 * 24 * 7 minutes = 10080 minutes)
    SEVEN_DAYS_MINUTES = 60 * 24 * 7

    for idx, (slide, render_fn) in enumerate(zip(slides, renderers), start=1):
        filename = f"slide_{idx}.png"
        local_png_path = os.path.join(scratch_dir, filename)

        render_fn(slide, local_png_path)

        object_key = f"campaigns/pib/camp_{campaign_id}/{filename}"
        presigned_url = storage.upload_and_get_presigned_url(
            local_file_path=local_png_path,
            object_name=object_key,
            expiry_minutes=SEVEN_DAYS_MINUTES
        )
        urls.append(presigned_url)

    return urls

def generate_campaign_for_latest_pib(db: Session) -> SocialCampaignQueue:
    storage = NewspaperStorage(force_r2=True)
    note_data, object_key = storage.get_latest_pib_smart_note()

    parts = object_key.split("/")
    topic_label = parts[2].replace("_", " ") if len(parts) > 2 else "Current Affairs"

    payload = build_slides_from_pib_note(note_data, topic_label)
    slides = payload.get("slides", [])

    headline = note_data.get("headline", "PIB Constitutional Dossier")
    raw_linkages = [clean_unicode_for_pillow(x) for x in note_data.get("backward_linkages", [])]
    top_linkages = [b.split("–")[0].split("-")[0].split(":")[0].strip() for b in raw_linkages[:3]]

    resolved_article = None
    for link in raw_linkages:
        match = re.search(r"Article\s+(\d+[A-Za-z]*)", link, re.IGNORECASE)
        if match:
            art_str = f"Article {match.group(1)}"
            resolved_article = db.query(ConstitutionalArticleModel).filter(
                ConstitutionalArticleModel.article_number.ilike(art_str)
            ).first()
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
        )
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    image_urls = render_pib_campaign_slides(campaign.id, slides)
    campaign.image_paths = image_urls
    db.commit()
    db.refresh(campaign)

    return campaign