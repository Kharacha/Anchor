import os
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


# 1) Load the EXACT .env next to this file (no guessing, no cwd problems)
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL missing. Put it in apps/api/.env")

# 2) Force sslmode=require if it isn't already in the URL (Supabase pooler likes SSL)
u = urlparse(DATABASE_URL)
q = dict(parse_qsl(u.query, keep_blank_values=True))
if "sslmode" not in q:
    q["sslmode"] = "require"
    DATABASE_URL = urlunparse(u._replace(query=urlencode(q)))

# 3) Print what Python ACTUALLY parsed (safe: no password)
u2 = urlparse(DATABASE_URL)
print("ENV FILE:", ENV_PATH)
print("DB host:", u2.hostname)
print("DB user:", u2.username)
print("DB dbname:", (u2.path or "").lstrip("/"))
print("DB query:", u2.query)

# 4) Create engine
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True, "project": "anchor"}


@app.get("/health/db")
def health_db():
    # Fail honestly: return 500 if DB is not reachable/auth fails.
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return {"db": "ok", "host": u2.hostname, "user": u2.username}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "db": "error",
                "host": u2.hostname,
                "user": u2.username,
                "error": str(e),
            },
        )
