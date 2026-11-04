import os
import re
from datetime import datetime
from typing import Optional, Union, List, Any
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.database.session import SessionLocal
from src.database.models import SocialCampaignQueue, PrelimsTrapMatrix
from src.services.instagram_publisher import InstagramPublisher
from src.storage.minio_client import NewspaperStorage
from src.services.social_service import (
    generate_campaign_for_article,
    render_campaign_slides
)
from src.services.pib_social_service import (
    generate_campaign_for_latest_pib,
    render_pib_campaign_slides
)
from src.services.dossier_social_service import (
    synthesize_dossier_with_groq,
    render_dossier_campaign_slides
)
from src.services.trap_engine_service import (
    generate_analytical_trap_from_article,
    generate_analytical_trap_from_dossier,
    generate_analytical_trap_from_pyq
)
from src.services.trap_slide_renderer import render_trap_campaign_slides

router = APIRouter(prefix="/api/admin/social", tags=["Social Cockpit"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def ensure_cdn_url(path: str) -> str:
    """Converts any path or legacy presigned R2 URL to a clean media.politymentor.com URL."""
    if not path:
        return ""
    
    cdn_base = os.getenv("R2_PUBLIC_DOMAIN", "https://media.politymentor.com").rstrip("/")

    # If it is already a clean CDN URL, return directly
    if path.startswith(cdn_base):
        return path

    # If it is a Cloudflare R2 presigned URL, strip out query signatures and bucket prefixes
    if "r2.cloudflarestorage.com" in path:
        clean_path = urlparse(path).path.lstrip("/")
        bucket = os.getenv("R2_BUCKET_NAME", "upsc-ai")
        if clean_path.startswith(f"{bucket}/"):
            clean_path = clean_path[len(bucket) + 1:]
        return f"{cdn_base}/{clean_path}"

    # If it's a relative object key
    if path.startswith("campaigns/"):
        return f"{cdn_base}/{path}"

    return path

# ---------------------------------------------------------------------------
# REQUEST SCHEMAS
# ---------------------------------------------------------------------------
class GenerateArticleRequest(BaseModel):
    article: Optional[str] = None
    article_number: Optional[str] = None
    tier: Optional[str] = "TIER_1"

    @model_validator(mode="before")
    def resolve_article_param(cls, values):
        if isinstance(values, dict):
            article_val = values.get("article") or values.get("article_number")
            if not article_val:
                raise ValueError("Must provide either 'article' or 'article_number'.")
            values["article"] = str(article_val).strip()
            values["article_number"] = str(article_val).strip()
        return values

class GenerateDossierRequest(BaseModel):
    issue_slug: str

class GenerateTrapArticleRequest(BaseModel):
    article: str
    format: Optional[str] = "STATEMENT_I_II"

class GenerateTrapDossierRequest(BaseModel):
    issue_slug: str
    format: Optional[str] = "STATEMENT_I_II"

class GenerateTrapPyqRequest(BaseModel):
    pyq_id: int
    format: Optional[str] = "STATEMENT_I_II"

class AmendCampaignRequest(BaseModel):
    slides_payload: Union[dict, List[Any]]
    caption: Optional[str] = None

# ---------------------------------------------------------------------------
# ARTICLE CAMPAIGN ENDPOINTS
# ---------------------------------------------------------------------------
@router.post("/generate")
def generate_draft(req: GenerateArticleRequest, db: Session = Depends(get_db)):
    """Triggers generation for a specific article into PENDING_APPROVAL status."""
    try:
        target_article = req.article or req.article_number
        campaign = generate_campaign_for_article(db, target_article)
        return {
            "status": "success",
            "message": f"Draft created for {campaign.article_number}",
            "campaign_id": campaign.id,
            "id": campaign.id,
            "article_number": campaign.article_number,
            "slides_payload": campaign.slides_payload.get("slides", []) if isinstance(campaign.slides_payload, dict) else campaign.slides_payload,
            "image_paths": [ensure_cdn_url(p) for p in (campaign.image_paths or [])],
            "caption": campaign.caption,
            "created_at": campaign.created_at.isoformat()
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

# ---------------------------------------------------------------------------
# PIB CAMPAIGN ENDPOINTS
# ---------------------------------------------------------------------------
@router.post("/generate/pib-latest")
def generate_latest_pib_draft(db: Session = Depends(get_db)):
    """
    Fetches the latest PIB smart note from R2, generates slides deterministically,
    renders them to R2 with media.politymentor.com URLs, and queues for approval.
    """
    try:
        campaign = generate_campaign_for_latest_pib(db)
        return {
            "status": "success",
            "message": f"Draft created for {campaign.article_number}: {campaign.title}",
            "campaign_id": campaign.id,
            "id": campaign.id,
            "title": campaign.title,
            "article_number": campaign.article_number,
            "slides_payload": campaign.slides_payload.get("slides", []),
            "image_paths": [ensure_cdn_url(p) for p in (campaign.image_paths or [])],
            "caption": campaign.caption,
            "status": campaign.status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PIB draft generation failed: {str(e)}")

# ---------------------------------------------------------------------------
# LIVING DOSSIER CAMPAIGN ENDPOINTS
# ---------------------------------------------------------------------------
@router.post("/generate/dossier")
def generate_dossier_draft(req: GenerateDossierRequest, db: Session = Depends(get_db)):
    """Generates an Instagram carousel draft using LLM synthesis directly from an issue dossier and its graph edges."""
    dossier = db.execute(
        text("SELECT * FROM issue_dossiers WHERE issue_slug = :slug LIMIT 1"),
        {"slug": req.issue_slug}
    ).mappings().first()

    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier slug not found.")

    edges = db.execute(
        text("SELECT * FROM issue_graph_edges WHERE issue_slug = :slug ORDER BY event_date ASC"),
        {"slug": req.issue_slug}
    ).mappings().all()

    payload = synthesize_dossier_with_groq(dict(dossier), [dict(e) for e in edges])
    slides = payload["slides"]

    campaign = SocialCampaignQueue(
        article_id=None,
        article_number=f"DOSSIER: {dossier['chapter_name']}",
        title=dossier["title"][:250],
        status="PENDING_APPROVAL",
        slides_payload=payload,
        image_paths=[],
        caption=(
            f"Evolving Constitutional Dossier: {dossier['title']}\n\n"
            f"Status: {dossier['status'].upper()} • {len(edges)} Event Nodes Tracked\n\n"
            f"Explore the live legal evolution and backward linkages on politymentor.com.\n\n"
            f"#UPSC #GS2 #PolityMentor #{dossier['chapter_name'].replace(' ', '')}"
        )
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    cdn_urls = render_dossier_campaign_slides(campaign.id, slides)
    campaign.image_paths = cdn_urls
    db.commit()
    db.refresh(campaign)

    return {
        "status": "success",
        "campaign_id": campaign.id,
        "title": campaign.title,
        "image_paths": cdn_urls,
        "slides_payload": payload
    }

# ---------------------------------------------------------------------------
# DISTRACTOR TRAP ENGINE ENDPOINTS
# ---------------------------------------------------------------------------
@router.post("/generate/trap/article")
def generate_trap_article_draft(req: GenerateTrapArticleRequest, db: Session = Depends(get_db)):
    """Synthesizes a 4-slide Distractor Trap carousel from a constitutional article."""
    try:
        payload = generate_analytical_trap_from_article(db, req.article, preferred_format=req.format)

        trap_row = PrelimsTrapMatrix(
            source_type="ARTICLE",
            source_ref_id=req.article,
            topic=payload["topic"],
            chapter_name="Indian Polity",
            question_format=payload["question_format"],
            question_stem=payload["question_stem"],
            statements_payload=payload["statements_payload"],
            options=payload["options"],
            correct_option=payload["correct_option"],
            trap_archetype=payload["trap_archetype"],
            conceptual_analysis=payload["conceptual_analysis"],
            elimination_heuristic=payload["elimination_heuristic"],
            source_citation=payload["source_citation"],
            status="PENDING"
        )
        db.add(trap_row)
        db.commit()
        db.refresh(trap_row)

        campaign = SocialCampaignQueue(
            article_id=None,
            article_number=f"TRAP: {req.article}",
            title=f"Prelims Trap: {payload['topic']}",
            status="PENDING_APPROVAL",
            slides_payload=payload,
            image_paths=[],
            caption=(
                f"Daily UPSC Prelims Distractor Trap: {payload['topic']}\n\n"
                f"Over 70% of candidates fall for this cognitive blindspot. Can you crack the constitutional ratio?\n\n"
                f"Swipe to uncover the trap and the authentic bare act rule.\n\n"
                f"#UPSC #Prelims #IndianPolity #PolityMentor #UPSC2026"
            )
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        trap_row.social_campaign_id = campaign.id
        cdn_urls = render_trap_campaign_slides(campaign.id, payload)
        campaign.image_paths = cdn_urls
        db.commit()

        return {
            "status": "success",
            "trap_id": trap_row.id,
            "campaign_id": campaign.id,
            "title": campaign.title,
            "image_paths": cdn_urls,
            "payload": payload
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trap generation failed: {str(e)}")

@router.post("/generate/trap/dossier")
def generate_trap_dossier_draft(req: GenerateTrapDossierRequest, db: Session = Depends(get_db)):
    """Synthesizes a 4-slide Distractor Trap carousel from an evolving dossier."""
    try:
        payload = generate_analytical_trap_from_dossier(db, req.issue_slug, preferred_format=req.format)

        trap_row = PrelimsTrapMatrix(
            source_type="DOSSIER",
            source_ref_id=req.issue_slug,
            topic=payload["topic"],
            chapter_name="Governance & Polity",
            question_format=payload["question_format"],
            question_stem=payload["question_stem"],
            statements_payload=payload["statements_payload"],
            options=payload["options"],
            correct_option=payload["correct_option"],
            trap_archetype=payload["trap_archetype"],
            conceptual_analysis=payload["conceptual_analysis"],
            elimination_heuristic=payload["elimination_heuristic"],
            source_citation=payload["source_citation"],
            status="PENDING"
        )
        db.add(trap_row)
        db.commit()
        db.refresh(trap_row)

        campaign = SocialCampaignQueue(
            article_id=None,
            article_number=f"TRAP: {req.issue_slug[:20]}",
            title=f"Dispute Trap: {payload['topic']}",
            status="PENDING_APPROVAL",
            slides_payload=payload,
            image_paths=[],
            caption=(
                f"Evolving Dispute Distractor Trap: {payload['topic']}\n\n"
                f"Analyzing the constitutional friction in recent litigation.\n\n"
                f"Swipe for the breakdown and heuristic elimination rule.\n\n"
                f"#UPSC #PolityMentor #GS2 #ConstitutionalLaw"
            )
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        trap_row.social_campaign_id = campaign.id
        cdn_urls = render_trap_campaign_slides(campaign.id, payload)
        campaign.image_paths = cdn_urls
        db.commit()

        return {
            "status": "success",
            "trap_id": trap_row.id,
            "campaign_id": campaign.id,
            "title": campaign.title,
            "image_paths": cdn_urls,
            "payload": payload
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trap generation failed: {str(e)}")

@router.post("/generate/trap/pyq")
def generate_trap_pyq_draft(req: GenerateTrapPyqRequest, db: Session = Depends(get_db)):
    """Synthesizes a 4-slide Distractor Trap carousel by mutating an authentic UPSC Prelims PYQ."""
    try:
        payload = generate_analytical_trap_from_pyq(db, req.pyq_id, preferred_format=req.format)

        trap_row = PrelimsTrapMatrix(
            source_type="PYQ_MUTATION",
            source_ref_id=str(req.pyq_id),
            topic=payload["topic"],
            chapter_name="PYQ Deconstruction",
            question_format=payload["question_format"],
            question_stem=payload["question_stem"],
            statements_payload=payload["statements_payload"],
            options=payload["options"],
            correct_option=payload["correct_option"],
            trap_archetype=payload["trap_archetype"],
            conceptual_analysis=payload["conceptual_analysis"],
            elimination_heuristic=payload["elimination_heuristic"],
            source_citation=payload["source_citation"],
            status="PENDING"
        )
        db.add(trap_row)
        db.commit()
        db.refresh(trap_row)

        campaign = SocialCampaignQueue(
            article_id=None,
            article_number=f"TRAP: PYQ-{req.pyq_id}",
            title=f"PYQ Variant: {payload['topic']}",
            status="PENDING_APPROVAL",
            slides_payload=payload,
            image_paths=[],
            caption=(
                f"UPSC Prelims PYQ Trap Variant: {payload['topic']}\n\n"
                f"How UPSC inverts standard PYQs to test analytical understanding.\n\n"
                f"Swipe for the distractor forensic analysis.\n\n"
                f"#UPSC #PrelimsPYQ #PolityMentor #UPSCStrategy"
            )
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        trap_row.social_campaign_id = campaign.id
        cdn_urls = render_trap_campaign_slides(campaign.id, payload)
        campaign.image_paths = cdn_urls
        db.commit()

        return {
            "status": "success",
            "trap_id": trap_row.id,
            "campaign_id": campaign.id,
            "title": campaign.title,
            "image_paths": cdn_urls,
            "payload": payload
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Trap generation failed: {str(e)}")

# ---------------------------------------------------------------------------
# QUEUE MANAGEMENT & EDITING
# ---------------------------------------------------------------------------
@router.get("/queue")
def list_queue(
    status: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Lists draft campaigns waiting for review, with permanent CDN image URLs."""
    target_status = status or status_filter
    query = db.query(SocialCampaignQueue)
    if target_status and target_status.upper() != "ALL":
        query = query.filter(SocialCampaignQueue.status == target_status.upper())

    items = query.order_by(SocialCampaignQueue.created_at.desc()).all()
    
    result = []
    for c in items:
        slides_list = c.slides_payload.get("slides", []) if isinstance(c.slides_payload, dict) else c.slides_payload
        cdn_images = [ensure_cdn_url(p) for p in (c.image_paths or [])]
        
        result.append({
            "id": c.id,
            "article_id": c.article_id,
            "article_number": c.article_number,
            "title": c.title,
            "status": c.status,
            "slides_payload": slides_list,
            "image_paths": cdn_images,
            "caption": c.caption,
            "created_at": c.created_at.isoformat() if c.created_at else datetime.utcnow().isoformat()
        })
    return result

@router.put("/queue/{campaign_id}/amend")
@router.put("/queue/{campaign_id}")
def amend_draft(campaign_id: int, req: AmendCampaignRequest, db: Session = Depends(get_db)):
    campaign = db.query(SocialCampaignQueue).filter(SocialCampaignQueue.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if isinstance(req.slides_payload, dict):
        slides = req.slides_payload.get("slides", req.slides_payload)
        payload_to_store = req.slides_payload
    elif isinstance(req.slides_payload, list):
        slides = req.slides_payload
        payload_to_store = {"slides": req.slides_payload}
    else:
        slides = []
        payload_to_store = {"slides": []}

    if not slides:
        raise HTTPException(status_code=400, detail="No slides provided in slides_payload.")

    campaign.slides_payload = payload_to_store
    if req.caption:
        campaign.caption = req.caption

    # Route dynamically based on campaign archetype
    if campaign.article_number and campaign.article_number.startswith("TRAP:"):
        new_paths = render_trap_campaign_slides(campaign.id, payload_to_store)
    elif campaign.article_number and campaign.article_number.startswith("DOSSIER:"):
        new_paths = render_dossier_campaign_slides(campaign.id, slides)
    elif campaign.article_number and campaign.article_number.startswith("PIB:"):
        new_paths = render_pib_campaign_slides(campaign.id, slides)
    else:
        new_paths = render_campaign_slides(campaign.article_number, slides, campaign.id)

    cdn_paths = [ensure_cdn_url(p) for p in new_paths]
    campaign.image_paths = cdn_paths
    db.commit()
    db.refresh(campaign)

    return {
        "status": "success",
        "message": "Content updated and slides re-rendered.",
        "image_paths": cdn_paths,
        "slides_payload": payload_to_store
    }

@router.post("/queue/{campaign_id}/approve")
def approve_draft(campaign_id: int, db: Session = Depends(get_db)):
    """Approves draft and publishes clean CDN URLs directly to Instagram Graph API."""
    campaign = db.query(SocialCampaignQueue).filter(SocialCampaignQueue.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    try:
        cdn_urls = [ensure_cdn_url(p) for p in (campaign.image_paths or [])]
        
        # Traps use 4 slides; Articles, PIB, and Dossiers use 6 slides
        min_required = 4 if campaign.article_number.startswith("TRAP:") else 6
        if not cdn_urls or len(cdn_urls) < min_required:
            raise HTTPException(status_code=400, detail=f"Campaign missing required {min_required} slide images.")

        media_id = InstagramPublisher.publish_carousel(
            image_urls=cdn_urls,
            caption=campaign.caption
        )

        campaign.status = "PUBLISHED"
        campaign.image_paths = cdn_urls
        campaign.approved_at = datetime.utcnow()
        db.commit()

        return {
            "status": "success",
            "message": f"Campaign #{campaign.id} ({campaign.article_number}) published to Instagram!",
            "media_id": media_id
        }
    except Exception as e:
        campaign.status = "FAILED"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Instagram publishing failed: {str(e)}")