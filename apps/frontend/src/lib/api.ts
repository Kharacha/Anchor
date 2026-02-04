const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

if (!API_BASE) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not set");
}

async function mustJson<T>(res: Response): Promise<T> {
    if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`${res.status} ${res.statusText} :: ${text}`);
    }
    return res.json() as Promise<T>;
}

export type Safety = { label: "allow" | "block" | "review"; reasons: string[]; meta: Record<string, any> };

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

export async function createSession(tier: "free" | "paid" = "free") {
    const res = await fetch(`${API_BASE}/v1/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
    });
    return mustJson<{ session_id: string } & Record<string, any>>(res);
}

export async function startTurn(sessionId: string) {
    const res = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/start`, { method: "POST" });
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

export async function appendChunk(sessionId: string, turnId: string, text: string, confidence: number) {
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

export async function getDailyTrends(sessionId: string, days: number = 30) {
    const res = await fetch(`${API_BASE}/v1/sessions/${sessionId}/trends/daily?days=${days}`, {
        method: "GET",
    });
    return mustJson<DailyTrendsResponse>(res);
}
