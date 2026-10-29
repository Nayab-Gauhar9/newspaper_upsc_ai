from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.classifiers.blueprint_taxonomy import PRELIMS_SYLLABUS_BLUEPRINT
from src.classifiers.taxonomy import LAXMIKANTH_8TH_EDITION
from src.database.models import PrelimsPYQModel
from src.database.session import get_db

router = APIRouter(prefix="/api/v1/blueprint", tags=["Syllabus Blueprint"])


# ---------------------------------------------------------------------------
# Pydantic Response Schemas
# ---------------------------------------------------------------------------

class PYQQuestionOut(BaseModel):
    id: int
    year: int
    question_number: int
    question_text: str
    options: dict
    correct_option: str
    chapter_number: int
    chapter_name: str
    mapped_articles: List[int]
    explanation: Optional[str] = None
    difficulty_level: Optional[str] = "Moderate"
    is_conceptual: bool = False

    class Config:
        from_attributes = True


class BlueprintChapterSummary(BaseModel):
    chapter_number: int
    chapter_name: str
    question_count: int


class PrelimsModuleCard(BaseModel):
    module_id: str
    module_number: int  # 1 to 10 for direct numeric routing in FlutterFlow
    title: str
    official_line: str
    total_questions: int
    weightage_percentage: float
    yield_tier: str
    subtopics: List[str]
    key_articles: List[int]
    chapters: List[BlueprintChapterSummary]
    # Ready-to-render display strings for FlutterFlow cards
    chapters_display: str  # e.g., "Ch 1–4 (4 Chapters)" or "Ch 7"
    articles_display: str  # e.g., "Art 14, Art 19, Art 21..."


class SyllabusKeywordDecode(BaseModel):
    keyword: str
    macro_picture: str
    micro_picture: List[str]
    core_focus_areas: str


class CompletePrelimsBlueprintOut(BaseModel):
    official_syllabus_raw: str
    syllabus_decoded: List[SyllabusKeywordDecode]
    modules: List[PrelimsModuleCard]


# ---------------------------------------------------------------------------
# Static Taxonomy: Word-by-Word Official Syllabus Decoded
# ---------------------------------------------------------------------------

OFFICIAL_PRELIMS_DECODED = [
    {
        "keyword": "Indian Polity",
        "macro_picture": "The constitutional machinery, federal equilibrium, and separation of powers among Organs of State.",
        "micro_picture": [
            "Parliamentary supremacy vs Judicial review interplay",
            "Ordinance-making limits (Art 123 & 213) and executive overreach",
            "Money Bill criteria and Speaker's certification powers (Art 110)",
        ],
        "core_focus_areas": "Parliament, Federalism, Basic Structure",
    },
    {
        "keyword": "Governance",
        "macro_picture": "Institutional independence, operational procedures, and accountability mechanisms of state bodies.",
        "micro_picture": [
            "Appointment, tenure, and removal protocols of Constitutional bodies",
            "Consolidated Fund charges vs Votable expenditures",
            "Statutory vs Executive commissions (CVC, CIC, NITI Aayog)",
        ],
        "core_focus_areas": "CAG, ECI, UPSC, Finance Commission, Tribunals",
    },
    {
        "keyword": "Constitution",
        "macro_picture": "Textual architecture, philosophical goals (Preamble), and the evolving Basic Structure doctrine.",
        "micro_picture": [
            "Scope and exceptions of Fundamental Rights (Art 14, 19, 21)",
            "Enforceability of DPSPs vs Fundamental Duties",
            "Amendment procedures under Article 368 vs Simple Majority",
        ],
        "core_focus_areas": "Part III, Part IV, Part IVA, Art 368",
    },
    {
        "keyword": "Political System",

        "macro_picture": "Electoral dynamics, legislative procedures, and parliamentary conventions in action.",
        "micro_picture": [
            "10th Schedule anti-defection rules and judicial review of Speaker",
            "Motions: No-Confidence, Censure, Adjournment, Calling Attention",
            "Representation of the People Acts (1950 & 1951) disqualifications",
        ],
        "core_focus_areas": "Elections, Anti-Defection, Parliamentary Motions",
    },
    {
        "keyword": "Panchayati Raj",
        "macro_picture": "Democratic decentralization and devolution of administrative and financial powers to local tiers.",
        "micro_picture": [
            "73rd & 74th Amendments: Compulsory vs Voluntary provisions",
            "State Election Commission (SEC) & State Finance Commission (SFC)",
            "PESA Act 1996: Sacred status and veto rights of the Gram Sabha",
        ],
        "core_focus_areas": "11th & 12th Schedules, Art 243A–243ZG, PESA",
    },
    {
        "keyword": "Public Policy",
        "macro_picture": "Rights-based social welfare statutory architecture and citizen empowerment mechanisms.",
        "micro_picture": [
            "Statutory entitlements: NFSA 2013, Forest Rights Act 2006, RTE 2009",
            "Affirmative action policies, sub-classification of reservations",
            "Public delivery monitoring mechanisms",
        ],
        "core_focus_areas": "Welfare legislation, Socio-economic rights",
    },
    {
        "keyword": "Rights Issues",
        "macro_picture": "Civil liberties, protection of vulnerable groups, and expanding frontiers of constitutional morality.",
        "micro_picture": [
            "Due Process of Law vs Procedure Established by Law",
            "Prerogative Writs (Habeas Corpus, Mandamus, Certiorari, Quo-Warranto)",
            "Statutory commissions for SC, ST, OBC, Women, and Minorities",
        ],
        "core_focus_areas": "Art 32 & 226, SC/ST Act, Privacy Rights",
    },
    {
        "keyword": "etc.",
        "macro_picture": "Dynamic current legal-constitutional controversies and evolving Supreme Court jurisprudence.",
        "micro_picture": [
            "Landmark Supreme Court Constitution Bench judgments",
            "Gubernatorial controversies (Art 200 assent / withholding)",
            "Digital data protection, free speech on platforms, election bonds",
        ],
        "core_focus_areas": "Recent PIB releases, Case laws, Commission reports",
    },
]


# ---------------------------------------------------------------------------
# Helper Calculation Function
# ---------------------------------------------------------------------------

def calculate_prelims_module_cards(db: Session) -> List[PrelimsModuleCard]:
    """Computes module cards, question totals, display strings, and yield weightage from database."""
    total_pyqs = db.execute(text("SELECT COUNT(*) FROM prelims_pyqs;")).scalar() or 1

    counts_query = text("""
        SELECT chapter_number, COUNT(*) AS count
        FROM prelims_pyqs
        GROUP BY chapter_number;
    """)
    chapter_counts = {row.chapter_number: row.count for row in db.execute(counts_query).all()}

    blueprint_cards = []

    for idx, mod in enumerate(PRELIMS_SYLLABUS_BLUEPRINT, start=1):
        chapters_data = []
        module_question_total = 0

        for ch_num in mod["chapter_range"]:
            q_count = chapter_counts.get(ch_num, 0)
            module_question_total += q_count
            chapters_data.append(
                BlueprintChapterSummary(
                    chapter_number=ch_num,
                    chapter_name=LAXMIKANTH_8TH_EDITION.get(ch_num, f"Chapter {ch_num}"),
                    question_count=q_count,
                )
            )

        percentage = round((module_question_total / total_pyqs) * 100.0, 1)

        if module_question_total >= 35:
            yield_tier = "Highest Yield (3-5 Qs/yr)"
        elif module_question_total >= 18:
            yield_tier = "High Yield (1-3 Qs/yr)"
        elif module_question_total >= 8:
            yield_tier = "Moderate Yield"
        else:
            yield_tier = "Low / Occasional Reference"

        # Construct clean human-readable strings for cards
        ch_list = mod.get("chapter_range", [])
        if ch_list:
            if len(ch_list) == 1:
                chapters_display = f"Ch {ch_list[0]}"
            else:
                chapters_display = f"Ch {ch_list[0]}–{ch_list[-1]} ({len(ch_list)} Chapters)"
        else:
            chapters_display = "None"

        art_list = mod.get("key_articles", [])
        if art_list:
            art_sample = [f"Art {a}" for a in art_list[:4]]
            articles_display = ", ".join(art_sample) + ("..." if len(art_list) > 4 else "")
        else:
            articles_display = "General Principles"

        blueprint_cards.append(
            PrelimsModuleCard(
                module_id=mod["module_id"],
                module_number=idx,
                title=mod["title"],
                official_line=mod["official_line"],
                total_questions=module_question_total,
                weightage_percentage=percentage,
                yield_tier=yield_tier,
                subtopics=mod["subtopics"],
                key_articles=mod["key_articles"],
                chapters=chapters_data,
                chapters_display=chapters_display,
                articles_display=articles_display,
            )
        )

    return blueprint_cards


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.get("/prelims", response_model=List[PrelimsModuleCard])
def get_prelims_blueprint(db: Session = Depends(get_db)):
    """Returns dynamic module cards with PYQ density and weightage."""
    return calculate_prelims_module_cards(db)


@router.get("/prelims/overview", response_model=CompletePrelimsBlueprintOut)
def get_complete_prelims_blueprint(db: Session = Depends(get_db)):
    """Returns the official decoded syllabus keyword-by-keyword along with all 10 module cards."""
    cards = calculate_prelims_module_cards(db)
    return CompletePrelimsBlueprintOut(
        official_syllabus_raw="Indian Polity and Governance – Constitution, Political System, Panchayati Raj, Public Policy, Rights Issues, etc.",
        syllabus_decoded=OFFICIAL_PRELIMS_DECODED,
        modules=cards,
    )


@router.get("/prelims/drill/{module_identifier}", response_model=List[PYQQuestionOut])
def get_pyqs_for_module(module_identifier: str, db: Session = Depends(get_db)):
    """
    Fetches all PYQ questions belonging to any chapter within a given syllabus module.
    Accepts either integer module index (e.g. '3') or string ID (e.g. 'MOD_03_RIGHTS_DUTIES_DPSP').
    """
    selected_module = None

    if module_identifier.isdigit():
        idx = int(module_identifier) - 1
        if 0 <= idx < len(PRELIMS_SYLLABUS_BLUEPRINT):
            selected_module = PRELIMS_SYLLABUS_BLUEPRINT[idx]
    else:
        selected_module = next(
            (m for m in PRELIMS_SYLLABUS_BLUEPRINT if m["module_id"] == module_identifier),
            None,
        )

    if not selected_module:
        raise HTTPException(status_code=404, detail="Syllabus module not found.")

    chapter_nums = selected_module["chapter_range"]

    questions = (
        db.query(PrelimsPYQModel)
        .filter(PrelimsPYQModel.chapter_number.in_(chapter_nums))
        .order_by(PrelimsPYQModel.year.desc(), PrelimsPYQModel.question_number.asc())
        .all()
    )
    return questions
