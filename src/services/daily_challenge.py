import asyncio
import hashlib
import itertools
import json
import os
import random
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from groq import AsyncGroq
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import DailyChallengeModel, DailyChallengeQuestionModel
from src.schema.daily_challenge import DailyChallengeItem, DailyChallengeSet

# --- ROUND-ROBIN GROQ KEY ROTATION ---
def _load_groq_keys() -> List[str]:
    keys_str = os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", ""))
    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    if not keys:
        raise ValueError("No GROQ API keys found in environment variables (GROQ_API_KEYS).")
    return keys

_GROQ_KEYS_CYCLE = itertools.cycle(_load_groq_keys())

def get_next_groq_client() -> AsyncGroq:
    return AsyncGroq(api_key=next(_GROQ_KEYS_CYCLE))


def compute_question_fingerprint(theme: str, question_text: str) -> str:
    """Computes a normalized SHA-256 signature to prevent duplicate questions."""
    normalized = "".join(filter(str.isalnum, (theme + question_text).lower()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# --- SYLLABUS BLUEPRINT POOL (45+ Curated UPSC Static Anchors) ---
BLUEPRINT_POOL: List[Dict[str, str]] = [
    # PARLIAMENT & FINANCIAL PROCEDURE
    {
        "archetype": "Pairing",
        "theme": "Money Bills vs Financial Bills",
        "focus": "Art 110 vs Art 117(1) vs Art 117(3). Test introducing chamber, presidential recommendation, and Rajya Sabha powers.",
    },
    {
        "archetype": "Institutional Mechanics",
        "theme": "Parliamentary Committees",
        "focus": "Public Accounts Committee, Estimates Committee, and Committee on Public Undertakings: membership limits, exclusion of Ministers, and term lengths.",
    },
    {
        "archetype": "Pairing",
        "theme": "Office of Speaker & Deputy Speaker",
        "focus": "Art 93–96 & Tenth Schedule. Speaker's casting vote, tenure beyond dissolution, and Kihoto Hollohan tribunal status.",
    },
    {
        "archetype": "Multi-Statement",
        "theme": "Parliamentary Motions",
        "focus": "No-Confidence Motion (Rule 198) vs Censure Motion vs Adjournment Motion: Lok Sabha exclusivity, member support threshold, and grounds disclosure.",
    },
    # CONSTITUTIONAL & STATUTORY BODIES
    {
        "archetype": "Pairing",
        "theme": "Constitutional vs Statutory Bodies",
        "focus": "Art 280 Finance Commission, Art 324 Election Commission, Art 338/338A/338B vs statutory NHRC and CVC.",
    },
    {
        "archetype": "Institutional Mechanics",
        "theme": "Election Commission of India",
        "focus": "Art 324(5) service conditions: removal parity of CEC with SC Judge vs removal of other Election Commissioners on CEC recommendation.",
    },
    {
        "archetype": "Institutional Mechanics",
        "theme": "Comptroller and Auditor General (CAG)",
        "focus": "Art 148–151. Post-retirement employment ban, consolidated fund charged expenditure, and audit jurisdiction over public corporations.",
    },
    {
        "archetype": "Institutional Mechanics",
        "theme": "Finance Commission Mechanics",
        "focus": "Art 280 & Finance Commission Act 1951: qualifications of members, advisory nature of recommendations, and Art 281 tabling.",
    },
    # FEDERALISM & INTER-STATE RELATIONS
    {
        "archetype": "Pairing",
        "theme": "Inter-State Water Disputes & Councils",
        "focus": "Art 262 statutory exclusion of Supreme Court jurisdiction under 1956 Act vs Art 263 advisory Inter-State Council.",
    },
    {
        "archetype": "Multi-Statement",
        "theme": "Parliament's Power to Legislate on State List",

    "focus": "Art 249 (RS 2/3rd resolution, 1 year validity) vs Art 252 (2+ states consent, state legislature cannot amend or repeal).",
    },
    {
        "archetype": "Multi-Statement",
        "theme": "Emergency Dynamics",
        "focus": "Art 352 (Cabinet written advice, 1-month approval) vs Art 356 (failure of constitutional machinery, Bommai floor test) vs Art 365.",
    },
    # FUNDAMENTAL RIGHTS, DPSP & DUTIES
    {
        "archetype": "Pairing",
        "theme": "Writ Jurisdiction Dynamics",
        "focus": "Art 32 vs Art 226: territorial extent, enforcement of legal rights vs Fundamental Rights, and Quo-Warranto locus standi.",
    },
    {
        "archetype": "Multi-Statement",
        "theme": "Fundamental Rights vs DPSP Harmonization",
        "focus": "Art 31C protection scope for Art 39(b)(c), non-justiciability of Art 37, and Minerva Mills balance doctrine.",
    },
    {
        "archetype": "Conceptual & Theory",
        "theme": "Right to Life & Personal Liberty",
        "focus": "Art 21 evolution: AK Gopalan procedure established by law vs Maneka Gandhi due process / just, fair, and reasonable standard.",
    },
    {
        "archetype": "Pairing",
        "theme": "Fundamental Duties Enforceability",
        "focus": "Art 51A Swaran Singh / Verma Committee recommendations: non-enforceable nature without specific enabling statutory legislation.",
    },
    # JUDICIARY & CONSTITUTIONAL INTERPRETATION
    {
        "archetype": "Institutional Mechanics",
        "theme": "Supreme Court Jurisdiction",
        "focus": "Art 131 Original jurisdiction limits (pre-constitution treaties excluded), Art 136 Special Leave Petition scope, and Art 143 Advisory opinions.",
    },
    {
        "archetype": "Pairing",
        "theme": "Judicial Appointments & Collegium",
        "focus": "Art 124(2) Second & Third Judges Cases, NJAC striking down (99th Amendment), and memorandum of procedure conventions.",
    },
    {
        "archetype": "Conceptual & Theory",
        "theme": "Constitutionalism and Limited Government",
        "focus": "Substantive checks vs formal constitution: judicial review, basic structure, separation of powers, and institutional restraint.",
    },
    {
        "archetype": "Conceptual & Theory",
        "theme": "Rule of Law vs Administrative Discretion",
        "focus": "Diceyan concepts of equality before law vs French Droit Administratif; procedural due process in administrative actions.",
    },
    # EXECUTIVE & SPECIAL PROVISIONS
    {
        "archetype": "Pairing",
        "theme": "Pardoning Powers",
        "focus": "Art 72 vs Art 161: Court Martial death sentences (President exclusively), bound by aid and advice of CoM (Maru Ram & Kehar Singh).",
    },
    {
        "archetype": "Institutional Mechanics",
        "theme": "Governor's Discretionary Bounds",
        "focus": "Art 163(1) general advice mandate vs Art 163(2) constitutional discretion finality and Art 200 bill reservation.",
    },
    {
        "archetype": "Institutional Mechanics",
        "theme": "Ordinance Making Mechanics",
        "focus": "Art 123 vs Art 213: satisfaction of executive subject to judicial review, 6 weeks from reassembly, and DC Wadhwa re-promulgation limits.",
    },
]


def select_blueprints_for_date(drill_date: date, count: int = 15) -> List[Dict[str, str]]:
    """Deterministically selects distinct blueprints based on the date seed."""
    seed_val = int(drill_date.strftime("%Y%m%d"))
    rng = random.Random(seed_val)
    shuffled = BLUEPRINT_POOL.copy()
    rng.shuffle(shuffled)
    return shuffled[:count]


def get_recent_exclusions(session: Session, drill_date: date, days_back: int = 14) -> List[str]:
    """Fetches recent question stems to pass as negative constraints."""
    cutoff = drill_date - timedelta(days=days_back)

    query = (
        select(DailyChallengeQuestionModel.question_text)
        .join(DailyChallengeModel, DailyChallengeQuestionModel.challenge_id == DailyChallengeModel.id)
        .where(DailyChallengeModel.challenge_date >= cutoff)
        .where(DailyChallengeModel.challenge_date < drill_date)
        .limit(60)
    )
    stems = session.execute(query).scalars().all()
    return [s[:100].strip() for s in stems]


SYSTEM_PROMPT = """You are an elite UPSC Civil Services Examination (CSE) Prelims paper setter specializing in Indian Polity and Constitutional Law.

Generate exactly 1 high-difficulty, strictly STATIC MCQ reflecting post-2023 UPSC trends.

CRITICAL CONSTITUTIONAL AXIOMS (FACTUAL INTEGRITY MANDATORY):
1. BILLS DYNAMICS:
   - Money Bill (Art 110): Lok Sabha ONLY, President recommendation REQUIRED. Rajya Sabha has 14-day limit and cannot amend/reject.
   - Financial Bill (I) (Art 117(1)): Lok Sabha ONLY, President recommendation REQUIRED. Rajya Sabha has ordinary powers after introduction.
   - Financial Bill (II) (Art 117(3)): Either House, NO President recommendation required for introduction (only for consideration/passing).
2. STATE LIST LEGISLATION:
   - Art 249: RS 2/3rd resolution, active for 1 year per resolution.
   - Art 252: By consent of 2+ states. Parliament alone can amend or repeal it (Art 252(2)); states CANNOT unilaterally withdraw or amend.
3. FORMAT CONSTRAINTS:
   - For Pairing/Count archetypes: "options" must strictly be: "A": "Only one", "B": "Only two", "C": "All three", "D": "None" (or "Neither").
   - For Multi-statement archetypes: "options" must strictly be combinations like: "A": "1 only", "B": "2 only", "C": "Both 1 and 2", "D": "Neither 1 nor 2".
   - Self-contained: Every concept or statement referenced must be fully spelled out in statements or question.
   - For Pairing/Count archetypes, ensure you provide exactly 3 or 4 statements if options include "All three" or "All four".
4. PARLIAMENTARY MOTIONS:
   - No-Confidence Motion (Rule 198): Lok Sabha ONLY, requires support of at least 50 members, no specific reasons/grounds need to be cited.
   - Censure Motion: Lok Sabha ONLY (Council of Ministers is collectively responsible only to LS under Art 75(3)), specific reasons/charges MUST be stated, NO 50-member threshold requirement.
   - Adjournment Motion: Lok Sabha ONLY, requires support of 50 members, pinpoints an urgent matter of public importance with serious administrative failure.
OUTPUT FORMAT (Valid JSON only):
{
  "archetype": "Pairing / Conceptual & Theory / Multi-Statement / Assertion-Reason / Institutional Mechanics",
  "theme": "Theme title",
  "primary_article_ref": "Article XXX",
  "question": "Question stem text...",
  "statements": ["1. First statement...", "2. Second statement..."],
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correct_option": "A",
  "explanation": "Deep, factually impeccable breakdown...",
  "traps_analyzed": "Specific trap analyzed..."
}
"""


def _normalize_mcq_data(data: dict) -> dict:
    """Standardizes JSON output across varying LLM responses."""
    if "correct_option" not in data:
        for k in ["correct_answer", "answer", "correctOption", "correct"]:
            if k in data:
                val = str(data.pop(k)).strip().upper()
                data["correct_option"] = val[0] if val else "A"
                break
    if "explanation" not in data:
        for k in ["solution", "rationale", "analysis", "reason"]:
            if k in data:
                data["explanation"] = str(data.pop(k))
                break
    if "correct_option" not in data:
        data["correct_option"] = "A"
    if "explanation" not in data:
        data["explanation"] = "No explanation provided."
    return data


async def generate_single_mcq_with_retry(
    order_id: int,
    blueprint: Dict[str, str],
    exclusions: List[str],
    max_retries: int = 2,
) -> tuple[DailyChallengeItem, str]:
    """Generates a question with negative constraints and retries if collision occurs."""
    client = get_next_groq_client()

    exclusion_clause = ""
    if exclusions:
        formatted = "\n- ".join(exclusions[:8])
        exclusion_clause = f"\nNEGATIVE EXCLUSION LIST (Do NOT duplicate or repeat these stems):\n- {formatted}"

    user_prompt = f"""Generate a {blueprint['archetype']} MCQ on the theme: '{blueprint['theme']}'.
Specific Focus: {blueprint['focus']}
{exclusion_clause}
Ensure high analytical difficulty and 100% adherence to constitutional facts."""

    for attempt in range(max_retries + 1):
        temp = 0.3 if attempt == 0 else 0.6  # slightly higher temperature if retrying

        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=temp,
            max_tokens=4000,
        )

        data = json.loads(response.choices[0].message.content)
        data["id"] = order_id
        normalized = _normalize_mcq_data(data)

        fingerprint = compute_question_fingerprint(
            theme=normalized.get("theme", ""),
            question_text=normalized.get("question", ""),
        )

        item = DailyChallengeItem.model_validate(normalized)
        return item, fingerprint

    raise RuntimeError(f"Failed to generate unique question for order {order_id}")


async def generate_daily_challenge_payload(
    target_date: str,
    exclusions: List[str],
) -> tuple[DailyChallengeSet, List[str]]:
    """Concurrently generates all 15 questions with rotation and anti-duplication guards."""
    parsed_date = date.fromisoformat(target_date)
    blueprints = select_blueprints_for_date(parsed_date, count=15)

    print(f"⚡ [Batch] Generating 15 distinct questions with {len(exclusions)} negative exclusions...")

    tasks = [
        generate_single_mcq_with_retry(
            order_id=idx + 1,
            blueprint=bp,
            exclusions=exclusions,
        )
        for idx, bp in enumerate(blueprints)
    ]

    results = await asyncio.gather(*tasks)
    questions = [res[0] for res in results]
    fingerprints = [res[1] for res in results]

    challenge_set = DailyChallengeSet(
        challenge_date=target_date,
        title="Daily Static Polity Prelims Drill",
        questions=questions,
    )
    return challenge_set, fingerprints


async def get_or_create_daily_challenge(
    session: Session,
    target_date: Optional[date] = None,
) -> DailyChallengeModel:
    drill_date = target_date or date.today()

    # 1. Check DB Cache
    print(f"🔍 [DB] Checking if daily challenge exists for {drill_date}...")
    query = select(DailyChallengeModel).where(DailyChallengeModel.challenge_date == drill_date)
    existing_challenge = session.execute(query).scalars().first()

    if existing_challenge:
        print(f"⚡ [DB Cache] Found existing challenge for {drill_date} (ID: {existing_challenge.id}).")
        return existing_challenge

    # 2. Retrieve past 14 days of question exclusions
    exclusions = get_recent_exclusions(session, drill_date, days_back=14)
    print(f"🛡️ [Anti-Repetition] Loaded {len(exclusions)} recent question signatures for exclusion.")

    # 3. Concurrently generate fresh set
    validated_set, fingerprints = await generate_daily_challenge_payload(drill_date.isoformat(), exclusions)

    # 4. Persist to Postgres
    challenge = DailyChallengeModel(
        challenge_date=drill_date,
        title=validated_set.title,
        total_questions=len(validated_set.questions),
    )
    session.add(challenge)
    session.flush()

    for q, fp in zip(validated_set.questions, fingerprints):
        q_record = DailyChallengeQuestionModel(
            challenge_id=challenge.id,
            question_order=q.id,
            archetype=q.archetype,
            theme=q.theme,
            primary_article_ref=q.primary_article_ref,
            question_text=q.question,
            statements=q.statements,
            options=q.options.model_dump(),
            correct_option=q.correct_option,
            explanation=q.explanation,
            traps_analyzed=q.traps_analyzed,
            fingerprint=fp,
        )
        session.add(q_record)

    session.commit()
    session.refresh(challenge)
    print(f"🎉 [DB] Successfully saved fresh 15-question drill for {drill_date}.")
    return challenge
