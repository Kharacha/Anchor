# apps/api/app/main.py

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlparse

from app.core.config import load_env, getenv_required, getenv_default
from app.core.db import make_engine

from app.routes.health import router as health_router
from app.routes.sessions import router as sessions_router
from app.routes.turns import router as turns_router
from app.routes.chunks import router as chunks_router
from app.routes.trends import router as trends_router

# NEW ingest endpoints (transcript-only + /turns/audio fallback)
from app.routes.turns_ingest import router as turns_ingest_router

# NEW: wire self-hosted whisper (HTTP client)
from app.wiring.self_hosted_stt import build_self_hosted_transcribe_callable


def create_app() -> FastAPI:
    env_path = load_env()
    db_url = getenv_required("DATABASE_URL")

    engine = make_engine(db_url)

    # Safe debug (no password)
    u = urlparse(db_url)
    print("ENV FILE:", env_path)
    print("DB host:", u.hostname)
    print("DB user:", u.username)

    app = FastAPI(title="Anchor API", version="0.1.0")

    allowed_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.engine = engine
    app.state.policy_version = getenv_default("POLICY_VERSION", "v1.0")
    app.state.model_version = getenv_default("MODEL_VERSION", "v1")

    # ✅ Self-hosted transcription (used by /v1/sessions/{session_id}/turns/audio)
    # Calls STT docker service via HTTP (no whisper inside API container)
    app.state.self_hosted_transcribe = build_self_hosted_transcribe_callable()

    app.include_router(health_router)
    app.include_router(sessions_router)

    # Existing v1 pipeline (chunked/audio -> finalize). Keep for compatibility.
    app.include_router(turns_router)
    app.include_router(chunks_router)

    # Existing trends endpoint
    app.include_router(trends_router)

    # NEW ingest endpoints (transcript-only + /turns/audio fallback)
    app.include_router(turns_ingest_router)

    return app


app = create_app()
