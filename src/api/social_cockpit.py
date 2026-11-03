from datetime import datetime
from typing import Optional, Union, List, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session
from src.services.instagram_publisher import InstagramPublisher
from src.database.session import SessionLocal
from src.database.models import SocialCampaignQueue
from src.services.social_service import (
    generate_campaign_for_article,
    render_campaign_slides
)
from src.services.pib_social_service import (
    generate_campaign_for_latest_pib,
    render_pib_campaign_slides
)

router = APIRouter(prefix="/api/admin/social", tags=["Social Cockpit"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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

class AmendCampaignRequest(BaseModel):
    slides_payload: Union[dict, List[Any]]
    caption: Optional[str] = None

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
            "image_paths": campaign.image_paths,
            "caption": campaign.caption,
            "created_at": campaign.created_at.isoformat()
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@router.get("/queue")
def list_queue(
    status: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Lists draft campaigns waiting for review in back office."""
    target_status = status or status_filter
    query = db.query(SocialCampaignQueue)
    if target_status and target_status.upper() != "ALL":
        query = query.filter(SocialCampaignQueue.status == target_status.upper())

    items = query.order_by(SocialCampaignQueue.created_at.desc()).all()
    
    result = []
    for c in items:
        slides_list = c.slides_payload.get("slides", []) if isinstance(c.slides_payload, dict) else c.slides_payload
        result.append({
            "id": c.id,
            "article_id": c.article_id,
            "article_number": c.article_number,
            "title": c.title,
            "status": c.status,
            "slides_payload": slides_list,
            "image_paths": c.image_paths,
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
        slides = req.slides_payload.get("slides", [])
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

    # Automatically choose renderer based on whether it is a PIB or Article campaign
    if campaign.article_number and campaign.article_number.startswith("PIB:"):
        new_paths = render_pib_campaign_slides(campaign.id, slides)
    else:
        new_paths = render_campaign_slides(campaign.article_number, slides, campaign.id)

    campaign.image_paths = new_paths
    db.commit()
    db.refresh(campaign)

    return {
        "status": "success",
        "message": "Content updated and slides re-rendered.",
        "image_paths": new_paths,
        "slides_payload": payload_to_store
    }

@router.post("/queue/{campaign_id}/approve")
def approve_draft(campaign_id: int, db: Session = Depends(get_db)):
    """Approves the draft and publishes the carousel directly to Instagram."""
    campaign = db.query(SocialCampaignQueue).filter(SocialCampaignQueue.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    try:
        media_id = InstagramPublisher.publish_carousel(
            image_urls=campaign.image_paths,
            caption=campaign.caption
        )

        campaign.status = "PUBLISHED"
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

@router.post("/generate/pib-latest")
def generate_latest_pib_draft(db: Session = Depends(get_db)):
    """
    Fetches the latest PIB smart note from R2, generates slides deterministically,
    renders them to R2, and queues the draft with status PENDING_APPROVAL.
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
            "image_paths": campaign.image_paths,
            "caption": campaign.caption,
            "status": campaign.status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PIB draft generation failed: {str(e)}")