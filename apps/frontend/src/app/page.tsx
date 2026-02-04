"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  appendChunk,
  createSession,
  finalizeTurn,
  getDailyTrends,
  startTurn,
  uploadAudio,
  type DailyTrendPoint,
  type Safety,
} from "../lib/api";

type Msg = { id: string; role: "user" | "assistant"; text: string };

function uid() {
  return Math.random().toString(16).slice(2) + "-" + Date.now().toString(16);
}

function clamp01(x: number) {
  return Math.max(0, Math.min(1, x));
}

/**
 * Prevents a UI indicator from flashing for ultra-fast operations.
 * Example: delay 150ms so it only appears if it actually takes a moment.
 */
function useDelayedFlag(flag: boolean, delayMs = 150) {
  const [show, setShow] = useState(false);

  useEffect(() => {
    let t: any;
    if (flag) {
      t = setTimeout(() => setShow(true), delayMs);
    } else {
      setShow(false);
    }
    return () => clearTimeout(t);
  }, [flag, delayMs]);

  return show;
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
    return <div className="rounded-xl border bg-white p-4 text-sm text-zinc-600">Not enough data yet.</div>;
  }

  // For valence [-1,1], normalize to [0,1] for plotting. For others already [0,1].
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

export default function Home() {
  const [tab, setTab] = useState<"chat" | "trends">("chat");

  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [status, setStatus] = useState<"idle" | "recording" | "sending">("idle");

  const [lastSafety, setLastSafety] = useState<Safety | null>(null);
  const [lastMode, setLastMode] = useState("neutral");

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const [trendPoints, setTrendPoints] = useState<DailyTrendPoint[] | null>(null);
  const [trendsErr, setTrendsErr] = useState<string | null>(null);
  const [trendsLoading, setTrendsLoading] = useState(false);

  // NEW: processing-phase flags
  const [isListening, setIsListening] = useState(false);   // “Listening carefully…”
  const [isReflecting, setIsReflecting] = useState(false); // “Reflecting on what you shared…”

  // avoid flicker
  const showListening = useDelayedFlag(isListening, 150);
  const showReflecting = useDelayedFlag(isReflecting, 150);

  const processingText =
      showListening ? "Listening carefully…" : showReflecting ? "Reflecting on what you shared…" : null;

  const canStart = useMemo(() => status === "idle" && !!sessionId, [status, sessionId]);
  const canStop = useMemo(() => status === "recording", [status]);

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

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;

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
        { id: uid(), role: "assistant", text: "I couldn’t access your microphone. Please allow mic permissions and try again." },
      ]);
      setStatus("idle");
    }
  }

  async function stopRecording() {
    const mr = mediaRecorderRef.current;
    if (!mr) return;

    setStatus("sending");

    mr.onstop = async () => {
      const resetIndicators = () => {
        setIsListening(false);
        setIsReflecting(false);
      };

      try {
        mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      } catch {}
      mediaStreamRef.current = null;
      mediaRecorderRef.current = null;

      const blob = new Blob(audioChunksRef.current, { type: mr.mimeType || "audio/webm" });

      if (!blob || blob.size < 4000) {
        setMessages((prev) => [
          ...prev,
          { id: uid(), role: "assistant", text: "I didn’t catch any audio. Try speaking a little louder and press Stop again." },
        ]);
        resetIndicators();
        setStatus("idle");
        return;
      }

      try {
        const start = await startTurn(sessionId);
        const turnId = start.turn_id;

        // Phase 1: STT/transcript processing
        setIsListening(true);
        setIsReflecting(false);

        const audio = await uploadAudio(sessionId, turnId, blob);
        const transcript = (audio.transcript || "").trim();

        if (!transcript) {
          setMessages((prev) => [...prev, { id: uid(), role: "assistant", text: "I had trouble hearing that. Try again?" }]);
          resetIndicators();
          setStatus("idle");
          return;
        }

        setMessages((prev) => [...prev, { id: uid(), role: "user", text: transcript }]);

        await appendChunk(sessionId, turnId, transcript, (audio.confidence ?? 0.9) as number);

        // Phase 2: response formulation
        setIsListening(false);
        setIsReflecting(true);

        const fin = await finalizeTurn(sessionId, turnId);

        setLastSafety(fin.input_safety);
        setLastMode((fin.analysis?.mode as string) || "neutral");

        setMessages((prev) => [...prev, { id: uid(), role: "assistant", text: fin.assistant_text }]);
      } catch (e) {
        console.error(e);
        setMessages((prev) => [
          ...prev,
          { id: uid(), role: "assistant", text: "Something went wrong while processing your voice. Try again?" },
        ]);
      } finally {
        resetIndicators();
        setStatus("idle");
      }
    };

    try {
      mr.stop();
    } catch {
      setIsListening(false);
      setIsReflecting(false);
      setStatus("idle");
    }
  }

  return (
      <div className="min-h-screen bg-zinc-50 px-6 py-10 text-zinc-900">
        {/* Breathing animation (85% <-> 100% opacity) */}
        <style jsx global>{`
        @keyframes breath {
          0% {
            opacity: 0.85;
          }
          50% {
            opacity: 1;
          }
          100% {
            opacity: 0.85;
          }
        }
      `}</style>

        <div className="mx-auto w-full max-w-3xl">
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900">Anchor (voice)</h1>

          <div className="mt-1 text-sm text-zinc-800">
            Session: <span className="font-mono text-zinc-900">{sessionId || "creating..."}</span>
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

                  {/* NEW: In-chat assistant processing bubble (not persisted) */}
                  {processingText ? (
                      <div className="rounded-2xl border bg-zinc-900 text-zinc-50 p-4">
                        <div className="text-xs font-semibold uppercase tracking-wide opacity-70">assistant</div>
                        <div
                            className="mt-2 whitespace-pre-wrap leading-7"
                            style={{ animation: "breath 2.2s ease-in-out infinite" }}
                        >
                          {processingText}
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
                    <span className="font-medium text-zinc-900">{status}</span>
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
