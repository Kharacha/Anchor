from __future__ import annotations

import os
from typing import Optional, Tuple

from openai import OpenAI

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment")
        _client = OpenAI(api_key=api_key)
    return _client


def transcribe_upload_file(upload_file) -> Tuple[str, float | None]:
    """
    Returns (transcript_text, transcript_confidence_or_none)

    If OpenAI fails (quota, network, etc.), returns ("", None).
    """
    try:
        client = _get_client()
        model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe")

        try:
            upload_file.file.seek(0)
        except Exception:
            pass

        filename = getattr(upload_file, "filename", None) or "audio.webm"

        tx = client.audio.transcriptions.create(
            model=model,
            file=(filename, upload_file.file),
        )

        text = (getattr(tx, "text", None) or "").strip()
        return text, None
    except Exception:
        # graceful degrade; caller decides UX
        return "", None
