import { useEffect, useState } from "react";
import { api } from "../lib/api";

type AppTime = { app_name: string; seconds: number };
type Episode = {
  id: string;
  title: string;
  summary: string;
  started_at: string;
  ended_at: string;
  focused_seconds: number;
};
type OpenLoop = { id: string; text: string; app_name: string; created_at: string };
type Recap = {
  day: string;
  consolidated: boolean;
  summary?: string;
  stats?: { focused_seconds: number; top_apps: AppTime[] };
  episodes?: Episode[];
  open_loops: OpenLoop[];
};

const DISMISS_KEY = "engram.recapDismissedFor";

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function duration(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} min`;
  return m % 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${Math.floor(m / 60)} h`;
}

function plain(text: string): string {
  return text.replace(/\s*\[\d+\]/g, "");
}

/** Yesterday at a glance, shown on the first visit of the day. */
export default function RecapCard() {
  const [recap, setRecap] = useState<Recap | null>(null);
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    api<Recap>("/recap").then((r) => {
      setRecap(r);
      setHidden(localStorage.getItem(DISMISS_KEY) === r.day);
    });
  }, []);

  if (!recap || hidden || !recap.consolidated || !recap.episodes?.length) return null;

  const dayName = new Date(`${recap.day}T12:00:00`).toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, recap!.day);
    setHidden(true);
  }

  async function setLoop(id: string, status: "done" | "dismissed") {
    await api(`/open-loops/${id}`, { method: "POST", body: { status } });
    setRecap({ ...recap!, open_loops: recap!.open_loops.filter((l) => l.id !== id) });
  }

  return (
    <section className="rounded-lg border border-border bg-surface p-6 shadow-sm">
      <div className="mb-4 flex items-baseline justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Yesterday</p>
          <h3 className="text-lg font-semibold text-ink">{dayName}</h3>
        </div>
        <button onClick={dismiss} className="text-xs text-ink-muted hover:text-ink">
          Dismiss
        </button>
      </div>

      {recap.summary && <p className="mb-5 leading-relaxed text-ink">{plain(recap.summary)}</p>}

      <div className="mb-5 flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink-muted">
        {recap.stats && <span>{duration(recap.stats.focused_seconds)} active</span>}
        {recap.stats?.top_apps.slice(0, 3).map((a) => (
          <span key={a.app_name}>
            {a.app_name} <span className="text-ink">{duration(a.seconds)}</span>
          </span>
        ))}
      </div>

      <ol className="flex flex-col gap-3 border-l border-border pl-4">
        {recap.episodes.map((e) => (
          <li key={e.id}>
            <p className="font-mono text-xs text-ink-muted">
              {clock(e.started_at)} to {clock(e.ended_at)}
            </p>
            <p className="text-sm font-medium text-ink">{e.title}</p>
            <p className="text-sm text-ink-muted">{plain(e.summary)}</p>
          </li>
        ))}
      </ol>

      {recap.open_loops.length > 0 && (
        <div className="mt-6">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">Open loops</p>
          <ul className="flex flex-col gap-2">
            {recap.open_loops.map((l) => (
              <li key={l.id} className="flex items-start justify-between gap-4 text-sm">
                <span className="text-ink">
                  {l.text}
                  <span className="text-ink-muted"> · {l.app_name}</span>
                </span>
                <span className="flex shrink-0 gap-3 text-xs">
                  <button onClick={() => setLoop(l.id, "done")} className="text-accent hover:underline">
                    Done
                  </button>
                  <button onClick={() => setLoop(l.id, "dismissed")} className="text-ink-muted hover:text-ink">
                    Dismiss
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
