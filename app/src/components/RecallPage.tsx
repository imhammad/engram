import { useEffect, useRef, useState } from "react";
import { api, apiStream } from "../lib/api";
import RecapCard from "./RecapCard";

type SourceCard = {
  n: number;
  id: string;
  app_name: string;
  window_title: string;
  url: string;
  created_at: string;
  snippet: string;
  kind?: "memory" | "activity" | "episode";
};

type AppTime = { app_name: string; seconds: number };

type RecallEvent =
  | { type: "meta"; route: string; period: string | null; sources: SourceCard[]; breakdown?: AppTime[] }
  | { type: "token"; text: string }
  | {
      type: "done";
      route: string;
      answer: string;
      sources: SourceCard[];
      breakdown?: AppTime[];
      dropped_sentences: number;
    };

type HistoryItem = {
  id: string;
  created_at: string;
  question: string;
  answer: string;
  route: string;
  sources: SourceCard[];
};

const EXAMPLES = [
  "What did I work on yesterday?",
  "How long was I in Chrome today?",
  "What was that EEG article about?",
  "Which apps did I use this week?",
];

function formatDuration(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
}

function when(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Show [n] citations as small superscript markers. */
function Answer({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-wrap text-lg leading-relaxed text-ink">
      {parts.map((part, i) =>
        /^\[\d+\]$/.test(part) ? (
          <sup key={i} className="ml-0.5 font-mono text-xs text-accent">
            {part}
          </sup>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </p>
  );
}

function Source({ source }: { source: SourceCard }) {
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState<string | null>(null);
  const [kept, setKept] = useState(false);
  const isMemory = (source.kind ?? "memory") === "memory";

  async function keep(e: React.MouseEvent) {
    e.stopPropagation();
    await api(`/memories/${source.id}/keep`, { method: "POST", body: { pinned: !kept } });
    setKept(!kept);
  }

  async function toggle() {
    if (!isMemory) {
      setOpen(!open);
      return;
    }
    if (!open && full === null) {
      try {
        const memory = await api<{ content: string }>(`/memories/${source.id}`);
        setFull(memory.content);
      } catch {
        setFull(source.snippet);
      }
    }
    setOpen(!open);
  }

  return (
    <button
      onClick={toggle}
      className="flex w-full gap-3 rounded-md border border-border bg-surface p-3 text-left transition-colors hover:border-accent/40"
    >
      <span className="font-mono text-xs text-accent">[{source.n}]</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-ink">
          {source.window_title || source.app_name}
        </span>
        <span className="block truncate text-xs text-ink-muted">
          {source.kind === "episode" ? "Episode" : source.kind === "activity" ? "Activity" : source.app_name}
          {" · "}
          {when(source.created_at)}
          {source.url && <> · {source.url}</>}
        </span>
        <span
          className={`mt-2 block whitespace-pre-wrap text-xs leading-relaxed text-ink-muted ${
            open ? "" : "line-clamp-2"
          }`}
        >
          {open && isMemory ? full : source.snippet}
        </span>
      </span>
      {isMemory && (
        <span
          role="button"
          onClick={keep}
          title="Keep this memory so it never fades"
          className={`shrink-0 self-start text-xs ${kept ? "font-medium text-accent" : "text-ink-muted hover:text-ink"}`}
        >
          {kept ? "Kept" : "Keep"}
        </span>
      )}
    </button>
  );
}

export default function RecallPage() {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [streamed, setStreamed] = useState("");
  const [final, setFinal] = useState<Extract<RecallEvent, { type: "done" }> | null>(null);
  const [pending, setPending] = useState<SourceCard[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const input = useRef<HTMLInputElement>(null);

  async function loadHistory() {
    setHistory(await api<HistoryItem[]>("/recall/history?limit=10"));
  }

  useEffect(() => {
    input.current?.focus();
    loadHistory();
  }, []);

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setQuestion(text);
    setAsked(text);
    setStreamed("");
    setFinal(null);
    setPending([]);
    setError(null);
    setBusy(true);
    try {
      await apiStream<RecallEvent>("/recall", { question: text }, (event) => {
        if (event.type === "meta") setPending(event.sources);
        else if (event.type === "token") setStreamed((s) => s + event.text);
        else if (event.type === "done") setFinal(event);
      });
      loadHistory();
    } catch {
      setError("Engram could not answer just now. Is the engine still running?");
    } finally {
      setBusy(false);
    }
  }

  async function clearHistory() {
    await api("/recall/history", { method: "DELETE" });
    setHistory([]);
  }

  const answer = final?.answer ?? streamed;
  const sources = final ? final.sources : pending;
  const breakdown = final?.breakdown ?? [];
  const maxSeconds = breakdown.length ? breakdown[0].seconds : 1;

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-8 py-12">
        <div>
          <h2 className="mb-1 text-2xl font-semibold text-ink">Recall</h2>
          <p className="text-sm text-ink-muted">
            Ask about anything you saw, read or did. Answers come only from
            your own memories, with sources, and never leave this Mac.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
          className="flex gap-2"
        >
          <input
            ref={input}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="What was that article about the seizure study?"
            className="flex-1 rounded-lg border border-border bg-surface px-5 py-4 text-lg text-ink shadow-sm outline-none placeholder:text-ink-muted/70 focus:border-accent"
          />
          <button
            type="submit"
            disabled={busy || !question.trim()}
            className="rounded-lg bg-accent px-6 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-40"
          >
            {busy ? "Recalling..." : "Ask"}
          </button>
        </form>

        {!asked && <RecapCard />}

        {!asked && (
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                onClick={() => ask(example)}
                className="rounded-full border border-border px-3 py-1.5 text-sm text-ink-muted hover:border-accent/40 hover:text-ink"
              >
                {example}
              </button>
            ))}
          </div>
        )}

        {asked && (
          <section className="flex flex-col gap-5 border-l-2 border-accent pl-6">
            <p className="text-sm font-medium text-ink-muted">{asked}</p>
            {answer ? (
              <Answer text={answer} />
            ) : (
              busy && <p className="text-sm text-ink-muted">Looking through your memories...</p>
            )}
            {error && <p className="text-sm text-red-600">{error}</p>}
            {final && final.dropped_sentences > 0 && (
              <p className="text-xs text-ink-muted">
                {final.dropped_sentences} sentence
                {final.dropped_sentences > 1 ? "s were" : " was"} left out because
                {final.dropped_sentences > 1 ? " they" : " it"} cited no source.
              </p>
            )}

            {breakdown.length > 0 && (
              <div className="flex flex-col gap-2">
                {breakdown.slice(0, 5).map((app) => (
                  <div key={app.app_name} className="text-sm">
                    <div className="mb-1 flex justify-between">
                      <span className="text-ink">{app.app_name}</span>
                      <span className="text-ink-muted">{formatDuration(app.seconds)}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-surface-muted">
                      <div
                        className="h-1.5 rounded-full bg-accent"
                        style={{ width: `${(app.seconds / maxSeconds) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {sources.length > 0 && (
              <div className="flex flex-col gap-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  Sources
                </p>
                {sources.map((s) => (
                  <Source key={s.id} source={s} />
                ))}
              </div>
            )}
          </section>
        )}

        {history.length > 0 && (
          <section className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Recent questions
              </p>
              <button onClick={clearHistory} className="text-xs text-ink-muted hover:text-red-600">
                Clear history
              </button>
            </div>
            <ul className="flex flex-col">
              {history.map((h) => (
                <li key={h.id}>
                  <button
                    onClick={() => ask(h.question)}
                    className="flex w-full justify-between gap-4 border-b border-border py-2 text-left text-sm hover:text-accent"
                  >
                    <span className="truncate text-ink">{h.question}</span>
                    <span className="shrink-0 text-xs text-ink-muted">{when(h.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
