import os
import sys
import json
import time
import argparse
import itertools
import threading
from groq import Groq
from dotenv import load_dotenv

# Ensure root directory is on sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from src.storage.minio_client_new import MinIOStorage
from src.classifiers.taxonomy import LAXMIKANTH_8TH_EDITION

# ---------------------------------------------------------------------------
# 1. Round-Robin Key Manager
# ---------------------------------------------------------------------------
class GroqKeyRotator:
    """Rotates between multiple Groq API keys in a thread-safe round-robin manner."""
    def __init__(self):
        raw_keys = os.getenv("GROQ_API_KEYS", "")
        self.keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        
        # Fallback to single GROQ_API_KEY
        if not self.keys:
            single = os.getenv("GROQ_API_KEY")
            if single:
                self.keys = [single.strip()]

        if not self.keys:
            raise RuntimeError("Missing GROQ_API_KEYS or GROQ_API_KEY in your .env file.")

        self._cycle = itertools.cycle(self.keys)
        self._lock = threading.Lock()
        self._clients = {key: Groq(api_key=key) for key in self.keys}
        print(f"🔑 Initialized Key Rotator with {len(self.keys)} Groq API key(s).")

    def get_client(self) -> tuple[Groq, str]:
        with self._lock:
            key = next(self._cycle)
        masked_key = f"{key[:7]}...{key[-4:]}"
        return self._clients[key], masked_key


storage = MinIOStorage()
rotator = GroqKeyRotator()
MODEL_NAME = "openai/gpt-oss-120b"
STATIC_PREFIX = "static/laxmikanth/"

# ---------------------------------------------------------------------------
# 2. Comprehensive Academic Study Prompt (No Mention of Laxmikanth)
# ---------------------------------------------------------------------------
def build_prompts(chapter_num: int, chapter_title: str) -> tuple[str, str]:
    system_prompt = """You are an authoritative UPSC Civil Services faculty member and scholar of Indian Constitutional Law and Comparative Jurisprudence.

Your objective is to generate an exhaustive, high-yield masterclass study dossier for the given constitutional syllabus module entirely from first principles, constitutional text, and established jurisprudence.

CRITICAL INSTRUCTIONS:
- Do NOT mention the name "Laxmikanth" or any private author/textbook anywhere in the content.
- Do NOT include editorial current affairs, ephemeral newspaper clippings, or subjective Mains opinion pieces.
- Rely purely on canonical static constitutional law, academic depth, and civil services examination rigor.
- Use clean GitHub-flavored Markdown with bold headings, clean bullet points, and properly formatted Markdown comparison tables.

You MUST structure your masterclass dossier systematically across the following mandatory sections:

# Chapter {chapter_num}: {chapter_title}
🏷️ Polity & Constitutional Law Masterclass Dossier • *Canonical Static Syllabus*

---

## 1. Foundational Concept & Evolution
### 📌 Core Concepts & Theoretical Principles
- Explain the fundamental principles, conceptual definitions, and governance rationale systematically from scratch with absolute academic clarity.
- Clarify core legal doctrines, institutional mandates, and procedural safeguards.

### 🏛️ Historical, Colonial & Philosophical Evolution
- Pre-Independence Colonial Charters: Trace evolutionary roots from colonial-era constitutional experiments (e.g., Regulating Acts, Charter Acts, Indian Councils Acts 1861/1892/1909, GoI Acts 1919 and 1935). Detail what features were adapted or discarded.
- Constituent Assembly Debates (CAD): Detail key debates, dissenting opinions, compromises, and philosophies voiced by Dr. B.R. Ambedkar, Jawaharlal Nehru, Sardar Patel, or other members regarding this institution or provision.
- Post-Independence Institutional Trajectory: Trace the early decades of operational evolution, institutional friction, and how implementation matured after 1950.

### ⚖️ Comparative Constitutional Law & Foreign Precedents
- Examine how this constitutional idea compares globally (e.g., UK unwritten conventions, US judicial review/due process, Irish Directive Principles, Canadian quasi-federalism, Australian concurrent powers, Weimar emergency provisions, South African socio-economic rights).
- Cite relevant foreign court doctrines or landmark comparative jurisprudence (e.g., US Supreme Court, UK House of Lords/Supreme Court) that influenced Indian constitutional thought.

### ⚙️ Structural Framework & Institutional Mechanics
- Detail structural organization, qualifications, appointment procedures, tenure, removal thresholds, service conditions, powers, operational limitations, and discretionary domains.
- Include a clear, comprehensive Markdown Comparison Table analyzing structural dimensions (e.g., Power vs. Limitation, Constitutional vs. Statutory facets, or Union vs. State variations).

---

## 2. Static & Constitutional Linkages
### 📖 Constitutional Articles, Parts & Schedules
- Exhaustively enumerate all pertinent Articles of the Constitution of India, their specific clauses, relevant Parts, and Schedules.
- Provide a clear breakdown of textual provisions and constitutional mandates.

### 📜 Constitutional Amendments & Statutory Enactments
- Detail every constitutional amendment affecting this topic (e.g., 1st, 7th, 24th, 42nd, 44th, 52nd, 73rd/74th, 86th, 91st, 101st, 103rd, etc.) and explain the structural shift brought by each.
- Detail relevant parent statutory acts, rules, or legislative schemes enforcing the mandate.

### ⚖️ Landmark Judicial Precedents & Legal Doctrines
- Systematically catalog landmark Supreme Court of India judgments, their facts, constitutional questions, exact ratio decidendi, and legal impact.
- Articulate associated constitutional doctrines (e.g., Basic Structure, Pith and Substance, Harmonious Construction, Colorable Legislation, Eclipse, Severability, Procedure Established by Law vs. Due Process).

### 📋 Authoritative Commissions & Committee Recommendations
- Integrate authoritative findings, structural critique, and specific reform recommendations from key commissions (e.g., Sarkaria Commission, Punchhi Commission, Venkatachaliah Commission / NCRWC, 1st & 2nd Administrative Reforms Commission (ARC), Law Commission Reports).

---
"""

    user_prompt = f"Generate the exhaustive constitutional study masterclass for Chapter {chapter_num}: {chapter_title}."
    return system_prompt.format(chapter_num=chapter_num, chapter_title=chapter_title), user_prompt

# ---------------------------------------------------------------------------
# 3. Generation & Storage Logic
# ---------------------------------------------------------------------------
def generate_and_save_chapter(chapter_num: int, force: bool = False):
    chapter_title = LAXMIKANTH_8TH_EDITION.get(chapter_num)
    if not chapter_title:
        print(f"❌ Chapter {chapter_num} not found in taxonomy.")
        return

    object_name = f"{STATIC_PREFIX}chapter_{chapter_num:02d}.json"

    # Check existence in upsc-ai bucket
    if not force:
        try:
            if storage.object_exists(object_name):
                print(f"⏩ [EXISTS] Chapter {chapter_num:02d}: '{chapter_title}' already in {storage.bucket}. Pass --force to overwrite.")
                return
        except Exception:
            pass

    client, key_tag = rotator.get_client()
    print(f"🚀 [GENERATING] Chapter {chapter_num:02d}: '{chapter_title}' | Key: [{key_tag}]...")

    system_prompt, user_prompt = build_prompts(chapter_num, chapter_title)

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=6000,
        )

        markdown_content = response.choices[0].message.content.strip()

# Sanitize against accidental mentions
        markdown_content = (
            markdown_content
            .replace("M. Laxmikanth", "Standard Constitutional Treatise")
            .replace("Laxmikanth", "Constitutional Framework")
            .replace("laxmikanth", "constitutional framework")
        )

        # Store both structured metadata and the ready-to-render Markdown string
        data = {
            "chapter_id": chapter_num,
            "chapter_title": chapter_title,
            "headline": f"{chapter_title}: Core Constitutional Principles & Evolutionary Dynamics",
            "markdown": markdown_content,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # Upload directly to MinIO (upsc-ai)
        storage.upload_json(object_name, data)
        print(f"✅ [SAVED TO MINIO: {storage.bucket}] {object_name}")

    except Exception as e:
        print(f"❌ [ERROR] Chapter {chapter_num} failed: {e}")

# ---------------------------------------------------------------------------
# 4. CLI Runner
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate comprehensive constitutional chapter notes to upsc-ai with Round-Robin Groq keys")
    parser.add_argument("--chapter", type=int, help="Single chapter number (e.g. --chapter 1)")
    parser.add_argument("--start", type=int, default=1, help="Start chapter number")
    parser.add_argument("--end", type=int, default=len(LAXMIKANTH_8TH_EDITION), help="End chapter number")
    parser.add_argument("--force", action="store_true", help="Overwrite existing MinIO files")
    parser.add_argument("--all", action="store_true", help="Generate all chapters sequentially")

    args = parser.parse_args()

    if args.chapter:
        generate_and_save_chapter(args.chapter, force=args.force)
    elif args.all:
        print(f"Starting batch generation for all {len(LAXMIKANTH_8TH_EDITION)} chapters...")
        for ch in range(1, len(LAXMIKANTH_8TH_EDITION) + 1):
            generate_and_save_chapter(ch, force=args.force)
            time.sleep(1.2)
    else:
        for ch in range(args.start, args.end + 1):
            generate_and_save_chapter(ch, force=args.force)
            time.sleep(1.2)

if __name__ == "__main__":
    main()
