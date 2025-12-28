from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

router = APIRouter(tags=["health"])

@router.get("/health")
def health():
    return {"ok": True, "project": "anchor"}

@router.get("/health/db")
def health_db(request: Request):
    engine = request.app.state.engine
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return {"db": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
