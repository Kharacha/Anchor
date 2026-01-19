from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from app.schemas.sessions import CreateSessionRequest, CreateSessionResponse
from app.services.sessions_service import create_session

router = APIRouter(prefix="/v1", tags=["sessions"])


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session_route(request: Request, body: Optional[CreateSessionRequest] = None):
    # default tier if client sends no body
    tier = (body.tier if body is not None else "free")

    if tier not in ("free", "paid"):
        raise HTTPException(status_code=400, detail="tier must be 'free' or 'paid'")

    try:
        engine = request.app.state.engine
        policy_version = request.app.state.policy_version
        model_version = request.app.state.model_version

        session_id, user_id, max_sec = create_session(engine, tier, policy_version, model_version)

        return CreateSessionResponse(
            session_id=session_id,
            user_id=user_id,
            tier=tier,
            max_duration_sec=max_sec,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
