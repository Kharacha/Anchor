from fastapi import APIRouter, Request, HTTPException
from app.schemas.turns import CreateTurnRequest, CreateTurnResponse, SafetyResult
from app.services.turns_service import create_turn

router = APIRouter(prefix="/v1", tags=["turns"])

@router.post("/sessions/{session_id}/turns", response_model=CreateTurnResponse)
def create_turn_route(session_id: str, body: CreateTurnRequest, request: Request):
    try:
        engine = request.app.state.engine
        policy_version = request.app.state.policy_version
        model_version = request.app.state.model_version

        turn_id, user_text, assistant_text, safety, fallback_used = create_turn(
            engine, session_id, body.text, policy_version, model_version
        )

        return CreateTurnResponse(
            turn_id=turn_id,
            user_text=user_text,
            assistant_text=assistant_text,
            input_safety=SafetyResult(**safety),
            fallback_used=fallback_used,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
