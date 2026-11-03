import os
import time
import requests
import logging
from typing import List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v20.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

class InstagramPublisher:
    @classmethod
    def get_credentials(cls):
        account_id = os.getenv("INSTAGRAM_ACCOUNT_ID", "").strip()
        token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        return account_id, token

    @classmethod
    def _create_item_container(cls, image_url: str) -> str:
        """Creates a single child item container for a carousel item."""
        account_id, token = cls.get_credentials()
        endpoint = f"{BASE_URL}/{account_id}/media"
        params = {
            "image_url": image_url,
            "is_carousel_item": "true",
            "access_token": token
        }
        res = requests.post(endpoint, params=params, timeout=30)
        if res.status_code != 200:
            logger.error(f"Failed to create child container: {res.text}")
            res.raise_for_status()
        return res.json()["id"]

    @classmethod
    def _create_carousel_container(cls, children_ids: List[str], caption: str) -> str:
        """Bundles child item containers into a parent carousel container."""
        account_id, token = cls.get_credentials()
        endpoint = f"{BASE_URL}/{account_id}/media"
        params = {
            "media_type": "CAROUSEL",
            "children": ",".join(children_ids),
            "caption": caption,
            "access_token": token
        }
        res = requests.post(endpoint, params=params, timeout=30)
        if res.status_code != 200:
            logger.error(f"Failed to create parent container: {res.text}")
            res.raise_for_status()
        return res.json()["id"]

    @classmethod
    def _poll_container_status(cls, container_id: str, max_retries: int = 12, delay: int = 3):
        """Polls until Meta finishes downloading and processing the container."""
        _, token = cls.get_credentials()
        endpoint = f"{BASE_URL}/{container_id}"
        
        for attempt in range(1, max_retries + 1):
            res = requests.get(
                endpoint,
                params={"fields": "status_code", "access_token": token},
                timeout=15
            )
            if res.status_code == 200:
                status = res.json().get("status_code")
                logger.info(f"Container {container_id} status (attempt {attempt}/{max_retries}): {status}")
                if status == "FINISHED":
                    return True
                if status == "ERROR":
                    raise RuntimeError(f"Meta container processing failed: {res.text}")
            time.sleep(delay)
        return True

    @classmethod
    def _publish_container(cls, creation_id: str) -> str:
        """Publishes the finalized carousel to the Instagram feed."""
        account_id, token = cls.get_credentials()
        endpoint = f"{BASE_URL}/{account_id}/media_publish"
        params = {
            "creation_id": creation_id,
            "access_token": token
        }
        res = requests.post(endpoint, params=params, timeout=30)
        if res.status_code != 200:
            logger.error(f"Publish request failed: {res.text}")
            res.raise_for_status()
        return res.json()["id"]

    @classmethod
    def publish_carousel(cls, image_urls: List[str], caption: str) -> str:
        """
        Takes presigned HTTPS URLs for the slides and publishes them as an Instagram carousel.
        """
        account_id, token = cls.get_credentials()
        if not account_id or not token:
            raise ValueError(f"Missing credentials: INSTAGRAM_ACCOUNT_ID='{account_id}', token_len={len(token)}")

        if not image_urls or len(image_urls) < 2:
            raise ValueError("An Instagram carousel requires at least 2 slide URLs.")

        logger.info(f"Publishing {len(image_urls)} slides directly to Instagram Account {account_id}...")

        # 1. Create individual child containers
        children_ids = []
        for idx, url in enumerate(image_urls, 1):
            logger.info(f"Creating child container {idx}/{len(image_urls)}...")
            child_id = cls._create_item_container(url)
            children_ids.append(child_id)

        # 2. Wait briefly to allow child item processing
        time.sleep(2)

        # 3. Create parent carousel container
        logger.info("Bundling slides into parent carousel container...")
        parent_id = cls._create_carousel_container(children_ids, caption)

        # 4. Poll until the parent container status is FINISHED
        cls._poll_container_status(parent_id)

        # 5. Execute final publish call
        logger.info("Publishing carousel to feed...")
        media_id = cls._publish_container(parent_id)
        logger.info(f"Carousel published successfully! Meta Media ID: {media_id}")
        return media_id