"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Safety = { label: "allow" | "block" | "review"; reasons: string[]; meta: Record<string, any> };

type FinalizeResponse = {
  turn_id: string;
  transcript: string;
  assistant_text: string;
  input_safety: Safety;
  fallback_used: boolean;
  analysis?: Record<string, any> | null;
};

type AudioUploadResponse = {
  transcript: string;
  confidence?: number | null;
  content_type?: string | null;
  bytes?: number | null;
};

type Msg = {
  id: string;
  role: "user" | "assistant";
  text: string;
};

function uid() {
  return Math.random().toString(16).slice(2) + "-" + Date.now().toString(16);
}

export default function Home() {
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [status, setStatus] = useState<"idle" | "recording" | "sending">("idle");

  const [lastSafety, setLastSafety] = useState<Safety | null>(null);
  const [lastMode, setLastMode] = useState("neutral");

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const canStart = useMemo(() => status === "idle" && !!sessionId, [status, sessionId]);
  const canStop = useMemo(() => status === "recording", [status]);

  useEffect(() => {
    const run = async () => {
      const res = await fetch(`${API_BASE}/v1/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier: "free" }),
      });

      if (!res.ok) throw new Error("Failed to create session");
      const data = await res.json();
      setSessionId(data.session_id);
    };

    run().catch((e) => {
      console.error(e);
      alert("Failed to create session. Check backend + CORS.");
    });
  }, [API_BASE]);

  function pickMimeType() {
    // Prefer opus webm if supported
    const preferred = "audio/webm;codecs=opus";
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(preferred)) return preferred;

    // Fallback webm
    const webm = "audio/webm";
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(webm)) return webm;

    // Let browser pick if nothing matches
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
      // (1) Stop mic tracks so mic isn't held open
      try {
        mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      } catch {}
      mediaStreamRef.current = null;
      mediaRecorderRef.current = null;

      const blob = new Blob(audioChunksRef.current, { type: mr.mimeType || "audio/webm" });

      // (2) Empty/tiny audio guard
      if (!blob || blob.size < 4000) {
        setMessages((prev) => [
          ...prev,
          { id: uid(), role: "assistant", text: "I didn’t catch any audio. Try speaking a little louder and press Stop again." },
        ]);
        setStatus("idle");
        return;
      }

      try {
        // start turn
        const startRes = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/start`, { method: "POST" });
        if (!startRes.ok) throw new Error("start_turn failed");
        const start = await startRes.json();
        const turnId = start.turn_id as string;

        // upload audio
        const fd = new FormData();
        fd.append("file", blob, "voice.webm");

        const audioRes = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/${turnId}/audio`, {
          method: "POST",
          body: fd,
        });

        if (!audioRes.ok) {
          const detail = await audioRes.text().catch(() => "");
          throw new Error(`audio upload failed: ${audioRes.status} ${detail}`);
        }

        const audio: AudioUploadResponse = await audioRes.json();
        const transcript = (audio.transcript || "").trim();

        if (!transcript) {
          setMessages((prev) => [
            ...prev,
            { id: uid(), role: "assistant", text: "I had trouble hearing that. Try again?" },
          ]);
          setStatus("idle");
          return;
        }

        // show transcript as user message
        setMessages((prev) => [...prev, { id: uid(), role: "user", text: transcript }]);

        // send transcript as chunk
        const chunkRes = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/${turnId}/chunks`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chunk_index: 0, text: transcript, confidence: audio.confidence ?? 0.9 }),
        });
        if (!chunkRes.ok) throw new Error("append_chunk failed");

        // finalize
        const finRes = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/${turnId}/finalize`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ client_turn_done: true }),
        });
        if (!finRes.ok) throw new Error("finalize failed");

        const fin: FinalizeResponse = await finRes.json();

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
        setStatus("idle");
      }
    };

    // stop triggers onstop callback
    try {
      mr.stop();
    } catch {
      setStatus("idle");
    }
  }

  return (
      <div className="min-h-screen bg-zinc-50 px-6 py-10 text-zinc-900">
        <div className="mx-auto w-full max-w-3xl">
          {/* Darker title */}
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-800">Anchor (voice)</h1>

          <div className="mt-1 text-sm text-zinc-700">
            Session: <span className="font-mono text-zinc-800">{sessionId || "creating..."}</span>
          </div>

          {/* Conversation */}
          <div className="mt-8 space-y-4">
            {messages.length === 0 ? (
                <div className="rounded-2xl border bg-white p-6 text-zinc-600">
                  Press <span className="font-medium text-zinc-800">Start recording</span> to begin.
                </div>
            ) : (
                messages.map((m) => (
                    <div
                        key={m.id}
                        className={[
                          "rounded-2xl border p-4",
                          m.role === "user" ? "bg-white text-zinc-800" : "bg-zinc-900 text-zinc-50",
                        ].join(" ")}
                    >
                      <div className="text-xs font-semibold uppercase tracking-wide opacity-70">{m.role}</div>
                      {/* Darker user text (no super-light gray) */}
                      <div className="mt-2 whitespace-pre-wrap leading-7">{m.text}</div>
                    </div>
                ))
            )}
          </div>

          {/* Controls */}
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

            <div className="text-xs text-zinc-700">
              mode: <span className="font-medium text-zinc-900">{lastMode}</span> · safety:{" "}
              <span className="font-medium text-zinc-900">{lastSafety?.label || "unknown"}</span> · status:{" "}
              <span className="font-medium text-zinc-900">{status}</span>
            </div>
          </div>
        </div>
      </div>
  );
}
