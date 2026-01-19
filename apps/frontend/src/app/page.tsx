// src/app/page.tsx
"use client";

import { useEffect, useMemo, useState } from "react";

type Safety = { label: "allow" | "block" | "review"; reasons: string[]; meta: Record<string, any> };

type FinalizeResponse = {
  turn_id: string;
  transcript: string;
  assistant_text: string;
  input_safety: Safety;
  fallback_used: boolean;
  analysis?: Record<string, any> | null;
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

  const [sessionId, setSessionId] = useState<string>("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [status, setStatus] = useState<"idle" | "sending">("idle");

  const [lastSafety, setLastSafety] = useState<Safety | null>(null);
  const [lastMode, setLastMode] = useState<string>("neutral");

  useEffect(() => {
    // Create a session on first load
    const run = async () => {
      const res = await fetch(`${API_BASE}/v1/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier: "free" }), // <-- REQUIRED to avoid 422
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

  const canSend = useMemo(() => status !== "sending" && sessionId && input.trim().length > 0, [status, sessionId, input]);

  async function send() {
    if (!canSend) return;
    const text = input.trim();
    setInput("");
    setStatus("sending");

    // optimistic add user message
    const userMsg: Msg = { id: uid(), role: "user", text };
    setMessages((prev) => [...prev, userMsg]);

    try {
      // start turn
      const startRes = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/start`, { method: "POST" });
      if (!startRes.ok) throw new Error("start_turn failed");
      const start = await startRes.json();
      const turnId = start.turn_id as string;

      // upload single chunk (you can later switch to multi-chunk)
      const chunkRes = await fetch(`${API_BASE}/v1/sessions/${sessionId}/turns/${turnId}/chunks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chunk_index: 0, text, confidence: 0.9 }),
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

      const assistantMsg: Msg = { id: uid(), role: "assistant", text: fin.assistant_text };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e) {
      console.error(e);
      setMessages((prev) => [
        ...prev,
        { id: uid(), role: "assistant", text: "Something went wrong on my side. Can you try sending that again?" },
      ]);
    } finally {
      setStatus("idle");
    }
  }

  return (
      <div className="min-h-screen bg-zinc-50 px-6 py-10 text-zinc-900">
        <div className="mx-auto w-full max-w-3xl">
          <h1 className="text-3xl font-semibold tracking-tight">Anchor (v1)</h1>
          <div className="mt-1 text-sm text-zinc-500">
            Session: <span className="font-mono">{sessionId || "creating..."}</span>
          </div>

          {/* Conversation */}
          <div className="mt-8 space-y-4">
            {messages.length === 0 ? (
                <div className="rounded-2xl border bg-white p-6 text-zinc-500">
                  Say something to start the conversation.
                </div>
            ) : (
                messages.map((m) => (
                    <div
                        key={m.id}
                        className={[
                          "rounded-2xl border p-4",
                          m.role === "user" ? "bg-white" : "bg-zinc-900 text-zinc-50",
                        ].join(" ")}
                    >
                      <div className="text-xs font-semibold uppercase tracking-wide opacity-70">{m.role}</div>
                      <div className="mt-2 whitespace-pre-wrap leading-7">{m.text}</div>
                    </div>
                ))
            )}
          </div>

          {/* Input at bottom */}
          <div className="mt-6 rounded-2xl border bg-white p-4">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-zinc-600">mode:</span>
              <span className="rounded-full bg-zinc-100 px-3 py-1 text-xs">{lastMode}</span>
              <span className="ml-2 text-xs font-medium text-zinc-600">safety:</span>
              <span className="rounded-full bg-zinc-100 px-3 py-1 text-xs">{lastSafety?.label || "unknown"}</span>
            </div>

            <label className="mt-4 block text-sm font-medium text-zinc-700">Say something</label>
            <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="e.g. i feel anxious and sad"
                className="mt-2 h-28 w-full resize-none rounded-xl border px-4 py-3 outline-none focus:ring-2 focus:ring-zinc-300"
            />
            <button
                onClick={send}
                disabled={!canSend}
                className="mt-3 inline-flex h-11 items-center justify-center rounded-xl bg-zinc-900 px-5 text-sm font-medium text-white disabled:opacity-50"
            >
              {status === "sending" ? "Sending..." : "Send"}
            </button>
          </div>
        </div>
      </div>
  );
}
