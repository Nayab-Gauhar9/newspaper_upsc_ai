import logging
from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

# Import existing, configured client directly
from src.storage.redis_cache import redis_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/r", tags=["Campaign Tracker"])

# Central map of short tags to final landing destinations with UTM tags
CAMPAIGN_DESTINATIONS = {
    # 1. Telegram promotions
    "tg-toppers": "https://politymentor.com/?utm_source=telegram&utm_medium=sponsored_channel&utm_campaign=toppers_notes_nov12",
    "tg-notes": "https://politymentor.com/?utm_source=telegram&utm_medium=sponsored_post&utm_campaign=gs2_notes",
    
    # 2. Instagram promotions
    "ig-art127": "https://politymentor.com/?utm_source=instagram&utm_medium=carousel&utm_campaign=art127_pib",
    "ig-bio": "https://politymentor.com/?utm_source=instagram&utm_medium=bio&utm_campaign=main_profile",
    
    # 3. YouTube promotions
    "yt-art3": "https://politymentor.com/?utm_source=youtube&utm_medium=video_desc&utm_campaign=art3_masterclass",
}

BOT_SIGNATURES = ("bot", "spider", "crawl", "preview", "telegrambot", "whatsapp", "meta-externalagent")


@router.get("/{tag}")
def redirect_and_track(tag: str, request: Request):
    destination = CAMPAIGN_DESTINATIONS.get(tag, "https://politymentor.com")

    # Non-blocking tracking: visitors always get redirected
    try:
        if redis_client:
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            user_agent = request.headers.get("user-agent", "").lower()
            is_bot = any(sig in user_agent for sig in BOT_SIGNATURES)

            pipe = redis_client.pipeline()
            if is_bot:
                pipe.incr(f"campaign:bot_clicks:{tag}")
            else:
                pipe.incr(f"campaign:clicks:{tag}")
                pipe.incr(f"campaign:daily:{today_str}:{tag}")
                pipe.set(f"campaign:last_click:{tag}", datetime.utcnow().isoformat())
            pipe.execute()
    except Exception as err:
        logger.warning(f"Campaign tracking error for [{tag}]: {err}")

    return RedirectResponse(url=destination, status_code=302)


@router.get("/stats/live")
def get_campaign_live_stats():
    """Inspect click counts anytime from browser or terminal."""
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    stats = {}

    if not redis_client:
        return {"status": "error", "message": "Redis client not initialized"}

    try:
        for tag in CAMPAIGN_DESTINATIONS.keys():
            total = redis_client.get(f"campaign:clicks:{tag}") or 0
            today = redis_client.get(f"campaign:daily:{today_str}:{tag}") or 0
            bots = redis_client.get(f"campaign:bot_clicks:{tag}") or 0
            last_click = redis_client.get(f"campaign:last_click:{tag}") or "None"

            stats[tag] = {
                "total_real_clicks": int(total),
                "today_real_clicks": int(today),
                "bot_scrapes": int(bots),
                "last_click_utc": last_click,
            }
        return {"status": "success", "analytics": stats}
    except Exception as err:
        return {"status": "error", "detail": str(err)}