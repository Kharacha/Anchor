# apps/stt/app.py

from __future__ import annotations

import io
import os
import subprocess
from typing import Optional, Tuple

import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException
from faster_whisper import WhisperModel


app = FastAPI(title="Anchor STT (self-hosted)", version="0.1.0")

MODEL_SIZE = os.getenv("WHISPER_MODEL", "small")           # tiny/base/small/medium/large-v3...
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")               # cpu or cuda
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")  # int8 / int8_float16 / float16 ...
LANG = os.getenv("STT_LANG", "en")                        # "en" or None for auto
VAD_FILTER = os.getenv("STT_VAD_FILTER", "true").lower() in ("1", "true", "yes")
BEAM_SIZE = int(os.getenv("STT_BEAM_SIZE", "5"))

# Lazy-init
_model: Optional[WhisperModel] = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def decode_to_pcm_f32(audio_bytes: bytes) -> Tuple[np.ndarray, int]:
    """
    Decode arbitrary input audio bytes (webm/opus, wav, m4a, etc.) into
    mono 16kHz float32 PCM using ffmpeg via stdin/stdout.
    No disk writes.
    """
    if not audio_bytes or len(audio_bytes) < 4000:
        raise ValueError("audio too short")

    # Output: mono, 16k, float32 little endian
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", "pipe:0",
        "-ac", "1",
        "-ar", "16000",
        "-f", "f32le",
        "pipe:1",
    ]

    p = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    out, err = p.communicate(input=audio_bytes)
    if p.returncode != 0 or not out:
        msg = (err.decode("utf-8", errors="ignore") or "").strip()
        raise RuntimeError(f"ffmpeg decode failed: {msg[:300]}")

    audio = np.frombuffer(out, dtype=np.float32)
    if audio.size < 1600:  # < 0.1s at 16k
        raise ValueError("decoded audio too short")

    return audio, 16000


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """
    multipart/form-data with field 'file'
    Returns: { text: str, confidence: float|null }
    """
    try:
        blob = await file.read()
        if not blob or len(blob) < 4000:
            raise HTTPException(status_code=400, detail="audio too short")

        audio, sr = decode_to_pcm_f32(blob)

        model = get_model()

        # faster-whisper returns segments + info
        segments, info = model.transcribe(
            audio,
            language=LANG if (LANG and LANG.lower() != "auto") else None,
            vad_filter=VAD_FILTER,
            beam_size=BEAM_SIZE,
        )

        texts = []
        for seg in segments:
            t = (seg.text or "").strip()
            if t:
                texts.append(t)

        text = " ".join(texts).strip()

        # Confidence heuristic:
        # - faster-whisper exposes avg_logprob, no_speech_prob in info
        # We'll map avg_logprob to ~[0,1] loosely; return null if unavailable.
        conf = None
        try:
            avg_logprob = getattr(info, "avg_logprob", None)
            if isinstance(avg_logprob, (int, float)):
                # avg_logprob typically in [-1.5, -0.1] for decent speech
                # map [-2.0..0.0] -> [0..1]
                conf = max(0.0, min(1.0, (float(avg_logprob) + 2.0) / 2.0))
        except Exception:
            conf = None

        return {"text": text, "confidence": conf}

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_SIZE, "device": DEVICE, "compute_type": COMPUTE_TYPE}
