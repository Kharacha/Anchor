"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  createSession,
  getDailyTrends,
  ingestTurn,
  ingestTurnAudioFallback,
  type DailyTrendPoint,
  type Safety,
} from "../lib/api";

/* =========================================================
   On-device STT (Web Speech API) — ONLY when toggle is enabled
   ========================================================= */

type SpeechRecognizer = {
  start: () => void;
  stop: () => Promise<{ ok: true; text: string } | { ok: false; reason: string }>;
  onInterim?: (t: string) => void;
};

function normalizeSpaces(s: string) {
  return (s || "").replace(/\s+/g, " ").trim();
}

function createOnDeviceRecognizer(): SpeechRecognizer | null {
  const w = window as any;
  const SR = w.SpeechRecognition || w.webkitSpeechRecognition;
  if (!SR) return null;

  const rec = new SR();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = "en-US";

  let finalText = "";
  let interimText = "";

  const api: SpeechRecognizer = {
    start() {
      finalText = "";
      interimText = "";
      try {
        rec.start();
      } catch {
        // start can throw if called too quickly; we handle via fallback path
      }
    },
    stop() {
      return new Promise((resolve) => {
        let settled = false;

        const finish = () => {
          const text = normalizeSpaces((finalText + " " + interimText).trim());
          if (!text) return resolve({ ok: false, reason: "empty_transcript" });
          resolve({ ok: true, text });
        };

        const timeout = setTimeout(() => {
          if (settled) return;
          settled = true;
          finish();
        }, 1200);

        const prevEnd = rec.onend;
        rec.onend = () => {
          try {
            prevEnd?.();
          } catch {}
          clearTimeout(timeout);
          if (settled) return;
          settled = true;
          finish();
        };

        try {
          rec.stop();
        } catch {
          clearTimeout(timeout);
          resolve({ ok: false, reason: "stop_failed" });
        }
      });
    },
  };

  rec.onresult = (event: any) => {
    interimText = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const res = event.results[i];
      const txt = normalizeSpaces(res?.[0]?.transcript || "");
      if (!txt) continue;

      if (res.isFinal) {
        // NOTE: do NOT force punctuation — it makes it worse.
        finalText = normalizeSpaces(finalText + " " + txt);
      } else {
        interimText = normalizeSpaces(interimText + " " + txt);
      }
    }
    api.onInterim?.(normalizeSpaces((finalText + " " + interimText).trim()));
  };

  rec.onerror = () => {
    // handled by stop() outcome; we’ll fallback if empty
  };

  return api;
}

/* =========================================================
   UI types
   ========================================================= */

type Msg = { id: string; role: "user" | "assistant"; text: string };

function uid() {
  return Math.random().toString(16).slice(2) + "-" + Date.now().toString(16);
}

function clamp01(x: number) {
  return Math.max(0, Math.min(1, x));
}

function LineSpark({
                     points,
                     accessor,
                     height = 120,
                   }: {
  points: DailyTrendPoint[];
  accessor: (p: DailyTrendPoint) => number | null | undefined;
  height?: number;
}) {
  const width = 640;
  const pad = 14;

  const vals = points
      .map((p) => accessor(p))
      .filter((v): v is number => typeof v === "number" && !Number.isNaN(v));

  if (vals.length < 2) {
    return (
        <div className="rounded-xl border bg-white p-4 text-sm text-zinc-600">
          Not enough data yet.
        </div>
    );
  }

  const norm = (v: number) => {
    if (v < 0 || v > 1) return clamp01((v + 1) / 2);
    return clamp01(v);
  };

  const ys = points.map((p) => {
    const v = accessor(p);
    return typeof v === "number" ? norm(v) : null;
  });

  const n = points.length;
  const xScale = (i: number) => pad + (i * (width - pad * 2)) / Math.max(1, n - 1);
  const yScale = (v01: number) => pad + (1 - v01) * (height - pad * 2);

  let d = "";
  for (let i = 0; i < n; i++) {
    const yv = ys[i];
    if (yv == null) continue;
    const x = xScale(i);
    const y = yScale(yv);
    d += d ? ` L ${x} ${y}` : `M ${x} ${y}`;
  }

  return (
      <div className="rounded-2xl border bg-white p-4">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-[120px] w-full">
          <path d={d} fill="none" stroke="currentColor" strokeWidth="3" className="text-zinc-900" />
        </svg>
        <div className="mt-2 flex justify-between text-xs text-zinc-600">
          <span>{points[0]?.day}</span>
          <span>{points[points.length - 1]?.day}</span>
        </div>
      </div>
  );
}

const LS_KEY_ONDEVICE_ONLY = "anchor_ondevice_only_v1";

export default function Home() {
  const [tab, setTab] = useState<"chat" | "trends">("chat");

  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [status, setStatus] = useState<"idle" | "recording" | "transcribing" | "reflecting">("idle");

  const [lastSafety, setLastSafety] = useState<Safety | null>(null);
  const [lastMode, setLastMode] = useState("neutral");

  // HYBRID toggle:
  // false = Default (server Whisper, best quality)
  // true  = On-device only (no audio upload, lower quality)
  const [onDeviceOnly, setOnDeviceOnly] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const recognizerRef = useRef<SpeechRecognizer | null>(null);
  const [liveTranscript, setLiveTranscript] = useState("");

  // Pause/duration tracking (cheap amplitude-based)
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const pauseStatsRef = useRef({ totalMs: 0, silentMs: 0, rafId: 0 as any });

  const [trendPoints, setTrendPoints] = useState<DailyTrendPoint[] | null>(null);
  const [trendsErr, setTrendsErr] = useState<string | null>(null);
  const [trendsLoading, setTrendsLoading] = useState(false);

  const canStart = useMemo(() => status === "idle" && !!sessionId, [status, sessionId]);
  const canStop = useMemo(() => status === "recording", [status]);

  useEffect(() => {
    // Load toggle
    try {
      const raw = localStorage.getItem(LS_KEY_ONDEVICE_ONLY);
      if (raw === "1") setOnDeviceOnly(true);
    } catch {}
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY_ONDEVICE_ONLY, onDeviceOnly ? "1" : "0");
    } catch {}
  }, [onDeviceOnly]);

  useEffect(() => {
    // Breathing animation (85% <-> 100% opacity)
    const style = document.createElement("style");
    style.innerHTML = `
      @keyframes anchorBreathe {
        0% { opacity: 0.85; }
        50% { opacity: 1; }
        100% { opacity: 0.85; }
      }
    `;
    document.head.appendChild(style);
    return () => {
      document.head.removeChild(style);
    };
  }, []);

  useEffect(() => {
    (async () => {
      const s = await createSession("free");
      setSessionId(s.session_id);
    })().catch((e) => {
      console.error(e);
      alert("Failed to create session. Check backend + CORS.");
    });
  }, []);

  useEffect(() => {
    if (tab !== "trends" || !sessionId) return;

    setTrendsErr(null);
    setTrendsLoading(true);
    setTrendPoints(null);

    getDailyTrends(sessionId, 30)
        .then((res) => setTrendPoints(res.points || []))
        .catch((e) => {
          console.error(e);
          setTrendsErr(String(e?.message || e));
        })
        .finally(() => setTrendsLoading(false));
  }, [tab, sessionId]);

  function pickMimeType() {
    const preferred = "audio/webm;codecs=opus";
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(preferred)) return preferred;

    const webm = "audio/webm";
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(webm)) return webm;

    return "";
  }

  function startPauseTracking(stream: MediaStream) {
    const AudioCtx = (window as any).AudioContext || (window as any).webkitAudioContext;
    if (!AudioCtx) return;

    const ctx = new AudioCtx();
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);

    audioCtxRef.current = ctx;
    analyserRef.current = analyser;

    const data = new Uint8Array(analyser.fftSize);
    pauseStatsRef.current.totalMs = 0;
    pauseStatsRef.current.silentMs = 0;

    const threshold = 0.02;

    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / data.length);

      pauseStatsRef.current.totalMs += 16;
      if (rms < threshold) pauseStatsRef.current.silentMs += 16;

      pauseStatsRef.current.rafId = requestAnimationFrame(tick);
    };

    pauseStatsRef.current.rafId = requestAnimationFrame(tick);
  }

  async function stopPauseTracking() {
    try {
      cancelAnimationFrame(pauseStatsRef.current.rafId);
    } catch {}

    const totalMs = pauseStatsRef.current.totalMs || 0;
    const silentMs = pauseStatsRef.current.silentMs || 0;

    try {
      await audioCtxRef.current?.close();
    } catch {}
    audioCtxRef.current = null;
    analyserRef.current = null;

    const pause_ratio = totalMs > 0 ? silentMs / totalMs : 0;
    return { duration_ms: totalMs, pause_ratio: Math.max(0, Math.min(1, pause_ratio)) };
  }

  async function startRecording() {
    try {
      setLiveTranscript("");
      recognizerRef.current = null;

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

      startPauseTracking(stream);

      // Only start on-device recognizer when toggle is enabled
      if (onDeviceOnly) {
        recognizerRef.current = createOnDeviceRecognizer();
        if (recognizerRef.current) {
          recognizerRef.current.onInterim = (t) => setLiveTranscript(t);
          recognizerRef.current.start();
        }
      }

      // Always record audio in memory (even in on-device-only mode)
      // This enables future “send anyway?” UX, and makes fallback easy to add later.
      const mimeType = pickMimeType();
      const mr = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);

      audioChunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mr.start();
      mediaRecorderRef.current = mr;
      setStatus("recording");
    } catch (e) {
      console.error(e);
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: "assistant",
          text: "I couldn’t access your microphone. Please allow mic permissions and try again.",
        },
      ]);
      setStatus("idle");
    }
  }

  async function stopRecording() {
    const mr = mediaRecorderRef.current;
    if (!mr) return;

    setStatus("transcribing");

    mr.onstop = async () => {
      try {
        mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      } catch {}
      mediaStreamRef.current = null;
      mediaRecorderRef.current = null;

      const pauseStats = await stopPauseTracking();
      const blob = new Blob(audioChunksRef.current, { type: mr.mimeType || "audio/webm" });

      // ============
      // Path A: On-device only (no audio upload)
      // ============
      if (onDeviceOnly) {
        let transcript = "";

        if (recognizerRef.current) {
          const out = await recognizerRef.current.stop();
          if (out.ok) transcript = normalizeSpaces(out.text);
        }

        if (!transcript) {
          setMessages((prev) => [
            ...prev,
            { id: uid(), role: "assistant", text: "I didn’t catch that clearly. Try again?" },
          ]);
          setStatus("idle");
          return;
        }

        try {
          setStatus("reflecting");

          const words = transcript.split(/\s+/).filter(Boolean).length;
          const duration_ms = pauseStats.duration_ms;
          const pause_ratio = pauseStats.pause_ratio;
          const speech_rate = duration_ms > 0 ? words / (duration_ms / 1000) : undefined;

          setMessages((prev) => [...prev, { id: uid(), role: "user", text: transcript }]);

          const res = await ingestTurn(sessionId, {
            input_mode: "voice",
            transcript_text: transcript,
            transcript_confidence: null,
            speech_features: { duration_ms, speech_rate, pause_ratio },
            stt_provider_used: "on_device",
            fallback_used: false,
            client_latency_ms: { record_ms: duration_ms, stt_ms: undefined },
          });

          setLastSafety(res.input_safety);
          setLastMode((res.analysis?.mode as string) || "neutral");
          setMessages((prev) => [...prev, { id: uid(), role: "assistant", text: res.assistant_text }]);
        } catch (e) {
          console.error(e);
          setMessages((prev) => [
            ...prev,
            { id: uid(), role: "assistant", text: "Something went wrong while processing your voice. Try again?" },
          ]);
        } finally {
          setStatus("idle");
        }

        return;
      }

      // ============
      // Path B: Default server Whisper (best quality)
      // ============
      try {
        setStatus("reflecting");

        if (!blob || blob.size < 4000) {
          setMessages((prev) => [
            ...prev,
            { id: uid(), role: "assistant", text: "I didn’t catch any audio. Try again?" },
          ]);
          setStatus("idle");
          return;
        }

        const res = await ingestTurnAudioFallback(sessionId, blob);

        const finalTranscript = normalizeSpaces(res.transcript || "");
        if (finalTranscript) {
          setMessages((prev) => [...prev, { id: uid(), role: "user", text: finalTranscript }]);
        }

        setLastSafety(res.input_safety);
        setLastMode((res.analysis?.mode as string) || "neutral");
        setMessages((prev) => [...prev, { id: uid(), role: "assistant", text: res.assistant_text }]);
      } catch (e) {
        console.error(e);
        setMessages((prev) => [
          ...prev,
          { id: uid(), role: "assistant", text: "Something went wrong while processing your voice. Try again?" },
        ]);
      } finally {
        setStatus("idle");
      }
    };

    try {
      mr.stop();
    } catch {
      setStatus("idle");
    }
  }

  return (
      <div className="min-h-screen bg-zinc-50 px-6 py-10 text-zinc-900">
        <div className="mx-auto w-full max-w-3xl">
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900">Anchor (voice)</h1>

          <div className="mt-1 text-sm text-zinc-800">
            Session: <span className="font-mono text-zinc-900">{sessionId || "creating..."}</span>
          </div>

          {/* Privacy / STT mode toggle */}
          <div className="mt-4 rounded-2xl border bg-white p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold text-zinc-900">Speech-to-text mode</div>
                <div className="mt-1 text-sm text-zinc-600">
                  Default uses <span className="font-medium text-zinc-900">Anchor’s server STT</span> for best punctuation and question detection.
                  <br />
                  <span className="font-medium text-zinc-900">On-device only</span> keeps audio on your device but may be less accurate.
                </div>
              </div>

              <label className="flex items-center gap-3 select-none">
                <span className="text-sm text-zinc-700">On-device only</span>
                <button
                    type="button"
                    onClick={() => setOnDeviceOnly((v) => !v)}
                    className={[
                      "relative inline-flex h-7 w-12 items-center rounded-full transition",
                      onDeviceOnly ? "bg-zinc-900" : "bg-zinc-300",
                    ].join(" ")}
                    aria-pressed={onDeviceOnly}
                >
                <span
                    className={[
                      "inline-block h-5 w-5 transform rounded-full bg-white transition",
                      onDeviceOnly ? "translate-x-6" : "translate-x-1",
                    ].join(" ")}
                />
                </button>
              </label>
            </div>
          </div>

          {/* Tabs */}
          <div className="mt-6 inline-flex rounded-2xl border bg-white p-1">
            <button
                onClick={() => setTab("chat")}
                className={[
                  "px-4 py-2 text-sm font-medium rounded-xl",
                  tab === "chat" ? "bg-zinc-900 text-white" : "text-zinc-700",
                ].join(" ")}
            >
              Chat
            </button>
            <button
                onClick={() => setTab("trends")}
                className={[
                  "px-4 py-2 text-sm font-medium rounded-xl",
                  tab === "trends" ? "bg-zinc-900 text-white" : "text-zinc-700",
                ].join(" ")}
            >
              Trends
            </button>
          </div>

          {tab === "chat" ? (
              <>
                <div className="mt-8 space-y-4">
                  {messages.length === 0 ? (
                      <div className="rounded-2xl border bg-white p-6 text-zinc-700">
                        Press <span className="font-medium text-zinc-900">Start recording</span> to begin.
                      </div>
                  ) : (
                      messages.map((m) => (
                          <div
                              key={m.id}
                              className={[
                                "rounded-2xl border p-4",
                                m.role === "user" ? "bg-white text-zinc-900" : "bg-zinc-900 text-zinc-50",
                              ].join(" ")}
                          >
                            <div className="text-xs font-semibold uppercase tracking-wide opacity-70">{m.role}</div>
                            <div className="mt-2 whitespace-pre-wrap leading-7">{m.text}</div>
                          </div>
                      ))
                  )}

                  {/* Live interim transcript only in on-device-only mode */}
                  {onDeviceOnly && status === "recording" && liveTranscript ? (
                      <div className="rounded-2xl border bg-white p-4 text-sm text-zinc-700">
                        <div className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                          live transcript (on-device)
                        </div>
                        <div className="mt-2">{liveTranscript}</div>
                      </div>
                  ) : null}

                  {/* Ephemeral assistant bubble (NOT persisted in messages) */}
                  {status !== "idle" ? (
                      <div className="rounded-2xl border bg-zinc-900 text-zinc-50 p-4">
                        <div className="text-xs font-semibold uppercase tracking-wide opacity-70">assistant</div>
                        <div
                            className="mt-2 whitespace-pre-wrap leading-7"
                            style={{ animation: "anchorBreathe 2.2s ease-in-out infinite" }}
                        >
                          {status === "recording"
                              ? "Listening carefully…"
                              : "Reflecting on what you shared…"}
                        </div>
                      </div>
                  ) : null}
                </div>

                <div className="mt-6 rounded-2xl border bg-white p-4">
                  <div className="mb-3 flex gap-3">
                    <button
                        disabled={!canStart}
                        onClick={startRecording}
                        className="inline-flex h-11 items-center justify-center rounded-xl bg-zinc-900 px-5 text-sm font-medium text-white disabled:opacity-50"
                    >
                      Start recording
                    </button>

                    <button
                        disabled={!canStop}
                        onClick={stopRecording}
                        className="inline-flex h-11 items-center justify-center rounded-xl bg-red-600 px-5 text-sm font-medium text-white disabled:opacity-50"
                    >
                      Stop
                    </button>
                  </div>

                  <div className="text-xs text-zinc-800">
                    mode: <span className="font-medium text-zinc-900">{lastMode}</span> · safety:{" "}
                    <span className="font-medium text-zinc-900">{lastSafety?.label || "unknown"}</span> · status:{" "}
                    <span className="font-medium text-zinc-900">{status}</span> · stt:{" "}
                    <span className="font-medium text-zinc-900">{onDeviceOnly ? "on-device" : "server"}</span>
                  </div>
                </div>
              </>
          ) : (
              <>
                <div className="mt-8 space-y-4">
                  <div className="rounded-2xl border bg-white p-6">
                    <div className="text-sm font-semibold text-zinc-900">Last 30 days</div>
                    <div className="mt-1 text-sm text-zinc-600">
                      Derived scores only. No in-chat mood notifications. Loads only when you open this tab.
                    </div>
                  </div>

                  {trendsLoading ? (
                      <div className="rounded-2xl border bg-white p-6 text-sm text-zinc-600">Loading trends…</div>
                  ) : trendsErr ? (
                      <div className="rounded-2xl border bg-white p-6 text-sm text-red-700">{trendsErr}</div>
                  ) : (
                      <>
                        <div className="grid gap-4">
                          <div>
                            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-600">Valence</div>
                            <LineSpark points={trendPoints || []} accessor={(p) => (p.valence_mean ?? null) as any} />
                          </div>
                          <div>
                            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-600">Arousal</div>
                            <LineSpark points={trendPoints || []} accessor={(p) => (p.arousal_mean ?? null) as any} />
                          </div>
                          <div>
                            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-600">Confidence</div>
                            <LineSpark points={trendPoints || []} accessor={(p) => (p.confidence_mean ?? null) as any} />
                          </div>
                          <div>
                            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-600">Extremeness</div>
                            <LineSpark points={trendPoints || []} accessor={(p) => (p.extremeness_mean ?? null) as any} />
                          </div>
                        </div>

                        <div className="rounded-2xl border bg-white p-4">
                          <div className="text-sm font-semibold text-zinc-900">Daily table</div>
                          <div className="mt-3 overflow-x-auto">
                            <table className="w-full text-sm">
                              <thead>
                              <tr className="text-left text-zinc-600">
                                <th className="py-2 pr-3">Day</th>
                                <th className="py-2 pr-3">N</th>
                                <th className="py-2 pr-3">Valence</th>
                                <th className="py-2 pr-3">Arousal</th>
                                <th className="py-2 pr-3">Confidence</th>
                                <th className="py-2 pr-3">Extremeness</th>
                              </tr>
                              </thead>
                              <tbody>
                              {(trendPoints || []).map((p) => (
                                  <tr key={p.day} className="border-t">
                                    <td className="py-2 pr-3 font-mono text-zinc-900">{p.day}</td>
                                    <td className="py-2 pr-3 text-zinc-900">{p.n}</td>
                                    <td className="py-2 pr-3 text-zinc-900">{p.valence_mean?.toFixed?.(2) ?? "-"}</td>
                                    <td className="py-2 pr-3 text-zinc-900">{p.arousal_mean?.toFixed?.(2) ?? "-"}</td>
                                    <td className="py-2 pr-3 text-zinc-900">{p.confidence_mean?.toFixed?.(2) ?? "-"}</td>
                                    <td className="py-2 pr-3 text-zinc-900">{p.extremeness_mean?.toFixed?.(2) ?? "-"}</td>
                                  </tr>
                              ))}
                              {(trendPoints || []).length === 0 ? (
                                  <tr>
                                    <td className="py-3 text-zinc-600" colSpan={6}>
                                      No trend data yet. Do a few turns first.
                                    </td>
                                  </tr>
                              ) : null}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      </>
                  )}
                </div>
              </>
          )}
        </div>
      </div>
  );
}
