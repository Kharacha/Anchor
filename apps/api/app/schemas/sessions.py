from pydantic import BaseModel, Field
from typing import Literal

class CreateSessionRequest(BaseModel):
    tier: Literal["free", "paid"] = "free"

class CreateSessionResponse(BaseModel):
    session_id: str
    user_id: str
    tier: Literal["free", "paid"]
    max_duration_sec: int = Field(..., gt=0)
