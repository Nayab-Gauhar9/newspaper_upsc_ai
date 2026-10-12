import time
from datetime import datetime, timedelta, timezone, now
from email.utils import parsedate_to_datetime
import urllib.request
import feedparser
import trafilatura

from src.storage.minio_client import NewspaperStorage
from src.storage.dedup_client import DeduplicationManager

TARGET_FEEDS = [
    {
        "publication": "the_hindu",
        "category": "national",
        "cat_code": "NAT",
        "feed_url": "https://www.thehindu.com/news/national/feeder/default.rss",
    },
    {
        "publication": "the_hindu",
        "category": "editorial",
        "cat_code": "ED",
        "feed_url": "https://www.thehindu.com/opinion/editorial/feeder/default.rss",
    },
    {
        "publication": "the_hindu",
        "category": "lead",
        "cat_code": "LEAD",
        "feed_url": "https://www.thehindu.com/opinion/lead/feeder/default.rss",
    },
    {
        "publication": "the_hindu",
        "category": "op_ed",
        "cat_code": "OPED",
        "feed_url": "https://www.thehindu.com/opinion/op-ed/feeder/default.rss",
    },
    {
        "publication": "indian_express",
        "category": "explained",
        "cat_code": "EXP",
        "feed_url": "https://indianexpress.com/section/explained/feed/",
    },
    {
        "publication": "indian_express",
        "category": "opinion",
        "cat_code": "OPN",
        "feed_url": "https://indianexpress.com/section/opinion/feed/",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

IST = timezone(timedelta(hours=5, minutes=30))
def parse_feed_date(entry) -> tuple[str, str]:
    """Returns (iso_date: 'YYYY-MM-DD', compact_date: 'YYYYMMDD')."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = datetime(*entry.published_parsed[:6])
            return dt.strftime("%Y-%m-%d"), dt.strftime("%Y%m%d")
        except Exception:
            pass

    raw_pub = getattr(entry, "published", "") or getattr(entry, "updated", "")
    if raw_pub:
        try:
            dt = parsedate_to_datetime(raw_pub)
            return dt.strftime("%Y-%m-%d"), dt.strftime("%Y%m%d")
        except Exception:
            pass
        if len(raw_pub) >= 10 and raw_pub[4] == "-" and raw_pub[7] == "-":
            d_str = raw_pub[:10]
            return d_str, d_str.replace("-", "")

    now_ist = datetime.now(IST)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y%m%d")


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        return trafilatura.fetch_url(url)


def run_daily_collector():
    storage = NewspaperStorage()
    dedup = DeduplicationManager(namespace="daily_press")

    print("=" * 75)
    print("STARTING DATE-PARTITIONED EXTRACTION TO MINIO")
    print(f"Target Base: daily_press/ | Bucket: {storage.bucket}")
    print("=" * 75)

    prefix_map = {"the_hindu": "TH", "indian_express": "IE"}

    for item in TARGET_FEEDS:
        pub = item["publication"]
        cat = item["category"]
        cat_code = item["cat_code"]
        url = item["feed_url"]
        pub_prefix = prefix_map.get(pub, "NP")

        print(f"\n[+] Polling {pub.upper()} -> {cat.upper()} ({cat_code})...")
        try:
            parsed = feedparser.parse(url, agent=HEADERS["User-Agent"])
            entries = parsed.entries
            print(f"    Discovered {len(entries)} candidate articles.")

            saved_count = 0
            skipped_count = 0

            for entry in entries:
                raw_url = getattr(entry, "link", "").strip()
                title = getattr(entry, "title", "No Title").strip()
                published = getattr(entry, "published", "")

                if not raw_url:
                    continue

                if dedup.is_duplicate(raw_url, title)[0]:
                    skipped_count += 1
                    continue

                iso_date, compact_date = parse_feed_date(entry)
                clean_url = dedup.canonicalize_url(raw_url)
                raw_hash = dedup.generate_id(clean_url)[:12]

                article_id = f"{pub_prefix}_{compact_date}_{cat_code}_{raw_hash}"
                raw_minio_key = f"daily_press/{pub}/{iso_date}/{cat}/raw/{article_id}.json"

                if storage.object_exists(raw_minio_key):
                    dedup.mark_as_seen(clean_url, title)
                    skipped_count += 1
                    continue

                raw_html = fetch_html(clean_url)
                if not raw_html:
                    continue

                full_text = trafilatura.extract(
                    raw_html,
                    include_comments=False,
                    include_tables=False,
                    favor_recall=True,
                )

                if not full_text or len(full_text.split()) < 75:
                    continue

                payload = {
                    "article_id": article_id,
                    "publication": pub,
                    "category": cat,
                    "cat_code": cat_code,
                    "article_date": iso_date,
                    "title": title,
                    "url": clean_url,
                    "published_at": published,
                    "scraped_at": datetime.now(IST).isoformat(),
                    "word_count": len(full_text.split()),
                    "full_article": full_text,
                }

                storage.put_json(raw_minio_key, payload)
                dedup.mark_as_seen(clean_url, title)
                saved_count += 1
                print(f"        [✓] Saved -> {raw_minio_key} ({payload['word_count']}w)")
                time.sleep(1.0)

            print(f"    [Done] Saved {saved_count} new, skipped {skipped_count} duplicates.")

        except Exception as e:
            print(f"    [!] Error polling {url}: {e}")


if __name__ == "__main__":
    run_daily_collector()
