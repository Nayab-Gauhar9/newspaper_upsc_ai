import json
import os
import re
from datetime import datetime, timedelta, timezone
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
    DailyChallengeQuestionModel
)
from src.storage.minio_client import NewspaperStorage

router = APIRouter(prefix="/api/v1/agent", tags=["AI Constitutional & Platform Concierge"])

IST = timezone(timedelta(hours=5, minutes=30))
storage = NewspaperStorage()

MODEL_NAME = "openai/gpt-oss-120b"

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
    # Strip markdown headers (e.g. ### Header -> Header)
    cleaned = re.sub(r'^[ \t]*#{1,6}\s*', '', text, flags=re.MULTILINE)
    # Strip bold markdown (**text** or __text__)
    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'__(.*?)__', r'\1', cleaned, flags=re.DOTALL)
    # Strip italic markdown (*text* or _text_)
    cleaned = re.sub(r'\*(.*?)\*', r'\1', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'(?<!\w)_(.*?)_(?!\w)', r'\1', cleaned, flags=re.DOTALL)
    # Strip stray asterisks, backticks, and tildes
    cleaned = cleaned.replace("**", "").replace("*", "").replace("`", "")
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
    )
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
# 4. Execution Tools
# ------------------------------------------------------------------------------
def resolve_platform_faq(topic: str) -> str:
    topic_clean = topic.strip().lower()
    for key, val in PLATFORM_MANIFEST.items():
        if key in topic_clean or topic_clean in key:
            return val
    return (
        "Polity Mentor is an exam-focused UPSC CSE GS-II & Prelims platform offering "
        "daily newspaper synthesis (The Hindu & Indian Express), clause-by-clause bare act analyses, "
        "and 15-question daily practice drills. For direct support, email support@politymentor.com."
    )

def fetch_constitutional_article(article_identifier: str, session: Session) -> Dict[str, Any]:
    clean_id = article_identifier.strip()
    normalized_slug = clean_id.lower().replace(" ", "-").replace("(", "-").replace(")", "")
    digits = re.findall(r"\d+", clean_id)
    raw_num = digits[0] if digits else clean_id

    stmt = select(ConstitutionalArticleModel).where(
        or_(
            ConstitutionalArticleModel.article_slug == normalized_slug,
            ConstitutionalArticleModel.article_number == clean_id,
            ConstitutionalArticleModel.article_number == raw_num,
            ConstitutionalArticleModel.title.ilike(f"%{clean_id}%")
        )
    )
    article = session.execute(stmt).scalars().first()
    if not article:
        return {"error": f"Article '{article_identifier}' not found in the constitutional database."}

    return {
        "article_number": article.article_number,
        "title": article.title,
        "part_number": article.part_number,
        "verbatim_text": article.verbatim_text,
        "clauses_analysis": article.bare_act_analysis[:3] if article.bare_act_analysis else [],
        "aspirant_summary": article.aspirant_summary,
    }

def fetch_issue_dossier(topic: str, session: Session) -> Dict[str, Any]:
    """Queries thematic dossiers matching chapter_name, title, or issue_slug, including connected graph edges."""
    search_term = f"%{topic.strip()}%"
    stmt = (
        select(IssueDossierModel)
        .where(
            or_(
                IssueDossierModel.title.ilike(search_term),
                IssueDossierModel.chapter_name.ilike(search_term),
                IssueDossierModel.issue_slug.ilike(search_term),
            )
        )
        .limit(1)
    )
    dossier = session.execute(stmt).scalars().first()
    if not dossier:
        return {"message": f"No dossier found directly matching '{topic}'."}

    edges_stmt = (
        select(IssueGraphEdgeModel.target_slug, IssueGraphEdgeModel.relation_type)
        .where(IssueGraphEdgeModel.source_slug == dossier.issue_slug)
        .limit(4)
    )
    edges = session.execute(edges_stmt).all()
    related = [{"slug": e[0], "relation": e[1]} for e in edges]

    return {
        "title": dossier.title,
        "chapter": dossier.chapter_name,
        "canonical_summary": dossier.canonical_summary or "",
        "prelims_factsheet": dossier.prelims_factsheet or {},
        "mains_framework": dossier.mains_framework or {},
        "connected_topics": related
    }

def fetch_relevant_pyq(topic: str, session: Session) -> Dict[str, Any]:
    """Queries authentic UPSC Prelims Previous Year Questions (1996 - 2026)."""
    search_term = f"%{topic.strip()}%"
    stmt = (
        select(PrelimsPYQModel)
        .where(
            or_(
                PrelimsPYQModel.question_text.ilike(search_term),
                PrelimsPYQModel.chapter_name.ilike(search_term),
                PrelimsPYQModel.explanation.ilike(search_term),
            )
        )
        .order_by(PrelimsPYQModel.year.desc())
        .limit(2)
    )
    pyqs = session.execute(stmt).scalars().all()
    if not pyqs:
        return {"message": f"No official PYQs found matching '{topic}'."}

    return {
        "pyqs": [
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
    }

def fetch_practice_drill_mcq(topic: str, session: Session) -> Dict[str, Any]:
    """Retrieves a high-yield practice MCQ from the preserved daily challenge drills."""
    search_term = f"%{topic.strip()}%"
    stmt = (
        select(DailyChallengeQuestionModel)
        .where(
            or_(
                DailyChallengeQuestionModel.question_text.ilike(search_term),
                DailyChallengeQuestionModel.topic.ilike(search_term),
                DailyChallengeQuestionModel.explanation.ilike(search_term)
            )
        )
        .order_by(func.random())
        .limit(1)
    )
    mcq = session.execute(stmt).scalars().first()

    if not mcq:
        fallback_stmt = select(DailyChallengeQuestionModel).order_by(func.random()).limit(1)
        mcq = session.execute(fallback_stmt).scalars().first()

    if not mcq:
        return {"message": "No drill questions available."}

    return {
        "question": mcq.question_text,
        "options": mcq.options,
        "correct_answer": mcq.correct_option,
        "explanation": mcq.explanation or "",
        "trap_concept": getattr(mcq, "trap_concept", "")
    }

def fetch_daily_press_intelligence(keyword: Optional[str] = None, target_date: Optional[str] = None) -> Dict[str, Any]:
    """Scans synthesized smart notes in MinIO."""
    all_objects = storage.list_objects(prefix="daily_press/")
    note_keys = [k for k in all_objects if "/smart_notes/" in k and k.endswith(".json")]

    if not note_keys:
        return {"total_matches": 0, "notes": [], "message": "No smart notes stored yet."}

    note_keys.sort(reverse=True)
    matched_notes = []
    kw_lower = keyword.strip().lower() if keyword and keyword != "null" else None

    if target_date and target_date != "null":
        filtered_keys = [k for k in note_keys if f"/{target_date}/" in k]
        search_keys = filtered_keys if filtered_keys else note_keys[:25]
    else:
        search_keys = note_keys[:35]

    for key in search_keys:
        note = storage.get_json(key)
        if not note:
            continue

        if kw_lower:
            text_corpus = f"{note.get('headline', '')} {note.get('issue_framing', '')} {note.get('syllabus_anchors', '')} {note.get('category', '')}".lower()
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

    return {
        "total_matches": len(matched_notes),
        "notes": matched_notes
    }

def search_pib_releases(keyword: str, target_date: Optional[str] = None) -> Dict[str, Any]:
    """Searches official Press Information Bureau (PIB) releases from MinIO."""
    query_prefix = f"pib/{target_date}/" if target_date else "pib/"
    pib_objects = storage.list_objects(prefix=query_prefix)
    
    pib_keys = sorted([k for k in pib_objects if k.endswith(".json")], reverse=True)
    kw_lower = keyword.strip().lower()
    matched_releases = []

    for key in pib_keys[:20]:
        data = storage.get_json(key)
        if not data:
            continue

        title = data.get("title", "") or data.get("headline", "")
        ministry = data.get("ministry", "")
        summary = data.get("summary", "") or data.get("content", "")

        corpus = f"{title} {ministry} {summary}".lower()
        if kw_lower in corpus:
            matched_releases.append({
                "title": title,
                "ministry": ministry,
                "summary": summary[:300] + "..." if len(summary) > 300 else summary,
                "key_facts": data.get("prelims_facts", [])[:3]
            })
            if len(matched_releases) >= 2:
                break

    if not matched_releases:
        return {"message": f"No recent PIB releases found matching '{keyword}'."}

    return {"pib_matches": matched_releases}


# ------------------------------------------------------------------------------
# 5. Tool Declarations
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
            "description": "Retrieve verbatim statutory text, clause analysis, and Prelims traps from the Indian Constitution database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "article_identifier": {"type": "string", "description": "e.g. 'Article 200', 'Article 13', 'Article 356'"}
                },
                "required": ["article_identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_issue_dossier",
            "description": "Retrieve comprehensive thematic dossiers (Anti-Defection, Governor's Discretion, Basic Structure, Federalism, Electoral Reforms) with committee reports, case laws, and related graph edges.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Polity syllabus theme or chapter title."}
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_relevant_pyq",
            "description": "Retrieve authentic UPSC Prelims Previous Year Questions (1996-2026) with options and explanations for a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Article or topic, e.g. 'Article 200', 'Preamble', 'Money Bill', 'Article 356'."}
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_practice_drill_mcq",
            "description": "Fetch a high-yield practice MCQ from preserved 15-question daily challenge drills matching the concept.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Constitutional topic or keyword (e.g., 'Article 356', 'Pardoning Power', 'Governor', 'Money Bill')."
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
            "description": "Search synthesized smart notes from The Hindu and Indian Express by keyword or date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": ["string", "null"],
                        "description": "Polity keyword or case name (e.g., 'Election Commission', 'Governor'). Pass null or empty string if searching by date only."
                    },
                    "target_date": {
                        "type": ["string", "null"],
                        "description": "Date in YYYY-MM-DD format. Pass null if looking for the latest notes."
                    }
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
                        "description": "Government scheme, ministry name, or policy keyword."
                    },
                    "target_date": {
                        "type": ["string", "null"],
                        "description": "Optional date in YYYY-MM-DD format. Pass null if not searching a specific date."
                    }
                },
                "required": ["keyword"],
                "additionalProperties": False,
            }
        }
    }
]

SYSTEM_PROMPT = """You are the "Polity Mentor Concierge", operating with the dual intellect of a PhD Constitutional Jurist and a veteran UPSC CSE GS-II Mentor on politymentor.com.

PEDAGOGICAL & INTELLECTUAL PERSONA:
- You synthesize constitutional design from first principles rather than merely repeating raw database text.
- Ground all explanations in institutional friction, statutory architecture, and landmark judicial doctrines.

CONVERSATION MODES & ADAPTABILITY:
1. CONVERSATIONAL FOLLOW-UP MODE:
   - When the user asks a follow-up question (e.g., "is this article important for prelims?", "what about money bills?", "explain the critique", "can you clarify?"):
     * Directly address the specific question in your first sentence.
     * DO NOT repeat the entire multi-section scaffold or restart the topic from scratch.
     * Maintain the context established in earlier messages.
     * Provide a sharp, targeted 2-3 paragraph answer citing relevant past trends, cases, or statutory exceptions.
2. COMPREHENSIVE OVERVIEW MODE:
   - Trigger ONLY when a new constitutional article, case, or broad syllabus theme is first introduced without prior immediate context.
   - In this mode, structure your output into clear uppercase titles with emojis.

CRITICAL FORMATTING INSTRUCTIONS (STRICT PLAIN TEXT ONLY):
- DO NOT use any Markdown formatting syntax under any circumstances.
- ABSOLUTELY NO ASTERISKS: No **bold**, no *italics*, and no lone asterisks.
- DO NOT use hash headers (no #, ##, or ###).
- DO NOT use markdown tables or raw HTML tags.
- For emphasis, use UPPERCASE WORDS (e.g. THE CORRECT ANSWER IS B, NOT permissible, AS SOON AS POSSIBLE).
- Use Unicode bullet points ("• ") for itemized lists.
- Separate all paragraphs and sections with double line breaks for clean mobile rendering.

HALLUCINATION PREVENTION:
- Ground all legal rules, case citations, and articles in established constitutional law and retrieved database records.
- Never fabricate landmark case names or committee reports.
"""

def is_follow_up_query(query: str, history: List[ChatMessage]) -> bool:
    """
    Determines whether the incoming user message is a conversational follow-up
    rather than a brand-new broad topic request.
    """
    if not history:
        return False

    q_lower = query.strip().lower()

    # Short query or demonstrative pronoun referring to earlier turns
    pronoun_markers = ["this", "that", "these", "it", "they", "here", "above"]
    has_pronoun = any(re.search(rf"\b{p}\b", q_lower) for p in pronoun_markers)

    follow_up_stems = [
        "is this", "is that", "important for prelims", "what about",
        "why is", "can you explain", "tell me more", "how does this",
        "what if", "difference between", "critique", "which option",
        "clarify", "correct answer", "solve this", "yes", "no"
    ]
    has_stem = any(stem in q_lower for stem in follow_up_stems)

    # If it refers to previous context and doesn't explicitly declare a new article code
    explicit_new_article = bool(re.search(r"\barticle\s+\d+", q_lower) and not has_pronoun)

    if explicit_new_article:
        return False

    return has_stem or has_pronoun or len(q_lower.split()) <= 8


# ------------------------------------------------------------------------------
# 6. Two-Step Autonomous Agent Execution
# ------------------------------------------------------------------------------
@router.post("/chat", response_model=ChatResponse)
def handle_agent_chat(request: ChatRequest, db_session: Session = Depends(get_db)):
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Prevent duplicate identical user queries from client history
    valid_roles = {"user", "assistant", "system"}
    cleaned_history: List[Dict[str, str]] = []
    for msg in request.history[-6:]:
        if msg.role == "user" and msg.content.strip() == request.message.strip():
            continue
        if msg.role in valid_roles and msg.content.strip():
            cleaned_history.append({"role": msg.role, "content": msg.content})
            messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": request.message})

    tools_used: List[str] = []

    try:
        # Step 1: Tool Selection Call
        def _call_groq_tools(client):
            return client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice="auto",
                temperature=0.2,
                max_completion_tokens=2000,
            )

        response = groq_pool.execute_with_failover(_call_groq_tools)
        choice = response.choices[0]
        response_message = choice.message

        # If the model answered directly without tool calls
        if not response_message.tool_calls:
            raw_ans = response_message.content or ""
            return ChatResponse(
                status="success",
                response=clean_plain_text(raw_ans),
                tools_used=[]
            )

        # Step 2: Execute triggered tools across database
        tool_results_summary: List[str] = []

        for tool_call in response_message.tool_calls:
            t_name = tool_call.function.name
            t_args = json.loads(tool_call.function.arguments or "{}")
            tools_used.append(t_name)

            if t_name == "resolve_platform_faq":
                res = resolve_platform_faq(topic=t_args.get("topic", ""))
            elif t_name == "fetch_constitutional_article":
                res = fetch_constitutional_article(
                    article_identifier=t_args.get("article_identifier", ""),
                    session=db_session
                )
            elif t_name == "fetch_issue_dossier":
                res = fetch_issue_dossier(
                    topic=t_args.get("topic", ""),
                    session=db_session
                )
            elif t_name == "fetch_relevant_pyq":
                res = fetch_relevant_pyq(
                    topic=t_args.get("topic", ""),
                    session=db_session
                )
            elif t_name == "fetch_practice_drill_mcq":
                res = fetch_practice_drill_mcq(
                    topic=t_args.get("topic", ""),
                    session=db_session
                )
            elif t_name == "fetch_daily_press_intelligence":
                kw = t_args.get("keyword")
                t_date = t_args.get("target_date")
                res = fetch_daily_press_intelligence(
                    keyword=kw if kw and kw != "null" else None,
                    target_date=t_date if t_date and t_date != "null" else None
                )
            elif t_name == "search_pib_releases":
                kw = t_args.get("keyword", "")
                t_date = t_args.get("target_date")
                res = search_pib_releases(
                    keyword=kw or "",
                    target_date=t_date if t_date and t_date != "null" else None
                )
            else:
                query_val = list(t_args.values())[0] if t_args else request.message
                res = fetch_issue_dossier(topic=str(query_val), session=db_session)

            tool_results_summary.append(f"Data from {t_name}:\n{json.dumps(res, ensure_ascii=False)}")

        # Check if this query is a conversational follow-up
        is_follow_up = is_follow_up_query(request.message, request.history)

        # Build synthesis messages preserving context
        synthesis_messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Inject conversation history so follow-ups retain context
        if cleaned_history:
            synthesis_messages.extend(cleaned_history)

        if is_follow_up:
            # Contextual follow-up prompt: Direct answer, no rigid template
            synthesis_instruction = (
                f"Retrieved Database Intelligence:\n"
                f"{chr(10).join(tool_results_summary)}\n\n"
                f"User's Specific Follow-up:\n"
                f"\"{request.message}\"\n\n"
                f"Instruction:\n"
                f"Answer the user's specific question directly in your opening sentence. "
                f"Do NOT regenerate the entire 6-part scaffold or repeat the introductory background. "
                f"Ground your answer in the preceding context and retrieved data. "
                f"Provide a clear, high-yield analysis (2-3 paragraphs) highlighting Prelims/Mains relevance, "
                f"statutory clauses, or historical trends as requested. "
                f"Strictly use plain text only: absolutely NO asterisks for bolding (* or **), NO markdown headers, NO tables."
            )
        else:
            # Comprehensive query: Full structured jurist breakdown
            synthesis_instruction = (
                f"Retrieved Database Intelligence:\n"
                f"{chr(10).join(tool_results_summary)}\n\n"
                f"Aspirant's Query:\n"
                f"\"{request.message}\"\n\n"
                f"Instruction:\n"
                f"Synthesize this topic with the depth of a PhD constitutional jurist and the clarity of a top-tier UPSC mentor. "
                f"Use plain text only: absolutely NO asterisks (* or **), NO markdown #, NO tables.\n\n"
                f"Structure your response strictly into these uppercase sections:\n\n"
                f"🧠 FIRST-PRINCIPLES INTELLECT & THE CORE FRICTION:\n"
                f"Frame how a constitutional scholar views this topic and deconstruct the institutional friction.\n\n"
                f"💡 THE LAYMAN INTUITION:\n"
                f"Break down the concept using an intuitive, real-world metaphor or plain-English logic.\n\n"
                f"📜 CONSTITUTIONAL PROVISION & CLAUSES:\n"
                f"Detail the statutory language, key clauses, and constitutional baseline.\n\n"
                f"⚖️ JUDICIAL DOCTRINES & LIVING DOSSIER:\n"
                f"Unpack landmark Supreme Court evolution, tests, and committee recommendations.\n\n"
                f"🎯 PRELIMS TRAPS & COMMISSIONS:\n"
                f"Pinpoint subtle traps UPSC uses to confuse aspirants.\n\n"
                f"📝 OFFICIAL UPSC PRELIMS PYQ:\n"
                f"If retrieved, provide the year, question text, and key trap explanation.\n\n"
                f"💡 PRACTICE DRILL QUESTION:\n"
                f"If retrieved, present 1 practice question with options A, B, C, D from the daily challenge archive for the aspirant to solve.\n\n"
                f"Ensure every section is separated by double line breaks."
            )

        synthesis_messages.append({"role": "user", "content": synthesis_instruction})

        def _call_groq_synthesis(client):
            return client.chat.completions.create(
                model=MODEL_NAME,
                messages=synthesis_messages,
                temperature=0.2,
                max_completion_tokens=5000,
            )

        final_resp = groq_pool.execute_with_failover(_call_groq_synthesis)
        raw_text = final_resp.choices[0].message.content or ""
        clean_text = clean_plain_text(raw_text)

        return ChatResponse(
            status="success",
            response=clean_text if clean_text else "Analysis completed.",
            tools_used=tools_used
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent reasoning error: {str(e)}"
        )