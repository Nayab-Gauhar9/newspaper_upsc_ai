import os
import re
import json
import itertools
from threading import Lock
from typing import List
import pdfplumber
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from groq import Groq  # or from openai import OpenAI
from pydantic import BaseModel, Field, field_validator
from typing import List, Union
from sqlalchemy.dialects.postgresql import insert
from src.database.session import SessionLocal  # Your sessionmaker
from src.database.models import PrelimsPYQModel          # PrelimsPYQModel in models.py
from src.classifiers.taxonomy import LAXMIKANTH_8TH_EDITION, get_chapter_title

load_dotenv()

# --- 1. Thread-safe Round-Robin Key Manager ---
raw_keys = os.getenv("GROQ_API_KEYS", "")
api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

if not api_keys:
    # Fallback to single GROQ_API_KEY if present
    single_key = os.getenv("GROQ_API_KEY")
    if single_key:
        api_keys = [single_key.strip()]
    else:
        raise ValueError("No GROQ_API_KEYS found in .env file!")

key_pool = itertools.cycle(api_keys)
key_lock = Lock()

def get_next_groq_client() -> Groq:
    with key_lock:
        key = next(key_pool)
    return Groq(api_key=key)

class QuestionTaxonomyEnrichment(BaseModel):
    chapter_number: int = Field(
        ...,
        description="The exact Laxmikanth 8th Edition chapter number between 1 and 92."
    )
    mapped_articles: List[Union[int, str]] = Field(
        default_factory=list,
        description="List of constitutional article numbers tested (e.g. [244, '244A', 371])."
    )
    explanation: str = Field(
        ...,
        description="Exam-oriented 2-sentence rationale grounding the answer."
    )
    difficulty_level: str = Field(
        ...,
        description="Difficulty: 'Easy', 'Moderate', or 'Tough'."
    )
    is_conceptual: bool = Field(
        ...,
        description="True if testing theoretical doctrine rather than factual provisions."
    )

    @field_validator("mapped_articles", mode="before")
    @classmethod
    def clean_articles(cls, v):
        if not isinstance(v, list):
            return []
        cleaned = []
        for item in v:
            digits = re.sub(r"\D", "", str(item))
            if digits and int(digits) <= 395:
                cleaned.append(int(digits))
        return list(dict.fromkeys(cleaned))  # Deduplicate while preserving order


# --- 3. Groq LLM Classifier with Fallback & Retries ---
def enrich_with_groq(q_text: str, options: dict, year: int, retries: int = 3) -> dict:
    taxonomy_context = "\n".join([f"{num}: {title}" for num, title in LAXMIKANTH_8TH_EDITION.items()])
    
    prompt = f"""
You are a senior UPSC Prelims GS-II subject matter expert.
Analyze and classify this UPSC question from year {year}:

Question:
{q_text}

Options:
{json.dumps(options, indent=2)}

Laxmikanth 8th Edition Chapter Taxonomy:
{taxonomy_context}

Return ONLY valid JSON matching this schema:
{{
  "chapter_number": <int 1-92>,
  "mapped_articles": [<integers 1-395>],
  "explanation": "<2-sentence bare-act explanation>",
  "difficulty_level": "Easy" | "Moderate" | "Tough",
  "is_conceptual": true | false
}}
"""

    for attempt in range(retries):
        client = get_next_groq_client()
        try:
            chat_completion = client.chat.completions.create(
                model="openai/gpt-oss-120b",  # Or llama-3.1-70b-versatile / llama-3.1-8b-instant
                messages=[
                    {"role": "system", "content": "You are a precise JSON-only UPSC Polity classifier."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            raw_json = chat_completion.choices[0].message.content
            parsed = QuestionTaxonomyEnrichment.model_validate_json(raw_json)

            chapter_num = parsed.chapter_number if parsed.chapter_number in LAXMIKANTH_8TH_EDITION else 4
            
            return {
                "chapter_number": chapter_num,
                "chapter_name": get_chapter_title(chapter_num),
                "mapped_articles": [a for a in parsed.mapped_articles if 1 <= a <= 395],
                "explanation": parsed.explanation,

                "difficulty_level": parsed.difficulty_level,
                "is_conceptual": parsed.is_conceptual,
            }
        except Exception as e:
            print(f"[Retry {attempt+1}/{retries}] Groq error with rotated key: {e}")
            if attempt == retries - 1:
                # Safe fallback if all rotated keys encounter rate-limits or fails
                return {
                    "chapter_number": 4,
                    "chapter_name": get_chapter_title(4),
                    "mapped_articles": [],
                    "explanation": "Official UPSC Prelims PYQ.",
                    "difficulty_level": "Moderate",
                    "is_conceptual": False,
                }


# --- 4. Batch Ingestion Loop ---
PDF_FILE_PATH = "upsc-prelims-indian-polity.pdf"

def run_full_ingestion():
    print("Reading all pages from PDF...")
    full_text = ""
    with pdfplumber.open(PDF_FILE_PATH) as pdf:
        print(f"Total pages: {len(pdf.pages)}")
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                full_text += "\n" + t

    # 1. First, split into lines or blocks and identify Year changes
    # Year banners in the PDF appear as: "— 2026 —", "— 2025 —", etc. or "UPSC 2024"
    lines = full_text.split("\n")
    tagged_lines = []
    current_year = 2026

    for line in lines:
        # Check for year divider: "— 2024 —" or "- 2024 -"
        year_match = re.search(r"[-—]\s*(\d{4})\s*[-—]", line)
        if year_match:
            current_year = int(year_match.group(1))
        
        # Check for "UPSC 2024"
        upsc_match = re.search(r"UPSC\s+(\d{4})", line, re.IGNORECASE)
        if upsc_match:
            current_year = int(upsc_match.group(1))

        # Inject the active year tag into the line stream
        if line.strip().startswith("Q") and re.match(r"^Q\d+\.", line.strip()):
            tagged_lines.append(f"[[YEAR_{current_year}]]\n" + line)
        else:
            tagged_lines.append(line)

    unified_text = "\n".join(tagged_lines)

    # 2. Match questions with the injected active year tag
    pattern = re.compile(
        r"\[\[YEAR_(?P<year>\d{4})\]\]\s*"
        r"(?:Indian Polity\s*>\s*(?P<subtopic>[^\n]+)\n+)?"
        r"(?P<q_num>Q\d+)\.\s*(?P<q_text>[\s\S]+?)\n+"
        r"\(a\)\s*(?P<opt_a>[\s\S]+?)\n+"
        r"\(b\)\s*(?P<opt_b>[\s\S]+?)\n+"
        r"\(c\)\s*(?P<opt_c>[\s\S]+?)\n+"
        r"\(d\)\s*(?P<opt_d>[\s\S]+?)\n+"
        r"Answer:\s*\((?P<ans>[a-d])\)",
        re.IGNORECASE
    )

    matches = list(pattern.finditer(unified_text))
    print(f"Total parsed questions with accurate years: {len(matches)}")


    db = SessionLocal()
    inserted_count = 0
    skipped_count = 0

    try:
        for idx, match in enumerate(matches, start=1):
            data = match.groupdict()
            year = int(data["year"]) if data.get("year") else 2026
            q_num = int(data["q_num"].replace("Q", "").strip())

            # Check duplicate first before calling Groq to save API calls
            existing = db.query(PrelimsPYQModel).filter_by(
                year=year,
                question_number=q_num
            ).first()

            if existing:
                skipped_count += 1
                continue

            q_text = " ".join(data["q_text"].split())
            options = {
                "A": " ".join(data["opt_a"].split()),
                "B": " ".join(data["opt_b"].split()),
                "C": " ".join(data["opt_c"].split()),
                "D": " ".join(data["opt_d"].split()),
            }
            correct_option = data["ans"].strip().upper()

            print(f"[{idx}/{len(matches)}] Classifying Year {year} Q{q_num} via Groq...")
            enriched = enrich_with_groq(q_text, options, year)

            new_pyq = PrelimsPYQModel(
                year=year,
                question_number=q_num,
                question_text=q_text,
                options=options,
                correct_option=correct_option,
                chapter_number=enriched["chapter_number"],
                chapter_name=enriched["chapter_name"],
                mapped_articles=enriched["mapped_articles"],
                explanation=enriched["explanation"],
                difficulty_level=enriched["difficulty_level"],
                is_conceptual=enriched["is_conceptual"],
            )
            db.add(new_pyq)
            db.commit()  # Commit per question so progress is preserved if interrupted
            inserted_count += 1
            print(f" -> Saved: Ch {enriched['chapter_number']} ({enriched['chapter_name']}) | Arts: {enriched['mapped_articles']}")

        print(f"\n==========================================")
        print(f"Ingestion Finished! Inserted: {inserted_count}, Skipped (Already Present): {skipped_count}")
        print(f"==========================================")
    except Exception as e:
        db.rollback()
        print(f"Error during ingestion loop: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    run_full_ingestion()
