from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from sqlalchemy import create_engine

def normalize_db_url(db_url: str) -> str:
    """
    Ensure sslmode=require is present for Supabase pooler.
    """
    u = urlparse(db_url)
    q = dict(parse_qsl(u.query, keep_blank_values=True))
    if "sslmode" not in q:
        q["sslmode"] = "require"
        db_url = urlunparse(u._replace(query=urlencode(q)))
    return db_url

def make_engine(db_url: str):
    db_url = normalize_db_url(db_url)
    return create_engine(db_url, pool_pre_ping=True)
