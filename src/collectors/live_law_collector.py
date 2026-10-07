import hashlib
import json
import time
from datetime import datetime
from bs4 import BeautifulSoup
import requests
import trafilatura

from src.storage.dedup_client import DeduplicationManager
from src.storage.minio_client import NewspaperStorage

SITEMAP_URL = "https://www.livelaw.in/news-sitemap-daily.xml"
PUBLICATION = "livelaw"
CATEGORY = "judiciary"
PREFIX = "LL"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
}

NON_ARTICLE_PATHS = [
    "/pdf_upload/", "/job-updates/", "/vacancy/", 
    "/events/", "/law-firms-deals/", "/sponsored/", "/deals/"
]


def get_livelaw_sitemap() -> list[dict]:
    """Parse LiveLaw daily news sitemap skipping non-article attachments."""
    try:
        resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[!] Sitemap HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.content, "xml")
        if not soup.find_all("url"):
            soup = BeautifulSoup(resp.content, "html.parser")

        candidates = []
        for node in soup.find_all("url"):
            loc = node.find("loc")
            title_node = node.find(["news:title", "title"])
            date_node = node.find(["news:publication_date", "publication_date", "lastmod"])

            if loc and loc.get_text().strip():
                url = loc.get_text().strip()
                if any(p in url.lower() for p in NON_ARTICLE_PATHS):
                    continue

                candidates.append({
                    "url": url,
                    "title": title_node.get_text().strip() if title_node else "",
                    "published_at": date_node.get_text().strip() if date_node else "",
                })
        return candidates
    except Exception as e:
        print(f"[!] Error fetching sitemap {SITEMAP_URL}: {e}")
        return []


def extract_livelaw_body(html: str) -> tuple[str, str, str]:
    """Extract canonical editorial text directly from LiveLaw's JSON-LD schema."""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    body = ""
    pub_date = ""

    # Strategy 1: JSON-LD Schema (Extracts full 700+ words directly)
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string) if s.string else {}
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    if "articleBody" in item and len(item["articleBody"].strip()) > len(body):
                        body = item["articleBody"].strip()
                    if "headline" in item and not title:
                        title = item["headline"].strip()
                    if "datePublished" in item and not pub_date:
                        pub_date = item["datePublished"].strip()
        except Exception:
            continue

    # Clean text if JSON-LD contained escaped characters or repetitive notices
    if body:
        cleaned_paras = [
            p.strip() for p in body.splitlines() 
            if len(p.strip()) > 20 and not any(noise in p.lower() for noise in ["we use cookies", "ip subscription", "to read full story"])
        ]
        if cleaned_paras:
            body = "\n\n".join(cleaned_paras)

    # Strategy 2: Heuristic Fallback only if JSON-LD was absent
    if not body or len(body.split()) < 60:
        traf_body = trafilatura.extract(html, favor_recall=True) or ""
        if "ip subscription is detected" not in traf_body.lower():
            body = traf_body

    if not title:
        h1 = soup.find("h1")
        title = h1.get_text().strip() if h1 else ""

    if not pub_date:
        date_meta = (
            soup.find("meta", property="article:published_time")
            or soup.find("meta", attrs={"name": "publish-date"})
            or soup.find("meta", attrs={"name": "date"})
        )
        if date_meta and date_meta.get("content"):
            pub_date = date_meta["content"].strip()

    return title, body, pub_date


def run_livelaw_collector():
    storage = NewspaperStorage()
    dedup = DeduplicationManager()

    print("=" * 80)
    print("STARTING DEDICATED LIVELAW JUDICIARY INGESTION (JSON-LD ENGINE)")
    print(f"Bucket: {storage.bucket} | Deduplication: Active")
    print("=" * 80)

    candidates = get_livelaw_sitemap()
    print(f"\n[+] Discovered {len(candidates)} valid editorial candidate URLs.")

    new_saved_count = 0
    skipped_dup_count = 0
    skipped_short_count = 0

    for entry in candidates:
        raw_url = entry["url"]
        fallback_title = entry["title"] or "LiveLaw Article"
        sitemap_date = entry["published_at"]

        # 1. Deduplication via Redis
        is_dup, reason = dedup.is_duplicate(raw_url, fallback_title)
        if is_dup:
            skipped_dup_count += 1
            continue

        clean_url = dedup.canonicalize_url(raw_url)
        raw_hash = dedup.generate_id(clean_url)
        article_id = f"{PREFIX}_{raw_hash}"

        minio_key = f"newspaper/{PUBLICATION}/{CATEGORY}/{article_id}.json"

        # 2. MinIO Check
        if storage.object_exists(minio_key):
            dedup.mark_as_seen(clean_url, fallback_title)
            skipped_dup_count += 1
            continue

        # 3. HTTP Fetch
        print(f"    [↓] Downloading new: {fallback_title[:55]}...")
        try:
            resp = requests.get(clean_url, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                print(f"        [!] HTTP {resp.status_code}, skipping.")
                continue
            html = resp.text
        except Exception as e:
            print(f"        [!] Fetch error: {e}")
            continue

        parsed_title, full_text, parsed_date = extract_livelaw_body(html)
        final_title = parsed_title or fallback_title
        words = len(full_text.split()) if full_text else 0

        if words < 65:
            skipped_short_count += 1
            print(f"        [-] Skipped: Content too short ({words} words)")
            continue

        final_date = parsed_date or sitemap_date or datetime.utcnow().isoformat()

        # 4. Save to MinIO
        payload = {
            "article_id": article_id,
            "publication": PUBLICATION,
            "category": CATEGORY,
            "title": final_title,
            "url": clean_url,
            "published_at": final_date,
            "scraped_at": datetime.utcnow().isoformat(),
            "word_count": words,
            "full_article": full_text,
        }

        storage.put_json(minio_key, payload)
        dedup.mark_as_seen(clean_url, final_title)
        new_saved_count += 1
        print(f"        [✓] Saved -> {minio_key} ({words} words) [Saved: {new_saved_count}]")

        time.sleep(0.6)

    print("\n" + "=" * 80)
    print(f"[Done] Finished LiveLaw. Saved {new_saved_count} new, skipped {skipped_dup_count} duplicates, skipped {skipped_short_count} short items.")
    print("=" * 80)


if __name__ == "__main__":
    run_livelaw_collector()
