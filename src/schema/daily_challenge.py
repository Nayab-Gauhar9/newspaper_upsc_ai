from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class MCQOptions(BaseModel):
    A: str = Field(description="Option A text")
    B: str = Field(description="Option B text")
    C: str = Field(description="Option C text")
    D: str = Field(description="Option D text")


class DailyChallengeItem(BaseModel):
    id: int = Field(ge=1, description="Question number index")
    archetype: Literal[
        "Pairing",
        "Pairing / Count",
        "Conceptual & Theory",
        "Multi-Statement",
        "Assertion-Reason",
        "Institutional Mechanics",
    ] = Field(description="UPSC question archetype")
    theme: str = Field(description="Topic/Theme e.g. Emergency Provisions, Money Bills")
    primary_article_ref: Optional[str] = Field(
        default=None,
        description="Constitutional article or statutory provision cited",
    )
    question: str = Field(description="The primary question stem")
    statements: Optional[List[str]] = Field(
        default=None,
        description="Numbered statements: ['1. ...', '2. ...']",
    )
    options: MCQOptions
    correct_option: Literal["A", "B", "C", "D"]
    explanation: str = Field(
        description="Comprehensive analytical explanation dissecting every statement and option"
    )
    traps_analyzed: Optional[str] = Field(
        default=None,
        description="Specific trap explanation",
    )


class DailyChallengeSet(BaseModel):
    challenge_date: str = Field(description="Date for the challenge in YYYY-MM-DD format")
    title: str = Field(default="Daily Static Polity Prelims Drill")
    questions: List[DailyChallengeItem] = Field(
        min_length=15,
        max_length=15,
        description="5 static Polity MCQs for test run",
    )

    @field_validator("questions")
    @classmethod
    def validate_unique_order(cls, v: List[DailyChallengeItem]) -> List[DailyChallengeItem]:
        ids = [q.id for q in v]
        if len(ids) != len(set(ids)):
            raise ValueError("All question IDs in the challenge set must be unique.")
        return v


# Rebuild to resolve any forward references cleanly
DailyChallengeSet.model_rebuild()
