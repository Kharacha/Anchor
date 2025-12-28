import os
from dotenv import load_dotenv

def load_env() -> str:
    """
    Load the .env that lives in apps/api/.env deterministically.
    Returns the absolute env path used (useful for debug).
    """
    # app/core/config.py -> app/core -> app -> (apps/api/app) -> (apps/api)
    api_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env_path = os.path.join(api_root, ".env")
    load_dotenv(dotenv_path=env_path, override=True)
    return env_path

def getenv_required(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"{key} missing. Put it in apps/api/.env")
    return val

def getenv_default(key: str, default: str) -> str:
    return os.getenv(key, default)
