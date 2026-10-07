import os
import re
import json
import urllib.request
import urllib.error

OUTPUT_DIR = "data"
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "full_constitution_corpus.json")

# Verified open-source raw GitHub JSON mirrors for the Constitution of India
DATA_MIRRORS = [
    "https://raw.githubusercontent.com/gokultp/indian-constitution/master/constitution.json",
    "https://raw.githubusercontent.com/nemo-0/Constitution-of-India/master/constitution.json",
    "https://raw.githubusercontent.com/CivicDataLab/indian-constitution-data/main/data/constitution_of_india.json",
]

DOCTRINE_MAPPING = {
    "Part I": "union-and-territory",
    "Part II": "citizenship",
    "Part III": "fundamental-rights",
    "Part IV": "dpsp",
    "Part IVA": "fundamental-duties",
    "Part V": "union-executive-parliament-judiciary",
    "Part VI": "state-executive-legislature-judiciary",
    "Part VIII": "union-territories",
    "Part IX": "panchayats",
    "Part IXA": "municipalities",
    "Part IXB": "cooperatives",
    "Part X": "scheduled-tribal-areas",
    "Part XI": "centre-state-relations",
    "Part XII": "finance-property-contracts",
    "Part XIII": "trade-commerce",
    "Part XIV": "civil-services-upsc",
    "Part XIVA": "tribunals",
    "Part XV": "elections",
    "Part XVI": "special-provisions-classes",
    "Part XVII": "official-language",
    "Part XVIII": "emergency-powers",
    "Part XIX": "miscellaneous",
    "Part XX": "amendment-constitution",
    "Part XXI": "temporary-transitional-special",
    "Part XXII": "short-title-commencements",
}

def clean_slug(article_num: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(article_num).strip().lower())
    return slug.strip("-")

def fetch_from_mirrors() -> list:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    for url in DATA_MIRRORS:
        try:
            print(f"[*] Attempting download from: {url}")
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(f"[✓] Successfully downloaded corpus from mirror.")
                return data
        except urllib.error.HTTPError as e:
            print(f"  [!] Mirror returned {e.code}. Trying next mirror...")
        except Exception as e:
            print(f"  [!] Download failed: {e}. Trying next mirror...")
    raise RuntimeError("All mirrors failed. Please check internet connection or provide local file.")

def extract_and_prepare_catalog():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    raw_items = fetch_from_mirrors()

    catalog = []
    
    # Normalize structures across different mirror schemas
    for item in raw_items:
        # Check standard possible field names
        art_num = item.get("article_number") or item.get("Article") or item.get("number") or item.get("art_no")
        if not art_num:
            continue

        art_num_str = str(art_num).strip()
        if not art_num_str.lower().startswith("article"):
            art_num_str = f"Article {art_num_str}"

        part = str(item.get("part") or item.get("Part") or "Part I").strip()
        title = str(item.get("title") or item.get("Title") or "").strip()
        
        # Capture the entire unabridged text
        full_text = str(
            item.get("text") 
            or item.get("content") 
            or item.get("verbatim_text") 
            or item.get("description") 
            or ""
        ).strip()

        if not full_text:
            continue

        slug = clean_slug(art_num_str)

        catalog.append({
            "article_number": art_num_str,
            "article_slug": slug,
            "title": title,
            "part_number": part,
            "doctrine_cluster_id": DOCTRINE_MAPPING.get(part, "general"),
            "verbatim_text": full_text
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    print(f"[✓] Saved {len(catalog)} unabridged articles to {OUTPUT_PATH}")

if __name__ == "__main__":
    extract_and_prepare_catalog()
