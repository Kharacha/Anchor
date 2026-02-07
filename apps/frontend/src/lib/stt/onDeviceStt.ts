// apps/frontend/src/lib/stt/onDeviceStt.ts

export type OnDeviceSttResult = {
    text: string;
    confidence?: number | null; // Web Speech doesn't expose numeric confidence consistently
    provider: "on_device";
};

export type OnDeviceSttFailure = {
    ok: false;
    reason: string;
};

export type OnDeviceSttSuccess = {
    ok: true;
    result: OnDeviceSttResult;
};

export type OnDeviceSttOutcome = OnDeviceSttSuccess | OnDeviceSttFailure;

// Web Speech API types are not in TS DOM lib by default in some setups.
type SpeechRecognitionLike = any;

function getSpeechRecognition(): SpeechRecognitionLike | null {
    const w = window as any;
    return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

/**
 * Start a Web Speech recognition session (on-device / browser-managed).
 * You control start/stop externally and receive final transcript.
 */
export function createOnDeviceRecognizer() {
    const SR = getSpeechRecognition();
    if (!SR) return null;

    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";

    let finalText = "";
    let interimText = "";
    let startedAt = 0;

    const listeners: {
        onInterim?: (t: string) => void;
        onFinal?: (t: string) => void;
        onError?: (reason: string) => void;
    } = {};

    rec.onresult = (event: any) => {
        interimText = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const res = event.results[i];
            const txt = (res?.[0]?.transcript || "").trim();
            if (!txt) continue;

            if (res.isFinal) {
                finalText += (finalText ? " " : "") + txt;
                listeners.onFinal?.(finalText.trim());
            } else {
                interimText += (interimText ? " " : "") + txt;
                listeners.onInterim?.((finalText + " " + interimText).trim());
            }
        }
    };

    rec.onerror = (e: any) => {
        listeners.onError?.(String(e?.error || e?.message || "stt_error"));
    };

    rec.onend = () => {
        // end is normal on stop()
    };

    return {
        setHandlers(h: typeof listeners) {
            listeners.onInterim = h.onInterim;
            listeners.onFinal = h.onFinal;
            listeners.onError = h.onError;
        },
        start() {
            finalText = "";
            interimText = "";
            startedAt = Date.now();
            rec.start();
            return startedAt;
        },
        stop(): Promise<OnDeviceSttOutcome> {
            return new Promise((resolve) => {
                const done = () => {
                    const text = (finalText || interimText || "").trim();
                    if (!text) return resolve({ ok: false, reason: "empty_transcript" });
                    return resolve({
                        ok: true,
                        result: { text, confidence: null, provider: "on_device" },
                    });
                };

                // Web Speech stops async; onend fires after stop. We also set a timeout fallback.
                let settled = false;

                const timeout = setTimeout(() => {
                    if (settled) return;
                    settled = true;
                    done();
                }, 1200);

                const prevOnEnd = rec.onend;
                rec.onend = () => {
                    try {
                        prevOnEnd?.();
                    } catch {}
                    clearTimeout(timeout);
                    if (settled) return;
                    settled = true;
                    done();
                };

                try {
                    rec.stop();
                } catch {
                    clearTimeout(timeout);
                    if (!settled) {
                        settled = true;
                        resolve({ ok: false, reason: "stop_failed" });
                    }
                }
            });
        },
    };
}
