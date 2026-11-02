from datetime import datetime
from typing import Optional, Union, List, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from src.database.session import SessionLocal
from src.database.models import SocialCampaignQueue
from src.services.social_service import generate_campaign_for_article, render_campaign_slides

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
        # Extract flat list of slides if wrapped in {"slides": [...]}
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

@router.put("/queue/{campaign_id}")
@router.put("/queue/{campaign_id}/amend")
def amend_draft(campaign_id: int, req: AmendCampaignRequest, db: Session = Depends(get_db)):
    """Edits slide content from back office and immediately re-renders the PNG slides."""
    campaign = db.query(SocialCampaignQueue).filter(SocialCampaignQueue.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    if isinstance(req.slides_payload, list):
        payload_dict = {"slides": req.slides_payload}
        slides = req.slides_payload
    else:
        payload_dict = req.slides_payload
        slides = req.slides_payload.get("slides", [])

    campaign.slides_payload = payload_dict
    if req.caption:
        campaign.caption = req.caption

    # Re-render PNG images using the edited JSON payload
    new_paths = render_campaign_slides(campaign.article_number, slides, campaign.id)
    campaign.image_paths = new_paths

    db.commit()
    db.refresh(campaign)

    return {
        "status": "success",
        "message": "Content updated and slides re-rendered.",
        "image_paths": new_paths
    }

@router.post("/queue/{campaign_id}/approve")
def approve_draft(campaign_id: int, db: Session = Depends(get_db)):
    """Approves the draft. It will not be posted anywhere until approved."""
    campaign = db.query(SocialCampaignQueue).filter(SocialCampaignQueue.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    campaign.status = "APPROVED"
    campaign.approved_at = datetime.utcnow()
    db.commit()

    return {
        "status": "success",
        "message": f"Campaign #{campaign.id} ({campaign.article_number}) approved for publishing."
    }
