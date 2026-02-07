# apps/api/app/routes/turns.py

from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException

from app.schemas.turns import CreateTurnRequest, CreateTurnResponse, SafetyResult
from app.services.turns_service import create_turn

router = APIRouter(prefix="/v1", tags=["turns-legacy"])


@router.post("/sessions/{session_id}/turns/text", response_model=CreateTurnResponse)
def create_turn_route(session_id: str, body: CreateTurnRequest, request: Request):
    """
    Legacy typed-text turn endpoint (kept for compatibility).
    IMPORTANT: This is intentionally NOT /turns to avoid colliding with transcript ingest.
    """
    try:
        engine = request.app.state.engine
        policy_version = request.app.state.policy_version
        model_version = request.app.state.model_version

        turn_id, user_text, assistant_text, safety, fallback_used = create_turn(
            engine,
            session_id=session_id,
            user_text=body.text,
            policy_version=policy_version,
            model_version=model_version,
        )

        return CreateTurnResponse(
            turn_id=str(turn_id),
            user_text=user_text,
            assistant_text=assistant_text,
            input_safety=SafetyResult(**safety),
            fallback_used=bool(fallback_used),
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
