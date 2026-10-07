import time
from datetime import datetime
import urllib.request
import feedparser
import trafilatura

from src.storage.minio_client import NewspaperStorage
from src.storage.dedup_client import DeduplicationManager

TARGET_FEEDS = [
    {
        "publication": "the_hindu",
        "category": "editorial",
        "feed_url": "https://www.thehindu.com/opinion/editorial/feeder/default.rss",
    },
    {
        "publication": "the_hindu",
        "category": "lead",
        "feed_url": "https://www.thehindu.com/opinion/lead/feeder/default.rss",
    },
    {
        "publication": "the_hindu",
        "category": "op_ed",
        "feed_url": "https://www.thehindu.com/opinion/op-ed/feeder/default.rss",
    },
    {
        "publication": "the_hindu",
        "category": "national",
        "feed_url": "https://www.thehindu.com/news/national/feeder/default.rss",
    },
    {
        "publication": "indian_express",
        "category": "explained",
        "feed_url": "https://indianexpress.com/section/explained/feed/",
    },
    {
        "publication": "indian_express",
        "category": "opinion",
        "feed_url": "https://indianexpress.com/section/opinion/feed/",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch_html_with_headers(url: str) -> str:
    """Fetch raw HTML using standard browser headers to bypass paywall bot-blocks."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        # Fallback to trafilatura default fetch if direct request fails
        return trafilatura.fetch_url(url)

def run_collector():
    storage = NewspaperStorage()
    dedup = DeduplicationManager()

    print("=" * 75)
    print("STARTING FULL UNRESTRICTED DEDUPLICATED INGESTION TO MINIO")
    print(f"Bucket: {storage.bucket} | Redis: Port 6380")
    print("=" * 75)

    for item in TARGET_FEEDS:
        pub = item["publication"]
        cat = item["category"]
        url = item["feed_url"]

        print(f"\n[+] Polling {pub.upper()} - {cat.upper()}...")
        try:
            parsed = feedparser.parse(url, agent=HEADERS["User-Agent"])
            entries = parsed.entries
            print(f"    Discovered {len(entries)} candidate feed items.")

            new_saved_count = 0
            skipped_dup_count = 0

            for entry in entries:
                raw_url = getattr(entry, "link", "").strip()
                title = getattr(entry, "title", "No Title").strip()
                published = getattr(entry, "published", "")

                if not raw_url:
                    continue

                # 1. Instant Redis duplicate check
                is_dup, reason = dedup.is_duplicate(raw_url, title)
                if is_dup:
                    skipped_dup_count += 1
                    continue

                prefix_map = {"the_hindu": "TH", "indian_express": "IE"}
                source_prefix = prefix_map.get(pub, "NP")

                clean_url = dedup.canonicalize_url(raw_url)
                raw_hash = dedup.generate_id(clean_url)
                article_id = f"{source_prefix}_{raw_hash}"

                minio_key = f"newspaper/{pub}/{cat}/{article_id}.json"

                # 2. Check MinIO fallback
                if storage.object_exists(minio_key):
                    dedup.mark_as_seen(clean_url, title)
                    skipped_dup_count += 1
                    continue

# 3. Download and parse body with browser headers
                print(f"    [↓] Downloading new: {title[:50]}...")
                raw_html = fetch_html_with_headers(clean_url)
                if not raw_html:
                    print("        [!] Could not fetch HTML, skipping.")
                    continue

                # Use favor_recall=True and include fallback to avoid dropping paywall containers
                full_text = trafilatura.extract(
                    raw_html,
                    include_comments=False,
                    include_tables=False,
                    no_fallback=False,
                    favor_recall=True,
                )

                # Lower threshold to 75 words to keep short op-eds and historical columns
                if not full_text or len(full_text.split()) < 75:
                    print(f"        [!] Body too short or blocked ({len(full_text.split()) if full_text else 0} words), skipping.")
                    continue

                # 4. Save to MinIO
                article_payload = {
                    "article_id": article_id,
                    "publication": pub,
                    "category": cat,
                    "title": title,
                    "url": clean_url,
                    "published_at": published,
                    "scraped_at": datetime.utcnow().isoformat(),
                    "word_count": len(full_text.split()),
                    "full_article": full_text,
                }

                storage.put_json(minio_key, article_payload)
                dedup.mark_as_seen(clean_url, title)
                new_saved_count += 1
                print(f"        [✓] Saved -> {minio_key} ({article_payload['word_count']} words) [Saved: {new_saved_count}]")

                time.sleep(1.0)

            print(f"    [Done] Processed all {len(entries)} items. Saved {new_saved_count} new, skipped {skipped_dup_count} duplicates.")

        except Exception as e:
            print(f"    [!] Error polling feed {url}: {e}")

    print("\n" + "=" * 75)
    print("DEDUPLICATED INGESTION COMPLETE")
    print("=" * 75)

if __name__ == "__main__":
    run_collector()
