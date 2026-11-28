import React, { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import "./fonts";
import "./quick.css";
import { api, apiStream } from "./lib/api";

// The mini Recall panel: opened by the mark or by the ask shortcut, from any
// app, without taking focus away from it until you type (ADR 0015).

type Source = {
  n: number;
  id: string;
  app_name: string;
  window_title: string;
  url: string;
  created_at: string;
  snippet: string;
  kind?: "memory" | "activity" | "episode";
};

type RecallEvent =
  | { type: "meta"; sources: Source[] }
  | { type: "token"; text: string }
  | { type: "done"; answer: string; sources: Source[] };

function when(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
}

function Quick() {
  const input = useRef<HTMLInputElement>(null);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<string | null>(null);
  const [ready, setReady] = useState(true);

  function close() {
    invoke("hide_quick").catch(() => {});
  }

  async function refreshOnOpen() {
    setNote(null);
    setError(null);
    setConnection(await invoke<string | null>("latest_connection").catch(() => null));
    const status = await invoke<{ state: string }>("engine_status").catch(() => ({ state: "starting" }));
    setReady(status.state === "ready");
    requestAnimationFrame(() => {
      input.current?.focus();
      input.current?.select();
    });
  }

  useEffect(() => {
    refreshOnOpen();
    const offs = [
      listen("quick-open", () => refreshOnOpen()),
      listen<string>("connection", (e) => setConnection(e.payload)),
      // A click anywhere else closes the panel, like Spotlight.
      getCurrentWindow().onFocusChanged(({ payload: focused }) => {
        if (!focused) close();
      }),
    ];
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      offs.forEach((p) => p.then((f) => f()));
    };
  }, []);

  async function ask() {
    const text = question.trim();
    if (!text || busy) return;
    setAsked(text);
    setAnswer("");
    setSources([]);
    setNote(null);
    setError(null);
    setBusy(true);
    try {
      await apiStream<RecallEvent>("/recall", { question: text }, (event) => {
        if (event.type === "meta") setSources(event.sources);
        else if (event.type === "token") setAnswer((a) => a + event.text);
        else if (event.type === "done") {
          setAnswer(event.answer);
          setSources(event.sources);
        }
      });
    } catch {
      setError("Engram could not answer just now. Is it still starting?");
    } finally {
      setBusy(false);
    }
  }

  async function saveNote() {
    const text = question.trim();
    if (!text) return;
    try {
      await api("/memories", { method: "POST", body: { content: text } });
      setQuestion("");
      setAsked(null);
      setAnswer("");
      setSources([]);
      setNote("Saved as a note.");
    } catch {
      setError("Could not save the note. Is Engram still starting?");
    }
  }

  const shown = sources.slice(0, 4);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden rounded-[14px] border border-border bg-canvas font-sans text-ink">
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 fill-accent" aria-hidden="true">
          <path
            opacity="0.85"
            d="M3 15.2 C 6.5 14.6, 9.5 11.6, 13 10.4 C 15.6 9.5, 17.8 9.2, 19.6 9.6 C 21.2 10 21.2 12 19.6 12.4 C 17.6 12.9, 15.6 12.6, 13.3 13.2 C 9.8 14.1, 6.6 15.6, 3 15.4 Z"
          />
        </svg>
        <input
          ref={input}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.metaKey) {
              e.preventDefault();
              saveNote();
            } else if (e.key === "Enter") {
              e.preventDefault();
              ask();
            }
          }}
          placeholder="Ask your memory, or type a note"
          aria-label="Ask Engram. Return answers; Command-Return saves as a note."
          className="flex-1 bg-transparent text-lg outline-none placeholder:text-ink-muted"
        />
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 text-sm" aria-live="polite">
        {!ready && <p className="text-ink-muted">Engram is still starting. Try again in a moment.</p>}
        {error && <p className="text-red-700">{error}</p>}
        {note && <p className="text-accent">{note}</p>}

        {asked && (
          <div className="mb-3">
            <p className="whitespace-pre-wrap leading-relaxed">
              {answer || (busy ? <span className="text-ink-muted">Thinking...</span> : null)}
            </p>
            {shown.length > 0 && (
              <ul className="mt-3 flex flex-col gap-1.5" aria-label="Sources">
                {shown.map((s) => (
                  <li key={`${s.kind ?? "memory"}-${s.id}`} className="rounded-md border border-border bg-surface px-2.5 py-1.5">
                    <p className="truncate text-xs text-ink-muted">
                      [{s.n}] {s.kind === "episode" ? "Episode" : s.kind === "activity" ? "Activity" : s.app_name}
                      {s.window_title ? ` · ${s.window_title}` : ""} · {when(s.created_at)}
                    </p>
                    {s.snippet && <p className="line-clamp-1 text-xs">{s.snippet}</p>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {!asked && connection && (
          <div className="rounded-md border border-[#e0b77a] bg-[#fbf3e6] px-3 py-2">
            <p className="text-xs font-medium uppercase tracking-wide text-[#8a5a17]">Latest connection</p>
            <p className="mt-1 text-sm">{connection}</p>
          </div>
        )}

        {!asked && !connection && ready && !note && (
          <p className="text-ink-muted">
            Try "What was I reading this morning?" or "Where did I see the pricing page?"
          </p>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-border px-4 py-2 text-xs text-ink-muted">
        <span>↩ ask · ⌘↩ save as note · esc close</span>
        <button className="underline-offset-2 hover:text-ink hover:underline" onClick={() => invoke("open_main", { page: "recall" })}>
          Open Engram
        </button>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Quick />
  </React.StrictMode>,
);
