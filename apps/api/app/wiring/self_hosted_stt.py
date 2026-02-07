# apps/api/app/wiring/self_hosted_stt.py

from __future__ import annotations

import os
import time
from typing import Any, Dict, Callable, Optional, Tuple

import requests


def _parse_timeout(timeout_s: float) -> Tuple[float, float]:
    """
    requests timeout can be:
      - single float (total)
      - tuple(connect_timeout, read_timeout)
    We'll split to be safer:
      connect: 5s (or 10% of total, capped)
      read: remainder
    """
    total = max(1.0, float(timeout_s))
    connect = min(5.0, max(1.0, total * 0.1))
    read = max(1.0, total - connect)
    return connect, read


def build_self_hosted_transcribe_callable() -> Callable[[bytes, str], Dict[str, Any]]:
    """
    Returns a function(blob: bytes, content_type: str) -> { "text": str, "confidence": float|None }

    Calls an HTTP STT service (Docker container), so API container stays clean
    and does not need whisper/tokenizers installed.
    """

    url = os.getenv("SELF_HOSTED_STT_URL", "http://stt:8001/transcribe").strip()

    # Default to longer since first transcription often includes model load.
    timeout_s = float(os.getenv("SELF_HOSTED_STT_TIMEOUT_S", "180"))
    timeout = _parse_timeout(timeout_s)

    # Optional headers (if you later add auth between services)
    api_key = os.getenv("SELF_HOSTED_STT_API_KEY", "").strip()

    # One retry helps when the model is cold / first request spikes.
    max_attempts = int(os.getenv("SELF_HOSTED_STT_MAX_ATTEMPTS", "2"))
    max_attempts = max(1, min(3, max_attempts))

    def _transcribe(blob: bytes, content_type: str = "audio/webm") -> Dict[str, Any]:
        if not blob or len(blob) < 4000:
            return {"text": "", "confidence": None}

        headers = {}
        if api_key:
            headers["x-api-key"] = api_key

        files = {"file": ("voice.webm", blob, content_type or "audio/webm")}

        last_err: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                r = requests.post(url, files=files, headers=headers, timeout=timeout)

                if r.status_code != 200:
                    # Keep error stable; don't leak huge bodies
                    raise ValueError(f"self-hosted stt failed: {r.status_code} :: {r.text[:300]}")

                data = r.json() if r.content else {}
                text = (data.get("text") or "").strip()

                conf: Optional[float] = data.get("confidence", None)
                try:
                    conf = float(conf) if conf is not None else None
                except Exception:
                    conf = None

                return {"text": text, "confidence": conf}

            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
                last_err = e
                # small backoff before retry
                if attempt < max_attempts:
                    time.sleep(0.35)
                    continue
                raise ValueError(
                    f"self-hosted stt timeout after {timeout_s:.0f}s (attempt {attempt}/{max_attempts})"
                ) from e

            except requests.exceptions.RequestException as e:
                # any other requests/network issue
                last_err = e
                raise ValueError(f"self-hosted stt request failed: {type(e).__name__}") from e

        # Should never hit
        raise ValueError("self-hosted stt failed") from last_err

    return _transcribe
