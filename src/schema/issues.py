from datetime import datetime, date
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


# --- Granular Prelims Sub-Schemas ---

class PrelimsStatementOut(BaseModel):
    statement: str = Field(..., description="UPSC Prelims factual/conceptual practice statement.")
    is_correct: bool = Field(..., description="Whether the statement is legally true or false.")
    explanation: Optional[str] = Field(None, description="Underlying constitutional/statutory reasoning.")


class PrelimsEventFactsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provisions_invoked: List[str] = Field(default_factory=list, description="Articles and sections invoked in this event.")
    nodal_authority: Optional[str] = Field(None, description="Body, Ministry, or Court involved.")
    legal_status: Optional[str] = Field(None, description="Constitutional, statutory, or executive classification.")
    critical_thresholds: Optional[str] = Field(None, description="Quorums, majorities, or bench composition.")
    prelims_statements: List[PrelimsStatementOut] = Field(default_factory=list, description="Targeted drill statements.")


class PrelimsFactsheetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    constitutional_articles: List[str] = Field(default_factory=list)
    statutory_acts_sections: List[str] = Field(default_factory=list)
    nodal_body: Optional[str] = None
    body_character: Optional[str] = None
    tenure_and_removal: Optional[str] = None
    key_reform_committees: List[str] = Field(default_factory=list)


# --- Mains Sub-Schema ---

class MainsFrameworkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    introduction_hook: Optional[str] = None
    body_dimensions: Optional[str] = None
    way_forward_reforms: Optional[str] = None


# --- Output Models ---

class GraphEdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    edge_id: UUID
    issue_slug: str
    prid: str
    publication: str
    event_date: date
    perspective_stance: str
    core_claim: str
    legal_anchors: List[str]
    prelims_event_facts: Optional[PrelimsEventFactsOut] = None
    created_at: datetime


class IssueDossierSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    issue_id: UUID
    issue_slug: str
    title: str
    chapter_name: str
    status: str
    article_count: int
    first_detected_at: datetime
    last_updated_at: datetime
    canonical_summary: Optional[str] = None


class IssueDossierDetailOut(IssueDossierSummaryOut):
    mains_framework: Optional[MainsFrameworkOut] = None
    prelims_factsheet: Optional[PrelimsFactsheetOut] = None
    edges: List[GraphEdgeOut] = []


class PrelimsDrillItemOut(BaseModel):
    issue_slug: str
    dossier_title: str
    chapter_name: str
    publication: str
    event_date: date
    statement: str
    is_correct: bool
    explanation: str
    provisions_invoked: List[str] = []
