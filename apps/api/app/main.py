from fastapi import FastAPI
from urllib.parse import urlparse

from app.core.config import load_env, getenv_required, getenv_default
from app.core.db import make_engine
from app.routes.health import router as health_router
from app.routes.sessions import router as sessions_router

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

    app.state.engine = engine
    app.state.policy_version = getenv_default("POLICY_VERSION", "v1.0")
    app.state.model_version = getenv_default("MODEL_VERSION", "v1")

    app.include_router(health_router)
    app.include_router(sessions_router)

    return app

app = create_app()
