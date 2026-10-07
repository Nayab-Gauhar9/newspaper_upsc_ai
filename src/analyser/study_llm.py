import os
from typing import List, Optional, Any
from pydantic import BaseModel, Field, model_validator
from groq import Groq


class PrelimsPracticePoint(BaseModel):
    statement: str = Field(default="", description="A tricky Prelims-style statement testing a conceptual/factual point.")
    is_correct: bool = Field(default=True, description="Whether the statement is True or False.")
    explanation: str = Field(default="", description="Short explanation under 200 characters.")


class UPSCStudyIntelligence(BaseModel):
    headline: str = Field(default="", description="Sharp, UPSC-relevant title.")
    summary: str = Field(default="", description="Executive summary in 2-3 sentences.")
    why_it_matters: str = Field(default="", description="Significance for UPSC GS-II.")
    smart_notes: List[str] = Field(default_factory=list, description="4 high-yield analytical takeaways for Mains.")
    backward_linkages: List[str] = Field(default_factory=list, description="3-4 static links to Constitution/Laxmikanth.")
    mains_question: str = Field(default="", description="A model 15-mark GS-II Mains question.")
    prelims_practice_points: List[PrelimsPracticePoint] = Field(default_factory=list, description="1 or 2 Prelims practice statements.")

    @model_validator(mode="before")
    @classmethod
    def remap_flexible_keys(cls, data: Any) -> Any:
        """Remaps non-standard keys returned by the LLM."""
        if not isinstance(data, dict):
            return data

        # Fallbacks for headline & summary
        if "headline" not in data and "title" in data:
            data["headline"] = data["title"]
        if "summary" not in data and "executive_summary" in data:
            data["summary"] = data["executive_summary"]

        # Fallbacks for why_it_matters
        if "why_it_matters" not in data:
            data["why_it_matters"] = data.get("significance") or data.get("importance") or data.get("context") or ""

        # Fallbacks for smart_notes
        if "smart_notes" not in data:
            data["smart_notes"] = data.get("key_takeaways") or data.get("takeaways") or data.get("points") or data.get("analysis") or []
        if isinstance(data["smart_notes"], str):
            data["smart_notes"] = [data["smart_notes"]]

        # Fallbacks for backward_linkages
        if "backward_linkages" not in data:
            data["backward_linkages"] = data.get("linkages") or data.get("constitutional_linkages") or data.get("static_linkages") or []
        if isinstance(data["backward_linkages"], str):
            data["backward_linkages"] = [data["backward_linkages"]]

        # Fallbacks for mains_question
        if "mains_question" not in data:
            data["mains_question"] = data.get("question") or data.get("mains_framework") or ""

        # Fallbacks for prelims_practice_points
        if "prelims_practice_points" not in data:
            data["prelims_practice_points"] = data.get("prelims_questions") or data.get("quiz") or []

        return data


SYSTEM_SYNTHESIS_PROMPT = """You are an expert UPSC Civil Services examination mentor and evaluator for GS-II (Polity & Governance).
You must output strictly valid JSON conforming exactly to this structure with these exact field names:
{
  "headline": "<Sharp exam title>",
  "summary": "<2-3 sentence executive summary>",
  "why_it_matters": "<Why it matters for GS-II>",
  "smart_notes": ["<Takeaway 1>", "<Takeaway 2>", "<Takeaway 3>", "<Takeaway 4>"],
  "backward_linkages": ["<Static Link 1 (e.g. Article 246, Seventh Schedule)>", "<Static Link 2>"],
  "mains_question": "<A model 15-mark GS-II Mains question>",
  "prelims_practice_points": [
    {
      "statement": "<Tricky factual/conceptual statement>",
      "is_correct": true,
      "explanation": "<Explanation under 180 chars>"
    }
  ]
}"""

USER_SYNTHESIS_TEMPLATE = """Transform the following current affairs article into UPSC study intelligence.

Target Laxmikanth Chapter: {chapter_name}
Topic: {topic}
Source Publication: {publication}
Headline: {title}

Article Text:
{text}
"""

class UPSCStudySynthesizer:
    def __init__(self, client: Optional[Groq] = None):
        api_key = os.getenv("GROQ_API_KEY")
        self.client = client or Groq(api_key=api_key)
        self.model = "openai/gpt-oss-120b"

    def synthesize(self, chapter_name: str, topic: str, record: dict) -> UPSCStudyIntelligence:
        title = record.get("title", "")
        publication = record.get("publication", "Editorial")
        text = record.get("full_article", "")[:9000]

        prompt = USER_SYNTHESIS_TEMPLATE.format(
            chapter_name=chapter_name,
            topic=topic,
            publication=publication,
            title=title,
            text=text
        )

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_SYNTHESIS_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        return UPSCStudyIntelligence.model_validate_json(completion.choices[0].message.content)
