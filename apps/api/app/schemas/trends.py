# apps/api/app/schemas/trends.py

from pydantic import BaseModel
from typing import List, Optional


class DailyTrendPoint(BaseModel):
    day: str  # YYYY-MM-DD
    n: int

    valence_mean: Optional[float] = None
    arousal_mean: Optional[float] = None
    confidence_mean: Optional[float] = None
    extremeness_mean: Optional[float] = None


class DailyTrendsResponse(BaseModel):
    session_id: str
    user_id: str
    days: int
    points: List[DailyTrendPoint]
