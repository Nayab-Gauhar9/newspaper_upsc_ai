from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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
    article: str  # e.g., "200", "356", "72"

class AmendCampaignRequest(BaseModel):
    slides_payload: dict
    caption: Optional[str] = None

@router.post("/generate")
def generate_draft(req: GenerateArticleRequest, db: Session = Depends(get_db)):
    """Triggers generation for a specific article into PENDING_APPROVAL status."""
    try:
        campaign = generate_campaign_for_article(db, req.article)
        return {
            "status": "success",
            "message": f"Draft created for {campaign.article_number}",
            "campaign_id": campaign.id,
            "preview_images": campaign.image_paths
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@router.get("/queue")
def list_queue(status_filter: str = Query("PENDING_APPROVAL"), db: Session = Depends(get_db)):
    """Lists draft campaigns waiting for review in back office."""
    items = (
        db.query(SocialCampaignQueue)
        .filter(SocialCampaignQueue.status == status_filter)
        .order_by(SocialCampaignQueue.created_at.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "article_number": c.article_number,
            "title": c.title,
            "status": c.status,
            "slides_payload": c.slides_payload,
            "image_paths": c.image_paths,
            "caption": c.caption,
            "created_at": c.created_at.isoformat()
        }
        for c in items
    ]

@router.put("/queue/{campaign_id}/amend")
def amend_draft(campaign_id: int, req: AmendCampaignRequest, db: Session = Depends(get_db)):
    """Edits slide content from back office and immediately re-renders the PNG slides."""
    campaign = db.query(SocialCampaignQueue).filter(SocialCampaignQueue.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    campaign.slides_payload = req.slides_payload
    if req.caption:
        campaign.caption = req.caption

    # Re-render PNG images using the edited JSON payload
    slides = req.slides_payload.get("slides", [])
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