# src/api/routes/chat_agent.py
import json
import re
from datetime import timedelta, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session

from src.core.key_pool import groq_pool
from src.database.session import get_db
from src.database.models import (
    ConstitutionalArticleModel,
    IssueDossierModel,
    IssueGraphEdgeModel,
    PrelimsPYQModel,
    DailyChallengeQuestionModel,
)
from src.storage.minio_client import NewspaperStorage
from src.storage.redis_cache import get_redis_cache

router = APIRouter(prefix="/api/v1/agent", tags=["AI Constitutional & Platform Concierge"])

IST = timezone(timedelta(hours=5, minutes=30))
storage = NewspaperStorage()

# Preserving your exact chosen model
MODEL_NAME = "openai/gpt-oss-120b"

# Cache TTL for tool evaluations (2 hours)
TOOL_CACHE_TTL = 7200

OUT_OF_SCOPE_RESPONSE = (
    "OUT OF SCOPE • UPSC CSE GS-II ONLY\n\n"
    "I am the Polity Mentor Concierge, strictly restricted to UPSC Civil Services General Studies Paper-II "
    "(Indian Constitution, Polity, Governance, Social Justice, and International Relations) and Polity Mentor platform guidance.\n\n"
    "Please ask a question related to Constitutional Articles, Supreme Court doctrines, Parliament, Federalism, "
    "Governance mechanisms, International Relations, or UPSC Prelims/Mains GS-II preparation."
)


# ------------------------------------------------------------------------------
# 1. Text Sanitization (Hard Strip of Markdown Asterisks & Artifacts)
# ------------------------------------------------------------------------------
def clean_plain_text(text: str) -> str:
    """
    Strips markdown asterisks (**bold**, *italics*), headers, and code fences,
    returning pure plain text for mobile chat rendering.
    """
    if not text:
        return ""
    cleaned = re.sub(r"^[ \t]*#{1,6}\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"__(.*?)__", r"\1", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"(?<!\w)_(.*?)_(?!\w)", r"\1", cleaned, flags=re.DOTALL)
    cleaned = cleaned.replace("**", "").replace("*", "").replace("`", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# ------------------------------------------------------------------------------
# 2. Platform Knowledge Manifest
# ------------------------------------------------------------------------------
PLATFORM_MANIFEST: Dict[str, str] = {
    "daily_notes_schedule": (
        "Daily Current Affairs Smart Notes from The Hindu and The Indian Express "
        "are ingested, synthesized, and published every morning before 7:00 AM IST."
    ),
    "navigation_yesterday_notes": (
        "To view previous editions of daily notes, use the 'Today / Yesterday' toggle button "
        "located right above the publication tab bar (The Hindu, Editorial, Explained) on the Daily Current Affairs Page."
    ),
    "daily_challenge_drill": (
        "The Daily Prelims Drill features 15 high-yield, curated MCQs covering both "
        "core static constitutional concepts (Laxmikanth) and dynamic current affairs linkages."
    ),
    "articles_catalogue": (
        "You can explore comprehensive clause-by-clause Bare Act breakdowns, landmark judicial precedents, "
        "and prelims edge-case traps by tapping on any article chip (e.g., 'Article 13' or 'Article 200') "
        "or visiting the Constitutional Articles section."
    ),
    "subscriptions_and_pricing": (
        "Polity Mentor is currently running its open beta. All smart notes, statutory analyses, "
        "and daily prelims test drills are accessible to registered aspirants."
    ),
    "contact_support": (
        "For technical issues, feedback, or editorial questions, reach our team directly at admin@politymentor.com."
    ),
    "mains_answers": (
        "Polity Mentor does not currently automate subjective Mains answer grading. We recommend practicing "
        "objective prelims traps and dialectical frameworks provided within the smart notes."
    ),
}


# ------------------------------------------------------------------------------
# 3. Schemas
# ------------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'user', 'assistant', or 'system'")
    content: str = Field(..., description="The message text")


class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Optional session or user identifier")
    message: str = Field(..., description="User's query")
    history: List[ChatMessage] = Field(default_factory=list, description="Recent conversation turns (up to 6)")


class ChatResponse(BaseModel):
    status: str
    response: str
    tools_used: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------------------
# 4. Intent, Scope, Entity Extraction & Mode Routing Helpers
# ------------------------------------------------------------------------------
def extract_search_topic(query: str) -> str:
    """
    Extracts a clean entity/article/topic string for SQL searches so conversational
    filler ('explain', 'in detail', 'wrt') never pollutes database queries.
    """
    art_match = re.search(r"\b(article|art\.?)\s*(\d+[a-z]?)\b", query, flags=re.IGNORECASE)
    if art_match:
        return f"Article {art_match.group(2).upper()}"

    cleaned = re.sub(
        r"\b(explain|elaborate|decode|breakdown|break down|teach|discuss|analyze|analyse|"
        r"overview|notes on|summary of|guide on|what is|what are|tell me about|in detail|"
        r"please|wrt|with respect to|regarding|about|the|of|for|on)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^\w\s-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else query.strip()[:60]


def wants_verbatim_mcq(query: str) -> bool:
    """Returns True ONLY if the user explicitly requests a verbatim PYQ or practice MCQ."""
    q = query.strip().lower()
    explicit_triggers = [
        r"\bverbatim\b",
        r"\bgive\s+(me\s+)?(a\s+|an\s+|some\s+)?(mcq|question|pyq|drill|quiz)\b",
        r"\bshow\s+(me\s+)?(the\s+|a\s+)?(mcq|question|pyq)\b",
        r"\bpractice\s+(mcq|question|drill)\b",
        r"\btest\s+me\b",
        r"\bask\s+(me\s+)?(a\s+)?question\b",
        r"\bsolve\s+(a\s+|this\s+)?(mcq|question|pyq)\b",
        r"\bwith\s+options\b",
    ]
    return any(re.search(pat, q) for pat in explicit_triggers)


def is_greeting_only(query: str) -> bool:
    q = re.sub(r"[^\w\s]", "", query.strip().lower())
    return q in {"hi", "hello", "hey", "namaste", "good morning", "good evening", "good afternoon"}


def is_follow_up_query(query: str, history: List[ChatMessage]) -> bool:
    """Detects whether the query is continuing an existing multi-turn thread."""
    if not history:
        return False

    q_lower = query.strip().lower()
    pronoun_markers = ["this", "that", "these", "it", "they", "here", "above"]
    has_pronoun = any(re.search(rf"\b{p}\b", q_lower) for p in pronoun_markers)

    follow_up_stems = [
        "is this", "is that", "important for prelims", "what about",
        "why is", "can you clarify", "tell me more", "how does this",
        "what if", "difference between", "critique", "which option",
        "clarify", "correct answer", "solve this", "yes", "no",
        "how many pyq", "pyq count", "give me the question", "verbatim",
        "simplify", "in short", "summarize",
    ]
    has_stem = any(stem in q_lower for stem in follow_up_stems)
    explicit_new_article = bool(
        re.search(r"\b(article|chapter|schedule|part)\s+\d+", q_lower) and not has_pronoun
    )

    if explicit_new_article:
        return False

    return has_stem or has_pronoun or len(q_lower.split()) <= 6


def is_deep_explanation_request(query: str, scope: str, history: List[ChatMessage]) -> bool:
    """
    Triggers the deep 4-tier pedagogical flow (Layman -> Detail -> Analysis -> PYQ Trend)
    ONLY when the user is asking to explain, decode, or teach a GS-II topic, chapter, or article.
    Returns False for platform FAQs, news/PIB lookups, pure PYQ count queries, or follow-ups.
    """
    if scope != "GS2":
        return False

    if is_follow_up_query(query, history):
        return False

    q = query.strip().lower()

    non_explanation_patterns = [
        r"\b(today'?s|yesterday'?s|latest)\s+(news|editorial|hindu|indian express|pib|smart notes|current affairs)\b",
        r"\bhow\s+many\s+(pyq|pyqs|questions)\b",
        r"\bpyq\s+(count|trend|list)\b",
        r"\bare\s+there\s+any\s+(pyq|pyqs|questions)\b",
        r"\bgive\s+(me\s+)?(a\s+|an\s+)?(mcq|pyq|question|drill)\b",
    ]
    if any(re.search(pat, q) for pat in non_explanation_patterns):
        return False

    explanation_triggers = [
        r"\b(explain|elaborate|decode|breakdown|break down|teach|discuss|analyze|analyse|overview|notes on|summary of|guide on)\b",
        r"\bwhat\s+(is|are|does)\b",
        r"\b(significance|importance|evolution|structure|provisions|scope|doctrine|mechanism|powers|functions)\s+of\b",
        r"\b(article|art\.?|chapter|part|schedule|amendment)\s+\d+[a-z]?\b",
    ]
    if any(re.search(pat, q) for pat in explanation_triggers):
        return True

    word_count = len(q.split())
    if 1 <= word_count <= 7 and not q.endswith("?"):
        return True

    return False


def classify_gs2_scope(query: str, history: List[ChatMessage]) -> str:
    """
    Fast deterministic + LLM gatekeeper.
    Returns one of: 'GS2', 'PLATFORM', or 'OUT_OF_SCOPE'.
    """
    recent_context = ""
    if history:
        turns = [f"{m.role}: {m.content[:220]}" for m in history[-4:]]
        recent_context = "Recent conversation context:\n" + "\n".join(turns) + "\n\n"

    gate_system = (
        "You are a strict domain classifier for Polity Mentor (an Indian UPSC CSE GS-II platform). "
        "Classify the user's message into strictly one of three labels:\n"
        "- GS2: Anything related to the Indian Constitution, Articles, Schedules, Parts, Amendments, "
        "Supreme Court/High Court cases & doctrines, Parliament, State Legislatures, President/Governor, "
        "Federalism, Local Bodies (Panchayats/Municipalities), Constitutional/Statutory/Regulatory Bodies, "
        "Governance, Public Policy/Welfare schemes, Social Justice, International Relations (India & world, treaties, groupings), "
        "or follow-up questions continuing an active GS-II discussion.\n"
        "- PLATFORM: Questions about Polity Mentor features, notes schedule, daily drills, workspace, pricing, or support.\n"
        "- OUT_OF_SCOPE: Celebrities, athletes (e.g., MS Dhoni, Virat Kohli), movies, songs, recipes, coding tutorials, "
        "pure stock market/crypto tips, pure physics/chemistry/astronomy, pure ancient/medieval history, or general trivia.\n"
        'Return strictly valid JSON: {"scope": "GS2" | "PLATFORM" | "OUT_OF_SCOPE"}'
    )

    def _call_gate(client):
        try:
            return client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": gate_system},
                    {"role": "user", "content": f"{recent_context}User message: {query}"},
                ],
                response_format={"type": "json_object"},
                reasoning_effort="low",
                temperature=0.0,
                max_completion_tokens=1000,
            )
        except TypeError:
            return client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": gate_system},
                    {"role": "user", "content": f"{recent_context}User message: {query}"},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_completion_tokens=1000,
            )

    try:
        resp = groq_pool.execute_with_failover(_call_gate)
        raw = resp.choices[0].message.content or "{}"
        json_match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        parsed = json.loads(json_match.group(0) if json_match else raw)
        scope = str(parsed.get("scope", "OUT_OF_SCOPE")).upper().strip()
        return scope if scope in {"GS2", "PLATFORM", "OUT_OF_SCOPE"} else "OUT_OF_SCOPE"
    except Exception:
        return "OUT_OF_SCOPE"


# ------------------------------------------------------------------------------
# 5. Database-Backed Execution Tools (with Redis Caching Layer)
# ------------------------------------------------------------------------------
def resolve_platform_faq(topic: str) -> Dict[str, Any]:
    topic_clean = topic.strip().lower()
    for key, val in PLATFORM_MANIFEST.items():
        if key in topic_clean or topic_clean in key:
            return {"found": True, "topic": key, "answer": val}
    return {
        "found": True,
        "topic": "overview",
        "answer": (
            "Polity Mentor is an exam-focused UPSC CSE GS-II & Prelims platform offering "
            "daily newspaper synthesis (The Hindu & Indian Express), clause-by-clause bare act analyses, "
            "evolutionary issue dossiers, and 15-question daily practice drills. For direct support, email admin@politymentor.com."
        ),
    }


def fetch_constitutional_article(article_identifier: str, session: Session, r_cache=None) -> Dict[str, Any]:
    clean_id = article_identifier.strip()
    cache_key = f"agent:tool:v4:article:{clean_id.lower()}"
    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    normalized_slug = clean_id.lower().replace(" ", "-").replace("(", "-").replace(")", "")
    digits = re.findall(r"\d+[A-Za-z]?", clean_id)
    raw_num = digits[0].upper() if digits else clean_id

    stmt = select(ConstitutionalArticleModel).where(
        or_(
            ConstitutionalArticleModel.article_slug == normalized_slug,
            ConstitutionalArticleModel.article_number == clean_id,
            ConstitutionalArticleModel.article_number == raw_num,
            ConstitutionalArticleModel.title.ilike(f"%{clean_id}%"),
        )
    )
    article = session.execute(stmt).scalars().first()
    if not article:
        return {
            "found": False,
            "error": f"Article '{article_identifier}' was not found in the ConstitutionalArticleModel table.",
        }

    res = {
        "found": True,
        "source_table": "constitutional_articles",
        "article_number": article.article_number,
        "title": article.title,
        "part_number": article.part_number,
        "verbatim_text": article.verbatim_text,
        "clauses_analysis": article.bare_act_analysis if article.bare_act_analysis else [],
        "aspirant_summary": article.aspirant_summary,
    }

    if r_cache:
        try:
            r_cache.setex(cache_key, TOOL_CACHE_TTL, json.dumps(res))
        except Exception:
            pass

    return res


def fetch_issue_dossier(topic: str, session: Session, r_cache=None) -> Dict[str, Any]:
    """Queries thematic dossiers and safely resolves graph edges from Postgres."""
    clean_topic = topic.strip().lower()
    cache_key = f"agent:tool:v4:dossier:{clean_topic}"
    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    search_term = f"%{clean_topic}%"
    stmt = (
        select(IssueDossierModel)
        .where(
            or_(
                IssueDossierModel.title.ilike(search_term),
                IssueDossierModel.chapter_name.ilike(search_term),
                IssueDossierModel.issue_slug.ilike(search_term),
                IssueDossierModel.canonical_summary.ilike(search_term),
            )
        )
        .limit(2)
    )
    dossiers = session.execute(stmt).scalars().all()
    if not dossiers:
        return {"found": False, "message": f"No issue dossier found matching '{topic}'."}

    primary = dossiers[0]

    # Safely inspect IssueGraphEdgeModel columns so schema variations never raise AttributeError
    related = []
    try:
        src_col = getattr(IssueGraphEdgeModel, "source_slug", None) or getattr(IssueGraphEdgeModel, "from_slug", None)
        tgt_col = (
            getattr(IssueGraphEdgeModel, "target_slug", None)
            or getattr(IssueGraphEdgeModel, "target_issue_slug", None)
            or getattr(IssueGraphEdgeModel, "to_slug", None)
            or getattr(IssueGraphEdgeModel, "related_slug", None)
        )
        rel_col = getattr(IssueGraphEdgeModel, "relation_type", None) or getattr(IssueGraphEdgeModel, "edge_type", None)

        if src_col is not None and tgt_col is not None:
            cols = [tgt_col, rel_col] if rel_col is not None else [tgt_col]
            edges_stmt = select(*cols).where(src_col == primary.issue_slug).limit(5)
            edges = session.execute(edges_stmt).all()
            related = [
                {"slug": e[0], "relation": e[1] if len(e) > 1 else "related"}
                for e in edges
            ]
    except Exception:
        related = []

    res = {
        "found": True,
        "source_table": "issue_dossiers",
        "title": primary.title,
        "chapter": primary.chapter_name,
        "canonical_summary": primary.canonical_summary or "",
        "prelims_factsheet": primary.prelims_factsheet or {},
        "mains_framework": primary.mains_framework or {},
        "connected_topics": related,
    }

    if r_cache:
        try:
            r_cache.setex(cache_key, TOOL_CACHE_TTL, json.dumps(res))
        except Exception:
            pass

    return res


def _build_pyq_filter(clean_topic: str, aux_title: Optional[str] = None):
    """
    Builds a precision SQL filter for PrelimsPYQModel:
    - Uses Postgres word-boundary regex for 'Article X' so 'Article 14' never matches 'Article 141'.
    - Optionally matches the constitutional article's title (e.g. 'Equality before law').
    """
    clauses = []
    art_match = re.match(r"^(?:article|art\.?)\s*(\d+[a-z]?)$", clean_topic, flags=re.IGNORECASE)
    if art_match:
        num = re.escape(art_match.group(1))
        boundary_pattern = rf"\marticle\s+{num}\M"
        clauses.extend([
            PrelimsPYQModel.question_text.op("~*")(boundary_pattern),
            PrelimsPYQModel.explanation.op("~*")(boundary_pattern),
            PrelimsPYQModel.chapter_name.op("~*")(boundary_pattern),
        ])
    else:
        search_term = f"%{clean_topic}%"
        clauses.extend([
            PrelimsPYQModel.question_text.ilike(search_term),
            PrelimsPYQModel.chapter_name.ilike(search_term),
            PrelimsPYQModel.explanation.ilike(search_term),
        ])

    if aux_title and len(aux_title.strip()) >= 6:
        title_term = f"%{aux_title.strip()}%"
        clauses.extend([
            PrelimsPYQModel.question_text.ilike(title_term),
            PrelimsPYQModel.explanation.ilike(title_term),
        ])

    return or_(*clauses)


def fetch_relevant_pyq(
    topic: str,
    session: Session,
    include_verbatim: bool = False,
    aux_title: Optional[str] = None,
    r_cache=None,
) -> Dict[str, Any]:
    """
    Queries PrelimsPYQModel for exact frequency counts (total, by year, by chapter).
    Returns verbatim MCQ text ONLY when include_verbatim=True.
    """
    clean_topic = topic.strip().lower()
    aux_key = (aux_title or "").strip().lower()
    cache_key = f"agent:tool:v4:pyq:{clean_topic}:{aux_key}:verbatim={int(include_verbatim)}"
    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    filter_clause = _build_pyq_filter(clean_topic, aux_title=aux_title)

    total_count = session.execute(
        select(func.count(PrelimsPYQModel.id)).where(filter_clause)
    ).scalar() or 0

    if total_count == 0:
        return {
            "found": False,
            "total_pyq_count": 0,
            "search_topic": topic,
            "message": f"0 UPSC Prelims PYQs found in PrelimsPYQModel matching '{topic}'.",
        }

    year_rows = session.execute(
        select(PrelimsPYQModel.year, func.count(PrelimsPYQModel.id))
        .where(filter_clause)
        .group_by(PrelimsPYQModel.year)
        .order_by(PrelimsPYQModel.year.desc())
    ).all()
    year_breakdown = {str(yr): cnt for yr, cnt in year_rows if yr is not None}

    chapter_rows = session.execute(
        select(PrelimsPYQModel.chapter_name, func.count(PrelimsPYQModel.id))
        .where(filter_clause)
        .group_by(PrelimsPYQModel.chapter_name)
        .order_by(func.count(PrelimsPYQModel.id).desc())
        .limit(5)
    ).all()
    chapter_breakdown = {str(ch): cnt for ch, cnt in chapter_rows if ch}

    res: Dict[str, Any] = {
        "found": True,
        "source_table": "prelims_pyqs",
        "search_topic": topic,
        "matched_title": aux_title,
        "total_pyq_count": total_count,
        "year_wise_count": year_breakdown,
        "chapter_wise_count": chapter_breakdown,
    }

    if include_verbatim:
        pyqs = (
            session.execute(
                select(PrelimsPYQModel)
                .where(filter_clause)
                .order_by(PrelimsPYQModel.year.desc())
                .limit(2)
            )
            .scalars()
            .all()
        )
        res["verbatim_pyqs"] = [
            {
                "year": q.year,
                "question": q.question_text,
                "options": q.options,
                "correct_answer": q.correct_option,
                "chapter": q.chapter_name,
                "explanation": q.explanation or "",
            }
            for q in pyqs
        ]
    else:
        sample_explanations = (
            session.execute(
                select(PrelimsPYQModel.year, PrelimsPYQModel.chapter_name, PrelimsPYQModel.explanation)
                .where(filter_clause)
                .order_by(PrelimsPYQModel.year.desc())
                .limit(3)
            )
            .all()
        )
        res["tested_concepts_summary"] = [
            {"year": yr, "chapter": ch, "concept_tested": (exp or "")[:240]}
            for yr, ch, exp in sample_explanations
        ]

    if r_cache:
        try:
            r_cache.setex(cache_key, TOOL_CACHE_TTL, json.dumps(res))
        except Exception:
            pass

    return res


def fetch_practice_drill_mcq(topic: str, session: Session, include_verbatim: bool = False) -> Dict[str, Any]:
    """Retrieves drill statistics or a verbatim MCQ (only if include_verbatim=True)."""
    search_term = f"%{topic.strip()}%"
    filter_clause = or_(
        DailyChallengeQuestionModel.question_text.ilike(search_term),
        DailyChallengeQuestionModel.topic.ilike(search_term),
        DailyChallengeQuestionModel.explanation.ilike(search_term),
    )

    drill_count = session.execute(
        select(func.count(DailyChallengeQuestionModel.id)).where(filter_clause)
    ).scalar() or 0

    if not include_verbatim:
        return {
            "found": drill_count > 0,
            "source_table": "daily_challenge_questions",
            "matching_drill_mcqs_count": drill_count,
        }

    mcq = (
        session.execute(
            select(DailyChallengeQuestionModel).where(filter_clause).order_by(func.random()).limit(1)
        )
        .scalars()
        .first()
    )
    if not mcq:
        return {"found": False, "message": f"No drill questions found matching '{topic}'."}

    return {
        "found": True,
        "source_table": "daily_challenge_questions",
        "matching_drill_mcqs_count": drill_count,
        "question": mcq.question_text,
        "options": mcq.options,
        "correct_answer": mcq.correct_option,
        "explanation": mcq.explanation or "",
        "trap_concept": getattr(mcq, "trap_concept", ""),
    }


def fetch_daily_press_intelligence(
    keyword: Optional[str] = None,
    target_date: Optional[str] = None,
    r_cache=None,
) -> Dict[str, Any]:
    """Scans synthesized smart notes in R2/MinIO with Redis memoization."""
    cache_key = f"agent:tool:v4:press:{keyword or 'all'}:{target_date or 'latest'}"
    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    all_objects = storage.list_objects(prefix="daily_press/")
    note_keys = [k for k in all_objects if "/smart_notes/" in k and k.endswith(".json")]

    if not note_keys:
        return {"found": False, "total_matches": 0, "notes": [], "message": "No smart notes stored yet."}

    note_keys.sort(reverse=True)
    matched_notes = []
    kw_lower = keyword.strip().lower() if keyword and keyword != "null" else None

    if target_date and target_date != "null":
        filtered_keys = [k for k in note_keys if f"/{target_date}/" in k]
        search_keys = filtered_keys if filtered_keys else note_keys[:25]
    else:
        search_keys = note_keys[:40]

    for key in search_keys:
        note = storage.get_json(key)
        if not note:
            continue

        if kw_lower:
            text_corpus = (
                f"{note.get('headline', '')} {note.get('issue_framing', '')} "
                f"{note.get('syllabus_anchors', '')} {note.get('category', '')}"
            ).lower()
            if kw_lower not in text_corpus:
                continue

        matched_notes.append({
            "headline": note.get("headline"),
            "publication": note.get("publication"),
            "category": note.get("category"),
            "issue_framing": note.get("issue_framing"),
            "prelims_traps": note.get("prelims_traps", [])[:2],
            "landmark_cases": note.get("landmark_cases", [])[:2],
        })

        if len(matched_notes) >= 3:
            break

    res = {
        "found": len(matched_notes) > 0,
        "source_storage": "daily_press/smart_notes",
        "total_matches": len(matched_notes),
        "notes": matched_notes,
    }

    if r_cache:
        try:
            r_cache.setex(cache_key, 1800, json.dumps(res))
        except Exception:
            pass

    return res


def search_pib_releases(
    keyword: str,
    target_date: Optional[str] = None,
    r_cache=None,
) -> Dict[str, Any]:
    """Searches official PIB releases from R2/MinIO with Redis caching."""
    clean_kw = keyword.strip().lower()
    cache_key = f"agent:tool:v4:pib:{clean_kw}:{target_date or 'latest'}"
    if r_cache:
        try:
            cached = r_cache.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    query_prefix = f"pib/{target_date}/" if target_date else "pib/"
    pib_objects = storage.list_objects(prefix=query_prefix)

    pib_keys = sorted([k for k in pib_objects if k.endswith(".json")], reverse=True)
    matched_releases = []

    for key in pib_keys[:25]:
        data = storage.get_json(key)
        if not data:
            continue

        title = data.get("title", "") or data.get("headline", "")
        ministry = data.get("ministry", "")
        summary = data.get("summary", "") or data.get("content", "")

        corpus = f"{title} {ministry} {summary}".lower()
        if clean_kw in corpus:
            matched_releases.append({
                "title": title,
                "ministry": ministry,
                "summary": summary[:350] + "..." if len(summary) > 350 else summary,
                "key_facts": data.get("prelims_facts", [])[:3],
            })
            if len(matched_releases) >= 2:
                break

    res = (
        {"found": True, "source_storage": "pib", "pib_matches": matched_releases}
        if matched_releases
        else {"found": False, "message": f"No recent PIB releases found matching '{keyword}'."}
    )

    if r_cache:
        try:
            r_cache.setex(cache_key, 1800, json.dumps(res))
        except Exception:
            pass

    return res


# ------------------------------------------------------------------------------
# 6. Tool Declarations
# ------------------------------------------------------------------------------
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "resolve_platform_faq",
            "description": "Fetch operational info about Polity Mentor (timings, notes schedule, 15-MCQ drill, toggles, navigation, and support).",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "e.g. 'daily_notes_schedule', 'navigation_yesterday_notes', 'daily_challenge_drill', 'contact_support', 'subscriptions_and_pricing', 'articles_catalogue'",
                    }
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_constitutional_article",
            "description": "Retrieve verbatim statutory text, clause analysis, and summary from the ConstitutionalArticleModel table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "article_identifier": {
                        "type": "string",
                        "description": "e.g. 'Article 200', 'Article 14', 'Article 128', 'Article 356'",
                    }
                },
                "required": ["article_identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_issue_dossier",
            "description": "Retrieve thematic dossiers (Anti-Defection, Governor's Discretion, Basic Structure, Federalism, Electoral Reforms) with factsheets, Mains frameworks, and graph edges.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Polity syllabus theme or chapter title."}
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_relevant_pyq",
            "description": "Retrieve exact UPSC Prelims PYQ counts (total, year-wise, chapter-wise) and tested concepts from PrelimsPYQModel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Clean Article, chapter, or topic name, e.g. 'Article 14', 'Article 200', 'Preamble', 'Money Bill'.",
                    }
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_practice_drill_mcq",
            "description": "Retrieve matching practice MCQ count or a verbatim MCQ from DailyChallengeQuestionModel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Constitutional topic or keyword (e.g., 'Article 356', 'Pardoning Power', 'Governor').",
                    }
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_daily_press_intelligence",
            "description": "Search synthesized GS-II smart notes from The Hindu and Indian Express by keyword or date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": ["string", "null"],
                        "description": "Polity keyword or case name (e.g., 'Election Commission', 'Governor'). Pass null if searching by date only.",
                    },
                    "target_date": {
                        "type": ["string", "null"],
                        "description": "Date in YYYY-MM-DD format. Pass null if looking for latest notes.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_pib_releases",
            "description": "Search official Press Information Bureau releases for government schemes, cabinet decisions, and ministry notifications.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Government scheme, ministry name, or policy keyword.",
                    },
                    "target_date": {
                        "type": ["string", "null"],
                        "description": "Optional date in YYYY-MM-DD format. Pass null if not searching a specific date.",
                    },
                },
                "required": ["keyword"],
                "additionalProperties": False,
            },
        },
    },
]

SYSTEM_PROMPT = """You are the "Polity Mentor Concierge", operating exclusively as a UPSC CSE General Studies Paper-II (Indian Constitution, Polity, Governance, Social Justice, and International Relations) Specialist on politymentor.com.

STRICT DOMAIN & PRECISION CONSTITUTION:
1. GS-II EXCLUSIVITY: You ONLY answer questions within UPSC CSE GS-II and Polity Mentor platform usage. Never answer queries about sports, celebrities, entertainment, general trivia, or unrelated subjects.
2. DATABASE-FIRST GROUNDING WITH VERIFIED CONSTITUTIONAL FALLBACK:
   - Whenever database records are returned, treat them as your primary source of truth.
   - If a valid GS-II Polity/Governance/IR question has no pre-stored record in our database yet, answer it completely, clearly, and in an intuitive layman-friendly yet legally rigorous manner using verified Indian Constitutional law, Bare Act provisions, established Supreme Court doctrines, and standard UPSC Polity/Governance jurisprudence.
   - NEVER fabricate fake database PYQ counts, fake news headlines, or unverified case citations. If PYQ count in the database is 0, state clearly that 0 matching PYQs are currently indexed in our database for that exact query while still explaining the conceptual Prelims traps thoroughly.
3. NO UNREQUESTED VERBATIM MCQs: NEVER output verbatim MCQ question stems or A/B/C/D options unless the user explicitly asked for a verbatim question or practice MCQ. By default, report ONLY the exact PYQ count from the database (if > 0) and the conceptual traps tested.

CRITICAL FORMATTING INSTRUCTIONS (STRICT PLAIN TEXT ONLY):
- DO NOT use any Markdown formatting syntax under any circumstances.
- ABSOLUTELY NO ASTERISKS: No **bold**, no *italics*, and no lone asterisks.
- DO NOT use hash headers (no #, ##, or ###).
- DO NOT use markdown tables or raw HTML tags.
- For emphasis, use UPPERCASE WORDS (e.g., PRIOR PRESIDENTIAL CONSENT, NOT BINDING, CONSULTATIVE ONLY, EXCEPTION).
- Use Unicode bullet points ("• ") for itemized lists.
- Separate all paragraphs and sections with double line breaks for clean mobile rendering.
"""


# ------------------------------------------------------------------------------
# 7. Grounded Two-Step Autonomous Agent Execution
# ------------------------------------------------------------------------------
@router.post("/chat", response_model=ChatResponse)
def handle_agent_chat(
    request: ChatRequest,
    db_session: Session = Depends(get_db),
    r_cache=Depends(get_redis_cache),
):
    if is_greeting_only(request.message):
        return ChatResponse(
            status="success",
            response=(
                "WELCOME TO POLITY MENTOR CONCIERGE\n\n"
                "Ask me any UPSC CSE GS-II question on Constitutional Articles, Supreme Court doctrines, "
                "Governance frameworks, International Relations, or daily current affairs synthesized from our database."
            ),
            tools_used=[],
        )

    cleaned_history: List[Dict[str, str]] = []
    valid_roles = {"user", "assistant", "system"}
    for msg in request.history[-6:]:
        if msg.role == "user" and msg.content.strip() == request.message.strip():
            continue
        if msg.role in valid_roles and msg.content.strip():
            cleaned_history.append({"role": msg.role, "content": msg.content})

    try:
        # ------------------------------------------------------------------
        # Gate 0: Strict UPSC GS-II Scope Enforcement
        # ------------------------------------------------------------------
        scope = classify_gs2_scope(request.message, request.history)
        if scope == "OUT_OF_SCOPE":
            return ChatResponse(
                status="success",
                response=clean_plain_text(OUT_OF_SCOPE_RESPONSE),
                tools_used=["gs2_scope_gatekeeper"],
            )

        include_verbatim_mcq = wants_verbatim_mcq(request.message)
        deep_explain_mode = is_deep_explanation_request(request.message, scope, request.history)

        # ------------------------------------------------------------------
        # Step 1: Mandatory Database Tool Routing
        # ------------------------------------------------------------------
        messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(cleaned_history)

        routing_directive = (
            "[SYSTEM DIRECTIVE: Call ALL relevant database tools to ground this GS-II explanation "
            "(fetch_constitutional_article, fetch_issue_dossier, fetch_daily_press_intelligence, AND fetch_relevant_pyq). "
            "Pass only the clean entity/article/topic name as tool arguments.]"
            if deep_explain_mode
            else "[SYSTEM DIRECTIVE: Call the specific database/platform tool(s) needed to check our records for this query. "
                 "Pass only the clean entity/article/topic name as tool arguments.]"
        )

        messages.append({
            "role": "user",
            "content": f"{request.message}\n\n{routing_directive}",
        })

        def _call_groq_tools(client):
            return client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice="required",
                temperature=0.05,
                max_completion_tokens=3000,
            )

        response = groq_pool.execute_with_failover(_call_groq_tools)
        response_message = response.choices[0].message

        tool_calls = response_message.tool_calls or []
        tools_used: List[str] = []
        tool_results_summary: List[str] = []
        any_db_hit = False

        # ------------------------------------------------------------------
        # Step 2: Execute Triggered Database & Storage Tools First
        # ------------------------------------------------------------------
        extracted_topic = extract_search_topic(request.message)
        matched_article_title: Optional[str] = None
        called_names = set()

        for tool_call in tool_calls:
            t_name = tool_call.function.name
            t_args = json.loads(tool_call.function.arguments or "{}")
            called_names.add(t_name)
            tools_used.append(t_name)

            if t_args.get("article_identifier"):
                extracted_topic = t_args["article_identifier"].strip()
            elif t_args.get("topic") and t_name in {"fetch_issue_dossier", "fetch_relevant_pyq"}:
                extracted_topic = t_args["topic"].strip()

            if t_name == "resolve_platform_faq":
                res = resolve_platform_faq(topic=t_args.get("topic", ""))
            elif t_name == "fetch_constitutional_article":
                res = fetch_constitutional_article(
                    article_identifier=t_args.get("article_identifier", ""),
                    session=db_session,
                    r_cache=r_cache,
                )
                if res.get("found") and res.get("title"):
                    matched_article_title = res["title"]
            elif t_name == "fetch_issue_dossier":
                res = fetch_issue_dossier(
                    topic=t_args.get("topic", ""),
                    session=db_session,
                    r_cache=r_cache,
                )
            elif t_name == "fetch_relevant_pyq":
                res = fetch_relevant_pyq(
                    topic=t_args.get("topic", "") or extracted_topic,
                    session=db_session,
                    include_verbatim=include_verbatim_mcq,
                    aux_title=matched_article_title,
                    r_cache=r_cache,
                )
            elif t_name == "fetch_practice_drill_mcq":
                res = fetch_practice_drill_mcq(
                    topic=t_args.get("topic", "") or extracted_topic,
                    session=db_session,
                    include_verbatim=include_verbatim_mcq,
                )
            elif t_name == "fetch_daily_press_intelligence":
                kw = t_args.get("keyword")
                t_date = t_args.get("target_date")
                res = fetch_daily_press_intelligence(
                    keyword=kw if kw and kw != "null" else None,
                    target_date=t_date if t_date and t_date != "null" else None,
                    r_cache=r_cache,
                )
            elif t_name == "search_pib_releases":
                kw = t_args.get("keyword", "")
                t_date = t_args.get("target_date")
                res = search_pib_releases(
                    keyword=kw or "",
                    target_date=t_date if t_date and t_date != "null" else None,
                    r_cache=r_cache,
                )
            else:
                query_val = list(t_args.values())[0] if t_args else extracted_topic
                res = fetch_issue_dossier(topic=str(query_val), session=db_session, r_cache=r_cache)

            if isinstance(res, dict) and res.get("found"):
                any_db_hit = True

            tool_results_summary.append(f"Data from {t_name}:\n{json.dumps(res, ensure_ascii=False)}")

        # Guarantee fetch_relevant_pyq runs with CLEAN extracted_topic in Deep Explanation Mode
        if deep_explain_mode and "fetch_relevant_pyq" not in called_names:
            pyq_res = fetch_relevant_pyq(
                topic=extracted_topic,
                session=db_session,
                include_verbatim=include_verbatim_mcq,
                aux_title=matched_article_title,
                r_cache=r_cache,
            )
            tools_used.append("fetch_relevant_pyq")
            if pyq_res.get("found"):
                any_db_hit = True
            tool_results_summary.append(
                f"Data from fetch_relevant_pyq:\n{json.dumps(pyq_res, ensure_ascii=False)}"
            )

        # ------------------------------------------------------------------
        # Step 3: Grounding Mode Context (DB Hit vs. Verified Constitutional Fallback)
        # ------------------------------------------------------------------
        if not any_db_hit:
            tools_used.append("verified_constitutional_knowledge_fallback")
            grounding_context_directive = (
                "KNOWLEDGE SOURCE MODE: VERIFIED CONSTITUTIONAL & POLITY KNOWLEDGE FALLBACK\n"
                "Our database tables currently do not contain a pre-stored record for this specific GS-II query. "
                "Because Gate 0 confirmed this is a valid Indian Polity / GS-II question, answer it completely, clearly, "
                "and in a layman-friendly yet legally accurate manner using authoritative Indian Constitutional law, "
                "Bare Act provisions, established Supreme Court doctrines, and standard UPSC Polity/Governance jurisprudence.\n"
                "CRITICAL: Do NOT invent fake database PYQ counts. State transparently that 0 matching PYQs are currently "
                "indexed in our database for this exact search term, and focus on the conceptual Prelims traps."
            )
        else:
            grounding_context_directive = (
                "KNOWLEDGE SOURCE MODE: DATABASE-GROUNDED SYNTHESIS\n"
                "Anchor your explanation directly in the Retrieved Database Records above, supplemented where helpful "
                "by authoritative Indian Constitutional jurisprudence for clarity without contradicting or fabricating database figures."
            )

        # ------------------------------------------------------------------
        # Step 4: Conditional Synthesis (Deep Pedagogical Flow ONLY for Explanations)
        # ------------------------------------------------------------------
        synthesis_messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if cleaned_history:
            synthesis_messages.extend(cleaned_history)

        verbatim_rule = (
            "The user EXPLICITLY requested a verbatim MCQ. If a verbatim PYQ or drill MCQ was retrieved in the database payload, "
            "include the question stem, options A, B, C, D, correct answer, and explanation. If none exists in the database, state that transparently."
            if include_verbatim_mcq
            else "DO NOT output any verbatim MCQ question text or A/B/C/D options. Report ONLY the exact PYQ counts "
                 "from the database payload (total count, year-wise distribution, and chapter-wise breakdown) and tested conceptual traps."
        )

        if deep_explain_mode:
            optional_verbatim_section = (
                "\n\n📝 VERBATIM PYQ / PRACTICE DRILL (EXPLICITLY REQUESTED):\n"
                "Present the retrieved verbatim question stem, options A, B, C, D, correct answer, and full elimination logic (or note if 0 verbatim MCQs are indexed)."
                if include_verbatim_mcq
                else ""
            )

            synthesis_instruction = (
                f"Retrieved Database Records:\n"
                f"{chr(10).join(tool_results_summary)}\n\n"
                f"{grounding_context_directive}\n\n"
                f"Aspirant's GS-II Explanation Query:\n"
                f"\"{request.message}\"\n\n"
                f"EXHAUSTIVE PEDAGOGICAL & PRECISION INSTRUCTIONS:\n"
                f"1. Deliver a complete, crystal-clear, masterclass-level breakdown that starts from intuitive layman understanding "
                f"and builds up to granular constitutional clauses, provisos, exceptions, judicial evolution, and Prelims traps.\n"
                f"2. {verbatim_rule}\n"
                f"3. Strictly plain text only: NO asterisks (* or **), NO markdown #, NO tables. Use UPPERCASE for emphasis and '• ' for structured bullets.\n\n"
                f"Organize your response strictly into these sequential sections separated by double line breaks:\n\n"
                f"💡 LAYMAN INTUITION & CORE PURPOSE:\n"
                f"Explain the concept in simple, everyday language first—why the framers created this provision, what problem it solves, and a concrete real-world governance example.\n\n"
                f"📜 CONSTITUTIONAL & STATUTORY ARCHITECTURE (CLAUSE-BY-CLAUSE DETAIL):\n"
                f"Break down the exact Article/Act provisions, operative clauses, mandatory conditions, exceptions, provisos, and key constitutional amendments in full detail.\n\n"
                f"⚖️ INSTITUTIONAL FRICTION, JUDICIAL EVOLUTION & PRELIMS TRAPS:\n"
                f"Analyze landmark Supreme Court interpretations, Executive-Legislature or Centre-State friction, relevant governance linkages, and subtle Prelims elimination traps.\n\n"
                f"📊 UPSC PRELIMS PYQ TREND & FREQUENCY:\n"
                f"Report the exact PYQ count from our database payload (total count, year-wise and chapter-wise breakdown if > 0, or note 0 indexed PYQs if none matched) along with the conceptual angles UPSC tests."
                f"{optional_verbatim_section}"
            )
            max_tokens = 6500
        else:
            synthesis_instruction = (
                f"Retrieved Database Records:\n"
                f"{chr(10).join(tool_results_summary)}\n\n"
                f"{grounding_context_directive}\n\n"
                f"User's Query:\n"
                f"\"{request.message}\"\n\n"
                f"STRICT DIRECT-ANSWER INSTRUCTIONS:\n"
                f"1. Answer the user's exact question directly in your very first sentence in a complete, clear, layman-accessible yet legally precise manner.\n"
                f"2. DO NOT use the 4-section deep explanation template (no Layman Intuition / Constitutional Architecture headers) because this is a targeted follow-up, platform FAQ, news lookup, or point query.\n"
                f"3. {verbatim_rule}\n"
                f"4. Strictly plain text only: NO asterisks (* or **), NO markdown #, NO tables. Use '• ' for bullets and double line breaks between paragraphs."
            )
            max_tokens = 4000

        synthesis_messages.append({"role": "user", "content": synthesis_instruction})

        def _call_groq_synthesis(client):
            return client.chat.completions.create(
                model=MODEL_NAME,
                messages=synthesis_messages,
                temperature=0.1,
                max_completion_tokens=max_tokens,
            )

        final_resp = groq_pool.execute_with_failover(_call_groq_synthesis)
        raw_text = final_resp.choices[0].message.content or ""
        clean_text = clean_plain_text(raw_text)

        return ChatResponse(
            status="success",
            response=clean_text if clean_text else "Analysis completed.",
            tools_used=tools_used,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent reasoning error: {str(e)}",
        )