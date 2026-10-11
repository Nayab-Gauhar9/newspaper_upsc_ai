from typing import List, Dict, Optional, Any, Literal
from pydantic import BaseModel, Field, model_validator
from src.classifiers.taxonomy import CHAPTER_BY_TITLE, LAXMIKANTH_8TH_EDITION

# --- Pydantic Schemas with Fallback Defaults ---

class PerspectiveArgument(BaseModel):
    argument: str = Field(default="", description="Crisp analytical point.")
    substantiation: str = Field(default="", description="Evidence: judgment, Constitutional article, committee report, or empirical data.")

class BalancedDialectic(BaseModel):
    thesis_affirmative_dimension: List[PerspectiveArgument] = Field(
        default_factory=list,
        description="Strongest arguments in favor / executive-institutional rationale / constitutional defense."
    )
    antithesis_critique_dimension: List[PerspectiveArgument] = Field(
        default_factory=list,
        description="Constructive critique identifying systemic flaws, democratic deficits, or institutional friction."
    )

class PrelimsStatement(BaseModel):
    statement: str = Field(default="", description="UPSC Prelims-style single statement testing an exact rule or fact.")
    is_correct: bool = Field(default=True, description="Whether statement is factually and legally true.")
    explanation: str = Field(default="", description="The underlying statutory/constitutional logic under 200 chars.")

class PrelimsEventFactsPayload(BaseModel):
    provisions_invoked: List[str] = Field(
        default_factory=list,
        description="Exact Articles, Schedules, or Statutory Sections (e.g. 'Article 324(5)', 'Section 62(5) RPA 1951')."
    )
    nodal_authority: str = Field(
        default="",
        description="Ministry or Constitutional/Statutory body involved."
    )
    legal_status: str = Field(
        default="Constitutional Body",
        description="Constitutional Body / Statutory Body / Quasi-judicial Body / Executive Body."
    )
    critical_thresholds: Optional[str] = Field(
        default="",
        description="Quorums, tenures, majorities, or age caps (e.g. 6 years or 65 years, 2/3rd majority)."
    )
    prelims_statements: List[PrelimsStatement] = Field(
        default_factory=list,
        description="2 rigorous statements testing exact legal rules and nuances."
    )

class PrelimsFactsheetPayload(BaseModel):
    constitutional_articles: List[str] = Field(
        default_factory=list,
        description="Canonical articles linked to this entire theme (e.g. ['Article 324', 'Article 326'])."
    )
    statutory_acts_sections: List[str] = Field(
        default_factory=list,
        description="Statutory Acts and exact sections."
    )
    nodal_body: str = Field(default="", description="Primary body or ministry.")
    body_character: str = Field(default="", description="Constitutional / Statutory / Regulatory.")
    tenure_and_removal: str = Field(default="", description="Exact tenure and method of appointment/removal.")
    key_reform_committees: List[str] = Field(
        default_factory=list,
        description="Committees and Law Commission reports (e.g. 'Dinesh Goswami (1990)', '2nd ARC 4th Report')."
    )

class UPSCPhDIntelligence(BaseModel):
    chapter_number: int = Field(default=0, description="Exact M. Laxmikanth 8th Edition chapter number (1-92).")
    chapter_name: str = Field(default="Constitutional Prescriptions", description="Exact chapter name as per M. Laxmikanth 8th Edition.")
    is_existing_dossier: bool = Field(
        default=False,
        description="True if linked to an existing active dossier in candidate list, False if brand new."
    )
    issue_slug: str = Field(default="constitutional-governance-issue", description="Hyphenated topic slug. Must be identical to candidate slug if is_existing_dossier is True.")
    suggested_status: Literal["active", "resolved"] = Field(

        default="active",
        description="Must be 'resolved' ONLY IF this development represents a final landmark verdict, Presidential assent, or definitive closure; otherwise 'active'."
    )
    headline: str = Field(default="", description="Academic, exam-oriented headline capturing the constitutional crux.")
    theoretical_and_constitutional_context: str = Field(
        default="",
        description="Theory framing (e.g., checks and balances, substantive equality) and Constitutional Articles."
    )
    executive_synthesis: str = Field(
        default="",
        description="High-density synthesis of current development and its systemic implications."
    )
    dialectical_matrix: BalancedDialectic = Field(default_factory=BalancedDialectic)
    constitutional_anchors: List[str] = Field(
        default_factory=list,
        description="Relevant Articles, Landmark SC Cases, Statutory Acts, or Law Commission Reports."
    )
    mains_model_framework: Dict[str, str] = Field(
        default_factory=lambda: {
            "introduction_hook": "",
            "body_dimensions": "",
            "way_forward_reforms": ""
        }
    )
    prelims_event_facts: PrelimsEventFactsPayload = Field(default_factory=PrelimsEventFactsPayload)
    prelims_factsheet: PrelimsFactsheetPayload = Field(default_factory=PrelimsFactsheetPayload)

    @model_validator(mode="before")
    @classmethod
    def remap_and_align_taxonomy(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        raw_chapter = data.get("chapter_name") or data.get("chapter") or ""
        matched_num = None

        if raw_chapter in CHAPTER_BY_TITLE:
            matched_num = CHAPTER_BY_TITLE[raw_chapter]
            canonical_name = raw_chapter
        else:
            lower_to_title = {k.lower(): (k, v) for k, v in CHAPTER_BY_TITLE.items()}
            raw_lower = str(raw_chapter).lower().strip()
            
            if raw_lower in lower_to_title:
                canonical_name, matched_num = lower_to_title[raw_lower]
            else:
                canonical_name = raw_chapter or "Constitutional Prescriptions"
                matched_num = data.get("chapter_number", 55)

        data["chapter_name"] = canonical_name
        data["chapter_number"] = matched_num or data.get("chapter_number", 0)

        raw_status = str(data.get("suggested_status") or data.get("status") or "active").strip().lower()
        if raw_status in ("resolved", "closed", "settled", "concluded"):
            data["suggested_status"] = "resolved"
        else:
            data["suggested_status"] = "active"

        if "issue_slug" not in data or not data["issue_slug"]:
            raw_slug = data.get("slug") or data.get("topic_slug") or canonical_name
            data["issue_slug"] = str(raw_slug).lower().replace(" ", "-").replace("–", "-")[:45]

        if "headline" not in data or not data["headline"]:
            data["headline"] = data.get("title") or data.get("issue_title") or "Constitutional Analysis"

        if "executive_synthesis" not in data or not data["executive_synthesis"]:
            data["executive_synthesis"] = data.get("summary") or data.get("executive_summary") or data.get("analysis") or ""

        if "theoretical_and_constitutional_context" not in data or not data["theoretical_and_constitutional_context"]:
            data["theoretical_and_constitutional_context"] = data.get("context") or data.get("significance") or ""

        if "constitutional_anchors" not in data or not data["constitutional_anchors"]:
            data["constitutional_anchors"] = data.get("anchors") or data.get("backward_linkages") or data.get("articles") or []

        return data


# --- System & User Prompts ---

PHD_UPSC_SYSTEM_PROMPT = """You are a senior UPSC CSE GS-II Mains Chief Evaluator and Prelims Question Setter holding a Doctorate in Constitutional Law.
Your analytical posture is rigorous, strictly neutral, dialectical, and factually grounded.

You MUST anchor the article to the exact M. Laxmikanth (8th Edition) chapter title and chapter number.
Select the chapter from this official table of contents:
- 1: Historical Background, 2: Making of the Constitution, 3: Concept of Constitution, 4: Salient Features of the Constitution, 5: Preamble
- 6: Union and its Territory, 7: Citizenship, 8: Fundamental Rights, 9: Directive Principles of State Policy, 10: Fundamental Duties
- 11: Amendment of the Constitution, 12: Basic Structure, 13: Parliamentary System, 14: Federal System, 15: Centre–State Relations
- 16: Inter-State Relations, 17: Emergency Provisions, 18: President, 19: Vice-President, 20: Prime Minister, 21: Central Council of Ministers
- 22: Cabinet Committees, 23: Parliament, 24: Parliamentary Committees, 25: Parliamentary Group, 26: Supreme Court, 27: Judicial Review
- 28: Judicial Activism, 29: Public Interest Litigation, 30: Governor, 31: Chief Minister, 32: State Council of Ministers, 33: State Legislature
- 34: High Court, 35: Subordinate Courts, 36: Tribunals, 37: NCDRC, 38: Lok Adalat and other courts, 39: Panchayati Raj, 40: Municipalities
- 41: Union Territories, 42: Scheduled and Tribal Areas, 43: Election Commission, 44: UPSC, 45: SPSC, 46: Finance Commission, 47: GST Council
- 48: NCSC, 49: NCST, 50: NCBC, 51: Linguistic Minorities, 52: CAG, 53: Attorney General, 54: Advocate General, 55: Constitutional Prescriptions
- 56: NITI Aayog, 57: NHRC, 58: SHRC, 59: NCW, 60: NCPCR, 61: NCM, 62: CIC, 63: SIC, 64: CVC, 65: CBI, 66: Lokpal and Lokayuktas
- 67: NIA, 68: NDMA, 69: BCI, 70: Law Commission, 71: Delimitation Commission, 72: Co-operative Societies, 73: Official Language
- 74: Public Services, 75: Rights and Liabilities of Govt, 76: Certain Classes, 77: Special Provisions for Some States, 78: Political Parties
- 79: Regional Parties, 80: Elections, 81: Election Laws, 82: Electoral Reforms, 83: Voting Behaviour, 84: Coalition Government
- 85: Anti-Defection Law, 86: Pressure Groups, 87: National Integration, 88: Foreign Policy, 89: NCRWC, 90: Landmark Judgements
- 91: Important Doctrines of Constitutional Interpretation, 92: World Constitutions

STATUS ASSESSMENT RULES:
- Use "resolved" ONLY if this report delivers a definitive judicial resolution (e.g. final Constitution Bench judgment), an enactment of an Act after Presidential assent (Art 111), or the final tabling of a statutory commission report.
- Otherwise, for ongoing debates, notices, interim orders, editorial opinions, or consultative processes, strictly set "suggested_status": "active".

You must respond ONLY with valid JSON conforming EXACTLY to this schema:
{
  "chapter_number": <int from 1 to 92>,
  "chapter_name": "<Exact M. Laxmikanth 8th Edition chapter name from the list above>",
  "is_existing_dossier": <true | false>,
  "issue_slug": "<lowercase-hyphenated-slug>",
  "suggested_status": "<active | resolved>",
  "headline": "<Academic, exam-oriented headline capturing the constitutional crux>",
  "theoretical_and_constitutional_context": "<1-2 sentences framing the issue through political theory and specific Articles>",
  "executive_synthesis": "<High-density 120-word synthesis of current development and its systemic implications>",
  "dialectical_matrix": {
    "thesis_affirmative_dimension": [
      {
        "argument": "<Institutional / Constitutional argument supporting the provision/measure>",
        "substantiation": "<Specific Article, Doctrine, or Precedent>"
      }
    ],
    "antithesis_critique_dimension": [
      {
        "argument": "<Systemic critique or democratic deficit identifying implementation hazards>",
        "substantiation": "<Empirical fact, Commission report, or dissenting jurisprudence>"
      }
    ]
  },
  "constitutional_anchors": [
    "<e.g. Article 326>",

"<e.g. Representation of the People Act, 1951, Section 62(5)>",
    "<e.g. Anukul Chandra Pradhan v. Union of India (1997)>"
  ],
  "mains_model_framework": {
    "introduction_hook": "<15-mark Mains answer opening>",
    "body_dimensions": "<Core analytical dimensions evaluating structural balance>",
    "way_forward_reforms": "<Constructive 2nd ARC/Law Commission-backed administrative solutions>"
  },
  "prelims_event_facts": {
    "provisions_invoked": ["<Article or statutory section numbers>"],
    "nodal_authority": "<Ministry, commission, or court>",
    "legal_status": "<Constitutional / Statutory / Executive>",
    "critical_thresholds": "<Quorum, tenure, or majority requirement>",
    "prelims_statements": [
      {
        "statement": "<Tricky factual statement testing exact statutory or constitutional rule>",
        "is_correct": true,
        "explanation": "<Concise explanation for the answer key>"
      },
      {
        "statement": "<Another statement introducing a common exam trap>",
        "is_correct": false,
        "explanation": "<Concise explanation pointing out the misconception>"
      }
    ]
  },
  "prelims_factsheet": {
    "constitutional_articles": ["<All foundational articles relevant to this entire topic>"],
    "statutory_acts_sections": ["<Relevant acts and key sections>"],
    "nodal_body": "<Primary constitutional or statutory entity>",
    "body_character": "<Constitutional / Statutory>",
    "tenure_and_removal": "<Tenure and constitutional removal mechanism>",
    "key_reform_committees": ["<e.g. Dinesh Goswami (1990), Law Commission 255th Report>"]
  }
}
"""

TOPIC_EVOLUTION_USER_PROMPT = """Analyze and synthesize the following current affairs article into the requested JSON schema.

Pre-classified Chapter: {chapter_name}
Topic: {topic}
Source Publication: {publication}
Article Title: {title}

EXISTING ACTIVE DOSSIERS IN THIS CHAPTER:
{existing_candidates}

CRITICAL SLUG & EVOLUTION RULE:
1. Examine the existing active dossiers listed above.
2. AGGRESSIVE DEDUPLICATION: If this article reports on the SAME ongoing dispute, High Court/Supreme Court proceeding, controversy, or policy development (even if covering a different phase, newer hearing, notice, or reaction from another publication), you MUST set "is_existing_dossier": true and REUSE THE EXACT "issue_slug" from the candidates list.
3. DO NOT invent a slightly different slug for updates or parallel reporting of the same event.
4. Only set "is_existing_dossier": false if this article addresses a fundamentally distinct legal issue or entirely different state/institution.

Article Text:
{text}
"""
