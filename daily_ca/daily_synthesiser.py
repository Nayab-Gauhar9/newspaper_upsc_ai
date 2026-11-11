import os
import time
import json
import logging
from typing import Optional, List, Dict
from dotenv import load_dotenv

from pydantic import BaseModel, Field, field_validator
from groq import Groq, RateLimitError

from src.storage.minio_client import NewspaperStorage
from src.classifiers.editorial_classifier import KeyRotator, countdown_sleep

load_dotenv()
logger = logging.getLogger(__name__)

# ==============================================================================
# 1. 6-LAYER PHD / UPSC EXPERT SCHEMA (STRICTLY PRESERVED)
# ==============================================================================

class DialecticalDimension(BaseModel):
    dimension: str = Field(description="Name of constitutional dimension (e.g., 'Federal Autonomy', 'Separation of Powers', 'Substantive Due Process')")
    argument: str = Field(description="Scholarly argument using precise constitutional terminology.")
    substantiation: str = Field(description="Supreme Court precedents, constitutional articles, committee reports, or historical conventions.")

class PrelimsTrapStatement(BaseModel):
    statement: str = Field(description="Rigorous Prelims statement crafted with a classic UPSC conceptual trap.")
    is_correct: bool = Field(description="True or False.")
    trap_mechanism: str = Field(description="Classification of trap: 'Constitutional vs Statutory', 'Shall vs May', 'Absolute vs Qualified', 'Central Sector vs Centrally Sponsored', 'Union vs State List'")
    explanation: str = Field(description="Authoritative legal rationale citing constitutional text, doctrine, or statutory section.")

class BackwardLinkages(BaseModel):
    articles_and_schedules: List[str] = Field(default_factory=list, description="Articles and Schedules invoked directly or indirectly")
    landmark_judgments: List[str] = Field(default_factory=list, description="Relevant Supreme Court / High Court precedents")
    commissions_and_committees: List[str] = Field(default_factory=list, description="Sarkaria, Punchhi, Law Commission, 2nd ARC, NCRWC citations")
    constitutional_doctrines: List[str] = Field(default_factory=list, description="Relevant constitutional doctrines")

class MainsFramework(BaseModel):
    mains_probable_question: str = Field(description="A high-probability UPSC CSE Mains GS-II question (15 Marks, 250 Words).")
    introduction_hook: str = Field(description="Constitutional anchor, doctrine, or context to open the answer.")
    body_architecture: str = Field(description="Key structural headings and balance required in the body.")
    way_forward_and_reforms: str = Field(description="Concrete administrative, statutory, or judicial remedies.")

class PhDLevelPolityAnalysis(BaseModel):
    headline: str = Field(description="Academic, structural headline capturing the institutional friction.")
    chapter_name: str = Field(description="Exact Laxmikanth 8th Edition Chapter Title.")
    issue_framing: str = Field(description="Concise 80-word academic overview of the core constitutional dilemma and institutional stakes.")
    backward_linkages: BackwardLinkages = Field(description="Categorized mappings to static polity")
    thesis_affirmative: List[DialecticalDimension] = Field(description="2 institutional/state rationales justifying the measure.")
    antithesis_critique: List[DialecticalDimension] = Field(description="2 rigorous constitutional critiques highlighting vulnerabilities and institutional risks.")
    edge_case_and_unintended_consequences: str = Field(description="Second-order administrative implications, constitutional ambiguities, or subtle legal paradoxes.")
    prelims_edge_traps: List[PrelimsTrapStatement] = Field(description="3 high-yield Prelims statements highlighting exam traps.")
    mains_framework: MainsFramework = Field(description="Mains GS-II answer blueprint")
    aspirant_blindspot: str = Field(description="Direct comparison: What a standard aspirant writes (superficial) vs. What an expert writes to secure top marks.")


# ==============================================================================
# 2. HARDENED SYSTEM & USER PROMPTS
# ==============================================================================

SCHEMA_TEMPLATE_STR = """{
  "headline": "<High-level academic headline highlighting institutional or constitutional tension>",
  "chapter_name": "<Exact Laxmikanth chapter title>",
  "issue_framing": "<Strictly 70-90 words synthesizing the institutional dilemma, statutory conflict, or constitutional friction>",
  "backward_linkages": {
    "articles_and_schedules": ["Article ...", "Schedule ... (List I/II/III Entry ...)"],
    "landmark_judgments": ["Case Name v. Union of India (Year)"],
    "commissions_and_committees": ["Sarkaria Commission / Punchhi Commission / 2nd ARC / Law Commission Report No. ..."],
    "constitutional_doctrines": ["Doctrine of Pith and Substance / Basic Structure / Harmonious Construction / Colorable Legislation"]
  },
  "thesis_affirmative": [
    {
      "dimension": "<Exact constitutional or administrative dimension name>",
      "argument": "<Scholarly argument with formal jurisprudence terms>",
      "substantiation": "<Specific Article, precedent, or statutory provision>"
    },
    {
      "dimension": "<Second constitutional dimension name>",
      "argument": "<Scholarly argument with formal jurisprudence terms>",
      "substantiation": "<Specific Article, precedent, or statutory provision>"
    }
  ],
  "antithesis_critique": [
    {
      "dimension": "<Exact vulnerability dimension name>",
      "argument": "<Rigorous critique focusing on institutional decay or rights violation>",
      "substantiation": "<Precedent, DPSP conflict, or federal safeguard violated>"
    },
    {
      "dimension": "<Second vulnerability dimension name>",
      "argument": "<Rigorous critique focusing on institutional decay or rights violation>",
      "substantiation": "<Precedent, DPSP conflict, or federal safeguard violated>"
    }
  ],
  "edge_case_and_unintended_consequences": "<2 to 3 sentences detailing subtle institutional paradoxes, jurisdictional overlap, or unintended enforcement dilemmas>",
  "prelims_edge_traps": [
    {
      "statement": "<Deceptive statement testing subtle wordings: e.g. statutory vs constitutional, 100% central funding vs 60:40>",
      "is_correct": false,
      "trap_mechanism": "<Constitutional vs Statutory / Shall vs May / Absolute vs Qualified / Central Sector vs CSS / Legislative Competence>",
      "explanation": "<Precise legal rationale stating why it is false, citing the exact statutory section or constitutional provision>"
    },
    {
      "statement": "<Factually accurate, nuanced statement testing a non-obvious constitutional safeguard>",
      "is_correct": true,
      "trap_mechanism": "<Constitutional Safeguard / Procedural Prerequisite / Statutory Qualification>",
      "explanation": "<Affirmation citing the exact constitutional article or benchmark judgment>"
    },
    {
      "statement": "<Deceptive statement manufacturing an arbitrary numerical requirement or incorrect Union vs State ministry attribution>",
      "is_correct": false,
      "trap_mechanism": "<Ministry Attribution / Numerical Constraint / Mandatory vs Discretionary>",
      "explanation": "<Precise legal rationale stating why it is false>"
    }
  ],
  "mains_framework": {
    "mains_probable_question": "<High-probability 15 Marks, 250 Words question starting with 'Critically examine', 'Evaluate', or 'Discuss'>",
    "introduction_hook": "<1-2 sentences framing the answer with an Article, Supreme Court doctrine, or institutional context>",
    "body_architecture": "<Clear breakdown of sub-headings: Affirmative Justification, Constitutional Friction/Critique, Federal/Institutional Implications>",
    "way_forward_and_reforms": "<Concrete actionable reforms citing Law Commission, ARC, or landmark committee recommendations>"
  },
  "aspirant_blindspot": "Standard Aspirant writes: [descriptive narrative or current events summary]. Expert Examination Candidate writes: [dialectical analysis balancing Articles, Seventh Schedule entries, and ratio decidendi of landmark rulings]."
}"""

EXPERT_POLITY_SYSTEM_PROMPT = f"""You are a distinguished Constitutional Scholar, UPSC CSE GS-II Chief Examiner, and Senior Legal Arbiter.
Your objective is to deconstruct daily news developments into authoritative, PhD-level UPSC General Studies Paper II analytical frameworks.

CRITICAL INSTRUCTIONS & NEGATIVE CONSTRAINTS:
1. OUTPUT FORMAT: Output ONLY a single, valid, parsable JSON object. No preamble, no markdown fences, no conversational prose.
2. SCHEMA STRICTNESS: You must match the key names and nesting in the JSON template below exactly. Do NOT rename, delete, or introduce new top-level keys.
3. CONSTITUTIONAL GROUNDING: Always specify exact Article numbers, Seventh Schedule Entries (List I/II/III), landmark Supreme Court rulings, and administrative bodies. Avoid vague assertions like "the constitution states".
4. PRELIMS TRAPS: Statements must feature realistic UPSC exam traps (e.g., swapping Central Sector vs Centrally Sponsored, confusing Article 66 with 54, or misattributing State subjects like public health to the Union). Include explicit 'is_correct' booleans.
5. NO TRUNCATION: Complete all arrays with the requested counts (thesis_affirmative: 2, antithesis_critique: 2, prelims_edge_traps: 3).

JSON SCHEMA TEMPLATE:
{SCHEMA_TEMPLATE_STR}"""

ANALYSIS_USER_PROMPT_TEMPLATE = """Evaluate this news article under the Indian Polity and Governance (UPSC GS-II) syllabus:
CHAPTER: {chapter_name} (Laxmikanth 8th Edition)
PUBLICATION: {publication} | CATEGORY: {category}
ARTICLE TITLE: {title}

RAW ARTICLE TEXT:
{article_text}

Output strictly valid JSON matching the exact schema provided in the system prompt.
Do not wrap in backticks or markdown fences."""


# ==============================================================================
# 3. SYNTHESIS ENGINE
# ==============================================================================

class DailyPolitySynthesizer:
    def __init__(self):
        self.storage = NewspaperStorage()
        self.rotator = KeyRotator()
        self.model = "openai/gpt-oss-120b"

    def synthesize_analysis(self, chapter_name: str, pub: str, cat: str, title: str, text: str) -> PhDLevelPolityAnalysis:
        prompt = ANALYSIS_USER_PROMPT_TEMPLATE.format(
            chapter_name=chapter_name,
            publication=pub,
            category=cat,
            title=title,
            article_text=text[:8500]
        )

        attempts = 0
        max_attempts = len(self.rotator.keys)

        while attempts < max_attempts:
            key, client = self.rotator.get_next_client()
            key_preview = f"...{key[-6:]}"
            try:
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": EXPERT_POLITY_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
                raw_json = completion.choices[0].message.content
                return PhDLevelPolityAnalysis.model_validate_json(raw_json)
            except RateLimitError:
                attempts += 1
                logger.warning(f"Rate limited on key {key_preview}. Rotating immediately...")
                time.sleep(1.0)
            except Exception as e:
                attempts += 1
                logger.warning(f"Error on key {key_preview}: {e}. Retrying next key...")
                time.sleep(1.0)

        # Fallback pause if all keys are temporarily rate-limited
        logger.warning("All Groq keys rate-limited. Pausing 15s...")
        time.sleep(15.0)
        _, client = self.rotator.get_next_client()
        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": EXPERT_POLITY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        return PhDLevelPolityAnalysis.model_validate_json(completion.choices[0].message.content)

    def run_synthesis(
        self,
        target_date: Optional[str] = None,
        limit: Optional[int] = None,
        cooldown_seconds: int = 4
    ):
        print("=" * 80)
        print("STARTING PHD-LEVEL POLITY SMART NOTE SYNTHESIZER")
        print(f"Bucket: {self.storage.bucket} | Model: {self.model} | Pacing: {cooldown_seconds}s")
        print("=" * 80)

        all_objects = self.storage.list_objects(prefix="daily_press/")
        classified_keys = [
            k for k in all_objects
            if "/classified/" in k and k.endswith(".json")
        ]

        if target_date:
            classified_keys = [k for k in classified_keys if f"/{target_date}/" in k]

        classified_keys.sort()
        print(f"Discovered {len(classified_keys)} classified articles in MinIO.")

        unprocessed_keys = []
        for c_key in classified_keys:
            smart_note_key = c_key.replace("/classified/", "/smart_notes/").replace(".json", "")
            parts = smart_note_key.split("/")
            parts[-1] = f"smart_notes_{parts[-1]}.json"
            target_key = "/".join(parts)

            if not self.storage.object_exists(target_key):
                unprocessed_keys.append(c_key)

        print(f"Articles pending smart note synthesis: {len(unprocessed_keys)}\n")
        synthesized = 0

        for c_key in unprocessed_keys:
            if limit and synthesized >= limit:
                print(f"[LIMIT REACHED] Stopped after {limit} syntheses.")
                break

            payload = self.storage.get_json(c_key)
            if not payload:
                continue

            article_id = payload.get("article_id") or c_key.split("/")[-1].replace(".json", "")
            title = payload.get("title", "")
            pub = payload.get("publication", "the_hindu")
            cat = payload.get("category", "national")
            text = payload.get("full_article", "")
            iso_date = payload.get("article_date") or payload.get("published_date") or "2026-10-12"
            classification = payload.get("classification", {})
            chapter_name = classification.get("chapter_name") or "Constitutional Framework"

            daily_smart_note_key = f"daily_press/{pub}/{iso_date}/{cat}/smart_notes/smart_notes_{article_id}.json"

            if self.storage.object_exists(daily_smart_note_key):
                continue

            print(f"\n[{iso_date}] Synthesizing: {title[:55]}... ({pub}/{cat})")
            try:
                intel = self.synthesize_analysis(
                    chapter_name=chapter_name,
                    pub=pub,
                    cat=cat,
                    title=title,
                    text=text
                )

                smart_note_payload = {
                    "article_id": article_id,
                    "publication": pub,
                    "category": cat,
                    "article_date": iso_date,
                    "chapter_name": chapter_name,
                    "title": title,
                    "url": payload.get("url", ""),
                    "published_at": payload.get("published_at_ist") or payload.get("published_at", ""),
                    "scraped_at": payload.get("scraped_at", ""),
                    **intel.model_dump(),
                }

                self.storage.put_json(daily_smart_note_key, smart_note_payload)
                print(f"     [✓ SAVED FEED] -> {daily_smart_note_key}")
                synthesized += 1

                if cooldown_seconds > 0:
                    countdown_sleep(cooldown_seconds)

            except Exception as e:
                print(f"     [!] Failed synthesizing {article_id}: {e}")

        print("\n" + "=" * 80)
        print("SMART NOTE SYNTHESIS RUN COMPLETE")
        print(f"Newly Synthesized : {synthesized}")
        print("=" * 80)


if __name__ == "__main__":
    synthesizer = DailyPolitySynthesizer()
    synthesizer.run_synthesis(target_date="2026-10-25", limit=None, cooldown_seconds=4)