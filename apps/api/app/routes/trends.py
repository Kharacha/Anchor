from fastapi import APIRouter, Request, HTTPException
from app.schemas.trends import DailyTrendsResponse
from app.services.trends_service import get_daily_trends

router = APIRouter(prefix="/v1", tags=["trends"])


@router.get("/sessions/{session_id}/trends/daily", response_model=DailyTrendsResponse)
def daily_trends_route(session_id: str, request: Request, days: int = 30):
    """
    Returns last N days of daily aggregated derived scores for the session's user.
    Computed on read (fast query) and does NOT run on the chat path.
    """
    try:
        engine = request.app.state.engine
        days = max(1, min(int(days), 180))
        data = get_daily_trends(engine, session_id=session_id, days=days)
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")
