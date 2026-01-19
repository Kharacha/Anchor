# apps/api/app/services/baselines_service.py

from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional

from app.repos import baselines_repo


# -----------------------
# Defaults (easy to change later)
# -----------------------
DEFAULT_ALPHA = 0.10              # EMA step size (decay/windowing)
DEFAULT_Z_THRESHOLD = 2.5         # spike detection threshold (std devs)
DEFAULT_DELTA_V = 0.60            # "big shift" from baseline (valence)
DEFAULT_DELTA_A = 0.60            # "big shift" from baseline (arousal)
DEFAULT_EXTREME_THRESH = 0.55     # extremeness gating threshold
DEFAULT_MIN_WEIGHT = 0.05         # minimum weight for updates when confidence is low
EPS = 1e-6


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _compute_extremeness(valence: float, arousal: float) -> float:
    # extremeness = abs(valence) * (0.5 + 0.5 * arousal)
    return abs(valence) * (0.5 + 0.5 * arousal)


def _ema_update(
    mean: Optional[float],
    var: Optional[float],
    x: float,
    *,
    alpha: float,
    weight: float,
) -> tuple[float, float]:
    """
    Weighted EMA mean/var update.
    - mean_new = (1 - a*w)*mean + (a*w)*x
    - var is EMA of squared deviation (also weighted)
    """
    if mean is None:
        mean = x
    if var is None:
        var = 0.0

    a = _clamp(alpha * weight, 0.0, 1.0)

    new_mean = (1.0 - a) * mean + a * x
    dev = x - new_mean
    new_var = (1.0 - a) * var + a * (dev * dev)

    return float(new_mean), float(new_var)


def update_user_baseline_if_opted_in(
    conn,
    *,
    user_id: str,
    session_id: str,
    baseline_opt_in: bool,
    valence: float | None,
    arousal: float | None,
    confidence: float | None = None,
    transcript_confidence: float | None = None,
    speech_rate_wpm: float | None = None,
    pause_ratio: float | None = None,
    # tuning knobs (defaults ok)
    alpha: float = DEFAULT_ALPHA,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    delta_v: float = DEFAULT_DELTA_V,
    delta_a: float = DEFAULT_DELTA_A,
    extreme_thresh: float = DEFAULT_EXTREME_THRESH,
) -> Optional[Dict[str, Any]]:
    """
    Implements:
      1) Delta flags: compare current vs baseline mean
      2) Extremeness gating: mark extreme turns
      3) Decay/windowing: EMA baseline update (alpha)
      4) Confidence-weighted baseline update: weight uses confidence and transcript_confidence
      5) Spike detection: z-score based using EMA variance
      6) Drift visualization: baseline_events record contains baseline before/after + deltas
    """

    if not baseline_opt_in:
        return None

    v = _safe_float(valence)
    a = _safe_float(arousal)
    c = _safe_float(confidence)
    tc = _safe_float(transcript_confidence)
    sr = _safe_float(speech_rate_wpm)
    pr = _safe_float(pause_ratio)

    if v is None and a is None and sr is None and pr is None:
        return None

    # Use confidence as update weight
    # - OpenAI confidence measures "emotion scoring confidence"
    # - transcript_confidence measures "STT confidence"
    # Weight should be conservative if either is low.
    w1 = 1.0 if c is None else _clamp(c, 0.0, 1.0)
    w2 = 1.0 if tc is None else _clamp(tc, 0.0, 1.0)
    weight = max(DEFAULT_MIN_WEIGHT, w1 * w2)

    current = baselines_repo.get_user_baseline(conn, user_id) or {}

    v_mean_before = _safe_float(current.get("valence_mean"))
    v_var_before = _safe_float(current.get("valence_var"))
    a_mean_before = _safe_float(current.get("arousal_mean"))
    a_var_before = _safe_float(current.get("arousal_var"))

    sr_mean_before = _safe_float(current.get("speech_rate_mean"))
    sr_var_before = _safe_float(current.get("speech_rate_var"))
    pr_mean_before = _safe_float(current.get("pause_ratio_mean"))
    pr_var_before = _safe_float(current.get("pause_ratio_var"))

    # Extremeness (computed from current turn if possible)
    extremeness = None
    extreme = False
    if v is not None and a is not None:
        extremeness = _compute_extremeness(v, a)
        extreme = extremeness > extreme_thresh

    # Delta-based flags (before update)
    delta_flags = {
        "valence_shift": False,
        "arousal_shift": False,
    }
    delta_vals = {
        "valence_delta": None,
        "arousal_delta": None,
    }

    if v is not None and v_mean_before is not None:
        dv = v - v_mean_before
        delta_vals["valence_delta"] = float(dv)
        delta_flags["valence_shift"] = abs(dv) >= delta_v

    if a is not None and a_mean_before is not None:
        da = a - a_mean_before
        delta_vals["arousal_delta"] = float(da)
        delta_flags["arousal_shift"] = abs(da) >= delta_a

    # Spike detection via z-score (before update)
    v_z = None
    a_z = None
    spike = False

    if v is not None and v_mean_before is not None and v_var_before is not None:
        v_z = (v - v_mean_before) / math.sqrt(v_var_before + EPS)
        spike = spike or (abs(v_z) >= z_threshold)

    if a is not None and a_mean_before is not None and a_var_before is not None:
        a_z = (a - a_mean_before) / math.sqrt(a_var_before + EPS)
        spike = spike or (abs(a_z) >= z_threshold)

    # Update baseline using weighted EMA
    v_mean_after, v_var_after = v_mean_before, v_var_before
    a_mean_after, a_var_after = a_mean_before, a_var_before

    if v is not None:
        v_mean_after, v_var_after = _ema_update(v_mean_before, v_var_before, v, alpha=alpha, weight=weight)
    if a is not None:
        a_mean_after, a_var_after = _ema_update(a_mean_before, a_var_before, a, alpha=alpha, weight=weight)

    # Speech/pause optional for later — keep previous values if not present
    sr_mean_after, sr_var_after = sr_mean_before, sr_var_before
    pr_mean_after, pr_var_after = pr_mean_before, pr_var_before

    if sr is not None:
        sr_mean_after, sr_var_after = _ema_update(sr_mean_before, sr_var_before, sr, alpha=alpha, weight=weight)
    if pr is not None:
        pr_mean_after, pr_var_after = _ema_update(pr_mean_before, pr_var_before, pr, alpha=alpha, weight=weight)

    baselines_repo.upsert_user_baseline(
        conn,
        user_id=user_id,
        valence_mean=v_mean_after,
        valence_var=v_var_after,
        arousal_mean=a_mean_after,
        arousal_var=a_var_after,
        speech_rate_mean=sr_mean_after,
        speech_rate_var=sr_var_after,
        pause_ratio_mean=pr_mean_after,
        pause_ratio_var=pr_var_after,
    )

    payload: Dict[str, Any] = {
        "schema_version": 2,
        "updated": True,
        "method": "ema_weighted",
        "alpha": alpha,
        "weight": weight,
        "inputs": {
            "valence": v,
            "arousal": a,
            "confidence": c,
            "transcript_confidence": tc,
            "speech_rate_wpm": sr,
            "pause_ratio": pr,
        },
        "before": {
            "valence_mean": v_mean_before,
            "valence_var": v_var_before,
            "arousal_mean": a_mean_before,
            "arousal_var": a_var_before,
            "speech_rate_mean": sr_mean_before,
            "speech_rate_var": sr_var_before,
            "pause_ratio_mean": pr_mean_before,
            "pause_ratio_var": pr_var_before,
        },
        "after": {
            "valence_mean": v_mean_after,
            "valence_var": v_var_after,
            "arousal_mean": a_mean_after,
            "arousal_var": a_var_after,
            "speech_rate_mean": sr_mean_after,
            "speech_rate_var": sr_var_after,
            "pause_ratio_mean": pr_mean_after,
            "pause_ratio_var": pr_var_after,
        },
        "delta": {
            **delta_vals,
            "flags": delta_flags,
        },
        "spike": {
            "z_threshold": z_threshold,
            "valence_z": v_z,
            "arousal_z": a_z,
            "is_spike": spike,
        },
        "extremeness": {
            "value": extremeness,
            "threshold": extreme_thresh,
            "is_extreme": extreme,
        },
    }

    baselines_repo.insert_baseline_event(
        conn,
        user_id=user_id,
        session_id=session_id,
        data_json=json.dumps(payload),
    )
    return payload
