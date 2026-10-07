import json
from collections import defaultdict
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor

# Use your existing DB dependency/pool imported in issues.py
from src.database.session import get_db


# --- Schemas for Chapter Directory ---
class DossierSummaryItem(BaseModel):
    issue_id: str
    issue_slug: str
    title: str
    status: str
    article_count: int
    mains_hook: Optional[str] = None
    constitutional_articles: List[str] = []
    last_updated_at: Optional[str] = None


class ChapterDossierGroup(BaseModel):
    chapter_name: str
    total_dossiers: int
    dossiers: List[DossierSummaryItem]

