import hashlib
import time
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
import trafilatura

from src.storage.dedup_client import DeduplicationManager
from src.storage.minio_client import NewspaperStorage

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def discover_sco_articles(limit: int = 25) -> list[dict]:
    """Crawl constitutional analyses and journal deep-dives from Supreme Court Observer."""
    target_urls = [
        "https://www.scobserver.in/journal/",
        "https://www.scobserver.in/"
    ]
    candidates = []
    seen_urls = set()

    # Paths to discard
    EXCLUDE_PATTERNS = [
        "/tag/", "/category/", "/author/", "/about-us", "/team", 
        "/contact", "/donate", "/privacy", "/terms", "/page/"
    ]

    for index_url in target_urls:
        try:
            resp = SESSION.get(index_url, timeout=15)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href.startswith("http"):
                    href = urljoin("https://www.scobserver.in", href)

                clean_url = href.split("?")[0].rstrip("/")

                if "scobserver.in" not in clean_url:
                    continue

                if clean_url in [
                    "https://www.scobserver.in", 
                    "https://www.scobserver.in/journal"
                ]:
                    continue

                if any(pat in clean_url for pat in EXCLUDE_PATTERNS):
                    continue

                # SCO titles live either in the anchor text or an enclosed heading
                title = a.get_text().strip()
                heading = a.find(["h1", "h2", "h3", "h4"])
                if heading and len(heading.get_text().strip()) > len(title):
                    title = heading.get_text().strip()

                # If the anchor is inside a card/heading element
                if len(title) < 18:
                    parent_h = a.find_parent(["h1", "h2", "h3", "h4", "article"])
                    if parent_h:
                        title = parent_h.get_text().strip()

                if len(title) >= 18 and clean_url not in seen_urls:
                    seen_urls.add(clean_url)
                    candidates.append({"url": clean_url, "title": title})
                    if len(candidates) >= limit:
                        return candidates

        except Exception as e:
            print(f"[!] SCO discovery error on {index_url}: {e}")

    return candidates



def discover_prs_articles(limit: int = 25) -> list[dict]:
    """Crawl recent legislative and policy analyses from The PRS Blog."""
    index_url = "https://prsindia.org/theprsblog"
    candidates = []
    seen_urls = set()

    try:
        resp = SESSION.get(index_url, timeout=15)
        if resp.status_code != 200:
            print(f"[!] PRS returned HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Locate links inside post rows or headline containers
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()

            # Target substantive blog slugs; reject tags, taxonomy, and categories
            if "/theprsblog/" in href and not any(sub in href for sub in ["/category/", "/tags/", "/author/", "/page/"]):
                full_url = urljoin("https://prsindia.org", href).split("?")[0].rstrip("/")
                if full_url == index_url.rstrip("/") or full_url in seen_urls:
                    continue

                title = a.get_text().strip()
                # If the anchor wrapped an image or empty space, check parent headline
                if len(title) < 15:
                    parent_heading = a.find_parent(["h2", "h3", "h4"])
                    if parent_heading:
                        title = parent_heading.get_text().strip()

                if len(title) >= 15:
                    seen_urls.add(full_url)
                    candidates.append({"url": full_url, "title": title})
                    if len(candidates) >= limit:
                        break

    except Exception as e:
        print(f"[!] PRS discovery error: {e}")

    return candidates


def run_governance_collector():
    storage = NewspaperStorage()
    dedup = DeduplicationManager()

    sources = [
        {
            "publication": "scobserver",
            "category": "constitutional_cases",
            "fetcher": discover_sco_articles,
            "prefix": "SCO",
        },
        {
            "publication": "prsindia",
            "category": "legislative_briefs",
            "fetcher": discover_prs_articles,
            "prefix": "PRS",
        },
    ]

    print("=" * 80)
    print("STARTING FULL GOVERNANCE & POLICY INGESTION (PRS & SCO)")
    print(f"Target Bucket: {storage.bucket} | Deduplication: Active")
    print("=" * 80)

    for src in sources:
        pub = src["publication"]
        cat = src["category"]
        prefix = src["prefix"]

        print(f"\n[+] Discovering pieces for {pub.upper()}...")
        items = src["fetcher"]()
        print(f"    Discovered {len(items)} candidates on index page.")

        new_saved_count = 0
        skipped_dup_count = 0

        for item in items:
            raw_url = item["url"]
            fallback_title = item["title"]

            # 1. Redis duplicate check
            is_dup, reason = dedup.is_duplicate(raw_url, fallback_title)
            if is_dup:
                skipped_dup_count += 1
                continue

            clean_url = dedup.canonicalize_url(raw_url)
            raw_hash = dedup.generate_id(clean_url)
            article_id = f"{prefix}_{raw_hash}"

            minio_key = f"newspaper/{pub}/{cat}/{article_id}.json"

            # 2. MinIO check
            if storage.object_exists(minio_key):
                dedup.mark_as_seen(clean_url, fallback_title)
                skipped_dup_count += 1
                continue

            # 3. Download & Extract Content
            try:
                page_resp = SESSION.get(clean_url, timeout=15)
                if page_resp.status_code != 200:
                    continue
                html = page_resp.text
            except Exception:
                continue

            # Favor recall to capture policy tables, case timelines, and side notes
            body = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
                favor_recall=True,
            )

            # Heuristic cleanup fallback if trafilatura missed nested div layouts
            if not body or len(body.split()) < 75:
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                    tag.decompose()
                paras = [
                    p.get_text().strip()
                    for p in soup.find_all(["p", "blockquote"])
                    if len(p.get_text().strip()) > 30
                ]
                body = "\n\n".join(paras)

            word_count = len(body.split())
            if word_count < 75:
                continue

            # Extract accurate publication date and metadata
            meta = trafilatura.extract_metadata(html)
            final_title = meta.title if meta and meta.title else fallback_title
            pub_date = (
                meta.date
                if meta and meta.date
                else datetime.utcnow().isoformat()
            )

            # 4. Save structured JSON to MinIO
            payload = {
                "article_id": article_id,
                "publication": pub,
                "category": cat,
                "title": final_title,
                "url": clean_url,
                "published_at": pub_date,
                "scraped_at": datetime.utcnow().isoformat(),
                "word_count": word_count,
                "full_article": body,
            }

            storage.put_json(minio_key, payload)
            dedup.mark_as_seen(clean_url, final_title)
            new_saved_count += 1
            print(f"    [✓] Saved -> {minio_key} ({word_count} words) | {final_title[:45]}...")
            time.sleep(1.0)

        print(f"    [Done] {pub.upper()} complete. Saved {new_saved_count} new, skipped {skipped_dup_count} duplicates.")

    print("\n" + "=" * 80)
    print("GOVERNANCE & POLICY INGESTION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_governance_collector()
