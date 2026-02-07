// apps/frontend/src/lib/api.ts

const API_BASE =
    (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/+$/, "") ||
    "http://localhost:8000";

async function mustJson<T>(res: Response): Promise<T> {
    if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`${res.status} ${res.statusText} :: ${text}`);
    }
    // Some endpoints might return empty bodies; keep it safe.
    const ct = res.headers.get("content-type") || "";
    if (!ct.includes("application/json")) {
        // @ts-expect-error - allow non-json responses in rare cases
        return (await res.text()) as T;
    }
    return (await res.json()) as T;
}

/* =========================================================
   Shared types
   ========================================================= */

export type Safety = {
    label: "allow" | "block" | "review";
    reasons: string[];
    meta: Record<string, any>;
};

export type StartTurnResponse = { turn_id: string; turn_index: number };

export type AudioUploadResponse = {
    transcript: string;
    confidence?: number | null;
    content_type?: string | null;
    bytes?: number | null;
};

export type FinalizeResponse = {
    turn_id: string;
    transcript: string;
    assistant_text: string;
    input_safety: Safety;
    fallback_used: boolean;
    analysis?: Record<string, any> | null;
};

export type DailyTrendPoint = {
    day: string;
    n: number;
    valence_mean?: number | null;
    arousal_mean?: number | null;
    confidence_mean?: number | null;
    extremeness_mean?: number | null;
};

export type DailyTrendsResponse = {
    session_id: string;
    user_id: string;
    days: number;
    points: DailyTrendPoint[];
};

/* =========================================================
   Sessions
   ========================================================= */

export async function createSession(tier: "free" | "paid" = "free") {
    const res = await fetch(`${API_BASE}/v1/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
    });
    return mustJson<{ session_id: string } & Record<string, any>>(res);
}

/* =========================================================
   Trends
   ========================================================= */

export async function getDailyTrends(sessionId: string, days: number = 30) {
    const res = await fetch(
        `${API_BASE}/v1/sessions/${sessionId}/trends/daily?days=${days}`,
        { method: "GET" }
    );
    return mustJson<DailyTrendsResponse>(res);
}

/* =========================================================
   Legacy chunked turn flow (kept for now; safe to delete later)
   ========================================================= */

export async function startTurn(sessionId: string) {
    const res = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/start`, {
        method: "POST",
    });
    return mustJson<StartTurnResponse>(res);
}

export async function uploadAudio(sessionId: string, turnId: string, blob: Blob) {
    const fd = new FormData();
    fd.append("file", blob, "voice.webm");
    const res = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/${turnId}/audio`, {
        method: "POST",
        body: fd,
    });
    return mustJson<AudioUploadResponse>(res);
}

export async function appendChunk(
    sessionId: string,
    turnId: string,
    text: string,
    confidence: number
) {
    const res = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/${turnId}/chunks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chunk_index: 0, text, confidence }),
    });
    return mustJson<{ ok: boolean; seq: number }>(res);
}

export async function finalizeTurn(sessionId: string, turnId: string) {
    const res = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/${turnId}/finalize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_turn_done: true }),
    });
    return mustJson<FinalizeResponse>(res);
}

/* =========================================================
   Transcript-only ingest (on-device STT default path)
   NOTE: returns FinalizeResponse to avoid duplicate response types
   ========================================================= */

export type TurnIngestRequest = {
    input_mode: "voice" | "text";
    transcript_text: string;
    transcript_confidence?: number | null;
    speech_features?: {
        duration_ms?: number;
        speech_rate?: number; // words/sec
        pause_ratio?: number; // 0..1
    };
    stt_provider_used: "on_device" | "self_hosted";
    fallback_used: boolean;
    client_latency_ms?: {
        record_ms?: number;
        stt_ms?: number;
    };
};

export async function ingestTurn(sessionId: string, body: TurnIngestRequest) {
    const res = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    return mustJson<FinalizeResponse>(res);
}

/* =========================================================
   Optional: server STT fallback endpoint (single-call)
   Endpoint: POST /v1/sessions/{session_id}/turns/audio
   Returns FinalizeResponse
   ========================================================= */

export async function ingestTurnAudioFallback(sessionId: string, blob: Blob) {
    const fd = new FormData();
    fd.append("file", blob, "voice.webm");
    const res = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/audio`, {
        method: "POST",
        body: fd,
    });
    return mustJson<FinalizeResponse>(res);
}
