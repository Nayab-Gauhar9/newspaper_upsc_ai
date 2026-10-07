import json
import time
from datetime import datetime
from bs4 import BeautifulSoup
import requests
import trafilatura

from src.storage.dedup_client import DeduplicationManager
from src.storage.minio_client import NewspaperStorage

SITEMAP_URL = "https://www.barandbench.com/news_sitemap.xml"
PUBLICATION = "bar_and_bench"
CATEGORY = "judiciary"
PREFIX = "BB"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_bar_and_bench_sitemap() -> list[dict]:
    """Parse news sitemap cleanly without namespace errors."""
    try:
        resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[!] Sitemap returned HTTP {resp.status_code}")
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
                candidates.append({
                    "url": loc.get_text().strip(),
                    "title": title_node.get_text().strip() if title_node else "",
                    "published_at": date_node.get_text().strip() if date_node else "",
                })
        return candidates
    except Exception as e:
        print(f"[!] Error reading sitemap: {e}")
        return []


def extract_bar_and_bench_body(html: str) -> tuple[str, str, str]:
    """Extract canonical body directly from Quintype JSON-LD schema with fallback."""
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    body = ""
    pub_date = ""

    # Strategy 1: Quintype JSON-LD Schema (Cleanest source of truth)
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string) if s.string else {}
            # Flatten if schema is a list
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

    # Strategy 2: Trafilatura Fallback if JSON-LD lacked articleBody
    if not body or len(body.split()) < 40:
        body = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_recall=True,
        ) or ""

    # Strategy 3: HTML DOM Title/Date Fallback
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


def run_bar_and_bench_collector():
    storage = NewspaperStorage()
    dedup = DeduplicationManager()

    print("=" * 80)
    print("STARTING BAR & BENCH JUDICIARY INGESTION (JSON-LD ENGINE)")
    print(f"Bucket: {storage.bucket} | Deduplication: Active")
    print("=" * 80)

    candidates = get_bar_and_bench_sitemap()
    print(f"\n[+] Discovered {len(candidates)} candidate articles in sitemap.")

    new_saved_count = 0
    skipped_dup_count = 0
    skipped_short_count = 0

    for entry in candidates:
        raw_url = entry["url"]
        fallback_title = entry["title"] or "Bar and Bench Article"
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

        # 3. Fetch & Extract
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

        parsed_title, full_text, parsed_date = extract_bar_and_bench_body(html)
        final_title = parsed_title or fallback_title
        words = len(full_text.split()) if full_text else 0

        # Filter out 1-sentence gazette / notification briefs (< 60 words)
        if words < 60:
            skipped_short_count += 1
            print(f"        [-] Skipped: Notification brief ({words} words)")
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

        time.sleep(0.5)

    print("\n" + "=" * 80)
    print(f"[Done] Finished. Saved {new_saved_count} new, skipped {skipped_dup_count} duplicates, skipped {skipped_short_count} short notification briefs.")
    print("=" * 80)


if __name__ == "__main__":
    run_bar_and_bench_collector()
