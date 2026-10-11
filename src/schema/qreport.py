from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid

class QuestionReportCreate(BaseModel):
    user_id: str = Field(..., description="User ID sent directly by the frontend", example="usr_12345")
    drill_date: Optional[str] = Field(None, example="2026-10-11")
    question_index: int = Field(..., ge=0, example=1)
    question_text: str = Field(..., example="Dicey's equality before law requires...")
    issue_type: str = Field(..., example="Incorrect Answer Key")
    user_notes: Optional[str] = Field(None, example="The explanation conflicts with Article 14 precedent.")

class QuestionReportResponse(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime

    class Config:
        from_attributes = True