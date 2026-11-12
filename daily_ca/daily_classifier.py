import os
import sys
import time
import itertools
from typing import Optional
from dotenv import load_dotenv
from groq import Groq, RateLimitError
from pydantic import BaseModel, Field, model_validator

from src.storage.minio_client import NewspaperStorage
from src.classifiers.taxonomy import (
    LAXMIKANTH_8TH_EDITION,
    is_valid_chapter,
    get_chapter_title,
)

load_dotenv()

# Formatted Laxmikanth 8th Edition Chapter Taxonomy (1–92)
TAXONOMY_STRING = "\n".join(
    [f"{num}: {title}" for num, title in LAXMIKANTH_8TH_EDITION.items()]
)


class KeyRotator:
    """Manages round-robin rotation across multiple Groq API keys with rate-limit failover."""

    def __init__(self):
        keys = []
        env_keys = os.getenv("GROQ_API_KEYS", "")
        if env_keys:
            keys.extend([k.strip() for k in env_keys.split(",") if k.strip()])

        single_key = os.getenv("GROQ_API_KEY")
        if single_key and single_key.strip() not in keys:
            keys.append(single_key.strip())

        idx = 1
        while True:
            numbered_key = os.getenv(f"GROQ_API_KEY_{idx}")
            if numbered_key and numbered_key.strip() not in keys:
                keys.append(numbered_key.strip())
                idx += 1
            else:
                break

        if not keys:
            raise ValueError(
                "No GROQ API keys found in .env (set GROQ_API_KEYS or GROQ_API_KEY)"
            )

        self.keys = keys
        self._pool = itertools.cycle(keys)
        self.clients = {k: Groq(api_key=k) for k in keys}
        print(f"[✓] KeyRotator initialized with {len(self.keys)} active Groq keys.")

    def get_next_client(self) -> tuple[str, Groq]:
        key = next(self._pool)
        return key, self.clients[key]


class ClassificationResult(BaseModel):
    is_relevant: bool = Field(
        default=False,
        description="True ONLY if the article has substantive UPSC CSE GS-II (Indian Polity, Constitution, Governance, Social Justice, or International Relations) exam value.",
    )
    chapter_number: Optional[int] = Field(
        default=None,
        description="Exact Laxmikanth chapter number (1 to 92) if is_relevant is true, else null.",
    )
    topic: Optional[str] = Field(
        default=None,
        description="Broad constitutional/governance/IR topic under the chapter if relevant, else null.",
    )
    subtopic: Optional[str] = Field(
        default=None,
        description="Specific concise subtopic (e.g., Article number, Act, Doctrine, Body, or Bilateral mechanism) if relevant, else null.",
    )
    reason: str = Field(
        default="",
        description="Concise justification for GS-II relevance or rejection (strictly under 25 words).",
    )

    @model_validator(mode="after")
    def enforce_strict_gs2_consistency(self) -> "ClassificationResult":
        # Enforce strict consistency between is_relevant and chapter_number
        if not self.is_relevant:
            self.chapter_number = None
            self.topic = None
            self.subtopic = None
        else:
            if self.chapter_number is None or not is_valid_chapter(self.chapter_number):
                self.is_relevant = False
                self.chapter_number = None
                self.topic = None
                self.subtopic = None
        return self


SYSTEM_PROMPT = """You are a strict UPSC Civil Services Examination (CSE) General Studies Paper-II (GS-II) Gatekeeper and Constitutional Taxonomy Classifier.

Your ONLY job is to filter out non-GS-II noise and retain articles that genuinely test or illustrate UPSC GS-II domains:
1. Indian Constitution: Historical underpinnings, evolution, features, amendments, significant provisions, and Basic Structure.
2. Union & States / Federalism: Functions and responsibilities of Union and States, federal challenges, devolution of powers/finances up to local levels (Panchayats & Municipalities), and separation of powers.
3. Legislatures & Executives: Parliament and State Legislatures (structure, functioning, conduct of business, privileges, bills/acts), Union and State Executives, Ministries/Departments, and Pressure Groups.
4. Judiciary & Dispute Redressal: Supreme Court, High Courts, tribunals, judicial review, judicial activism, PILs, and landmark constitutional/statutory interpretations.
5. Constitutional, Statutory & Regulatory Bodies: Appointment, powers, functions, and accountability of ECI, CAG, UPSC, Finance Commission, NCSC, NCST, NCBC, NHRC, CVC, CIC, Lokpal, CBI, TRAI, SEBI, etc.
6. Governance, Transparency & Social Justice: Government policies/interventions for development, statutory/regulatory frameworks, e-governance, RTI, citizen charters, civil services reforms, and welfare mechanisms for vulnerable sections.
7. International Relations (Chapters 85–92): India and its neighborhood, bilateral/regional/global groupings and agreements involving India, and important international institutions/treaties.

STRICT EXCLUSION RULES (MUST SET "is_relevant": false):
- Pure GS-III Economy/Markets: Stock indices, corporate earnings, quarterly GDP/CPI/WPI data, RBI repo rate/liquidity updates, routine trade/export numbers, or infrastructure contracts without statutory/regulatory/federal governance focus.
- Pure GS-III Science, Tech & Environment: Space launches, astronomy, medical/disease discoveries, wildlife sightings, weather forecasts, or climate events without statutory/policy/treaty governance focus.
- Pure GS-I History, Art, Culture & Geography: Archaeological finds, festival coverage, historical tributes/anniversaries, or physical geography events.
- Routine Local News & Noise: Daily crime blotters, road accidents, local civic complaints, celebrity/entertainment news, sports matches/tournaments, weather alerts, or routine ministerial inaugurations with zero policy/constitutional substance.
- Borderline Rule: If an article mentions a politician, court, or ministry only incidentally in a crime, election campaign rally, or routine event without substantive constitutional, legislative, judicial, governance, or IR content, REJECT IT ("is_relevant": false).

OUTPUT FORMAT:
Return strictly valid JSON conforming to this exact schema:
{
  "is_relevant": true or false,
  "chapter_number": <int 1-92 if is_relevant is true, else null>,
  "topic": <string if is_relevant is true, else null>,
  "subtopic": <string if is_relevant is true, else null>,
  "reason": <concise string strictly under 25 words>
}"""

HUMAN_PROMPT_TEMPLATE = """Evaluate the following article strictly for UPSC CSE GS-II (Indian Polity, Constitution, Governance, Social Justice, or International Relations) relevance.

Instructions:
- Apply the strict GS-II inclusion and exclusion rules. Reject pure GS-I, pure GS-III, sports, entertainment, crime, and routine political rhetoric.
- When relevant, map the article to the single most accurate Laxmikanth chapter number (1 to 92) from the taxonomy below.
- When NOT relevant, set "is_relevant": false, and set "chapter_number", "topic", and "subtopic" to null.
- Keep "reason" sharp and under 25 words.
- Output ONLY the JSON object.

Laxmikanth Chapters (1–92):
{chapters}

Article Title:
{title}

Article Text:
{article_text}"""


def countdown_sleep(seconds: int = 5):
    for remaining in range(seconds, 0, -1):
        sys.stdout.write(f"\r    [⏳ Pace Cooldown] {remaining:2d}s...")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 80 + "\r")
    sys.stdout.flush()


class DailyPolityClassifier:
    def __init__(self):
        self.storage = NewspaperStorage()
        self.rotator = KeyRotator()
        self.model = "openai/gpt-oss-120b"

    def evaluate_polity_relevance(self, title: str, text: str) -> ClassificationResult:
        """Evaluates article text strictly for UPSC GS-II relevance using round-robin Groq API rotation."""
        prompt = HUMAN_PROMPT_TEMPLATE.format(
            chapters=TAXONOMY_STRING,
            title=title,
            article_text=text[:8000],
        )
        attempts = 0
        max_attempts = len(self.rotator.keys)

        while attempts < max_attempts:
            key, client = self.rotator.get_next_client()
            try:
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.05,
                )
                return ClassificationResult.model_validate_json(
                    completion.choices[0].message.content
                )
            except RateLimitError:
                attempts += 1
                print(f"    [!] Groq 429 rate limit on key ...{key[-6:]}. Rotating...")
                time.sleep(1.0)
            except Exception as e:
                attempts += 1
                print(f"    [!] Groq rotation on key ...{key[-6:]}: {e}")
                time.sleep(1.0)

        # Fallback pause if all keys hit rate limits
        print("    [!] All keys rate-limited. Pausing 15s...")
        time.sleep(15.0)
        _, client = self.rotator.get_next_client()
        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.05,
        )
        return ClassificationResult.model_validate_json(
            completion.choices[0].message.content
        )

    def run_classifier(
        self,
        target_date: Optional[str] = None,
        limit: Optional[int] = None,
        cooldown_seconds: int = 4,
    ):
        """
        Scans daily_press/ across all dates or a target date.
        - Idempotent: Skips if already in classified/ or unclassified/.
        - Non-destructive: Never removes files from raw/.
        """
        print("=" * 80)
        print("STARTING DAILY GS-II POLITY CLASSIFIER (IDEMPOTENT & NON-DESTRUCTIVE)")
        print(f"Bucket: {self.storage.bucket} | Model: {self.model}")
        print("=" * 80)

        # 1. Discover all raw objects across daily_press
        all_objects = self.storage.list_objects(prefix="daily_press/")
        raw_keys = [
            k for k in all_objects
            if "/raw/" in k and k.endswith(".json")
        ]

        # Filter by specific date if requested (e.g. "2026-09-17" or "2026-10-25")
        if target_date:
            raw_keys = [k for k in raw_keys if f"/{target_date}/" in k]

        # Sort chronologically so backlog processes in order
        raw_keys.sort()

        print(f"Discovered {len(raw_keys)} total raw files.")

        # 2. Idempotency Check: Filter out already processed items
        unprocessed_keys = []
        for raw_key in raw_keys:
            classified_key = raw_key.replace("/raw/", "/classified/")
            unclassified_key = raw_key.replace("/raw/", "/unclassified/")

            if not self.storage.object_exists(classified_key) and not self.storage.object_exists(unclassified_key):
                unprocessed_keys.append(raw_key)

        print(f"Remaining to classify: {len(unprocessed_keys)} articles.\n")

        processed = 0
        retained_polity = 0
        diverted_general = 0

        for raw_key in unprocessed_keys:
            if limit and processed >= limit:
                print(f"[LIMIT REACHED] Stopped after {limit} articles.")
                break

            payload = self.storage.get_json(raw_key)
            if not payload:
                continue

            title = payload.get("title", "")
            text = payload.get("full_article", "")
            pub = payload.get("publication", "")
            cat = payload.get("category", "")
            art_date = payload.get("published_date") or payload.get("article_date", "")

            if not text or len(text.split()) < 50:
                continue

            print(f"[{art_date}] Evaluating: {title[:55]}... ({pub}/{cat})")
            res = self.evaluate_polity_relevance(title, text)

            classified_key = raw_key.replace("/raw/", "/classified/")
            unclassified_key = raw_key.replace("/raw/", "/unclassified/")

            # 3. Non-Destructive Partitioning (Exact Existing Schema)
            if res.is_relevant and res.chapter_number and is_valid_chapter(res.chapter_number):
                chapter_name = get_chapter_title(res.chapter_number)
                classified_payload = {
                    **payload,
                    "classification": {
                        **res.model_dump(),
                        "chapter_name": chapter_name,
                    },
                }
                self.storage.put_json(classified_key, classified_payload)
                retained_polity += 1
                print(f"    [✓ GS-II STORED] -> {classified_key}")
                print(f"        Chapter {res.chapter_number}: {chapter_name} ({res.topic})")
            else:
                unclassified_payload = {
                    **payload,
                    "classification": res.model_dump(),
                }
                self.storage.put_json(unclassified_key, unclassified_payload)
                diverted_general += 1
                print(f"    [→ NON-GS2 ARCHIVE] -> {unclassified_key}")
                print(f"        Reason: {res.reason}")

            processed += 1
            if cooldown_seconds > 0:
                countdown_sleep(cooldown_seconds)

        print("\n" + "=" * 80)
        print("DAILY GS-II CLASSIFICATION COMPLETED")
        print(f"Total Processed       : {processed}")
        print(f"GS-II Polity Articles : {retained_polity}")
        print(f"Non-GS2 / Unclassified: {diverted_general}")
        print(f"Raw Files Preserved   : {len(raw_keys)} (100%)")
        print("=" * 80)


if __name__ == "__main__":
    classifier = DailyPolityClassifier()
    classifier.run_classifier(target_date="2026-11-12", limit=None, cooldown_seconds=3)