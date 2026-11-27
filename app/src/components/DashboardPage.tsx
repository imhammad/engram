import { useState, useEffect } from "react";
import { api } from "../lib/api";

type Stats = {
  total_memories: number;
  by_source: Record<string, number>;
};

type ActivityEntry = {
  id: string;
  window_title: string;
  app_name: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
};

type AppTime = { app_name: string; seconds: number };

function formatDuration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

const sourceLabels: Record<string, string> = {
  manual: "Typed notes",
  screen_ocr: "Screen captures",
  audio_transcription: "Audio recordings",
};

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [today, setToday] = useState<AppTime[] | null>(null);

  useEffect(() => {
    api<Stats>("/stats").then(setStats);
    api<ActivityEntry[]>("/activity").then(setActivity);
    const loadToday = () =>
      api<{ apps: AppTime[] }>("/activity/today").then((d) => setToday(d.apps));
    loadToday();
    const timer = setInterval(loadToday, 60000);
    return () => clearInterval(timer);
  }, []);

  const maxToday = today && today.length ? today[0].seconds : 1;
  const totalToday = today ? today.reduce((sum, a) => sum + a.seconds, 0) : 0;

  const maxSourceCount = stats
    ? Math.max(...Object.values(stats.by_source), 1)
    : 1;

  return (
    <div className="flex h-full w-full flex-col gap-6 overflow-y-auto p-8">
      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Overview
        </h2>
        <div className="rounded-md border border-border bg-surface p-6">
          <p className="text-3xl font-semibold text-ink">
            {stats?.total_memories ?? "…"}
          </p>
          <p className="text-sm text-ink-muted">total memories saved</p>
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
            Today
          </h2>
          {today && today.length > 0 && (
            <span className="text-xs text-ink-muted">
              {formatDuration(totalToday)} active
            </span>
          )}
        </div>
        <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-6">
          {today === null && <p className="text-sm text-ink-muted">Loading…</p>}
          {today && today.length === 0 && (
            <p className="text-sm text-ink-muted">
              No activity yet today. Time is counted while you use your Mac,
              and pauses when you are idle, asleep or locked.
            </p>
          )}
          {today?.map((app) => (
            <div key={app.app_name}>
              <div className="mb-1 flex justify-between text-sm">
                <span className="text-ink">{app.app_name}</span>
                <span className="text-ink-muted">{formatDuration(app.seconds)}</span>
              </div>
              <div className="h-2 w-full rounded-full bg-surface-muted">
                <div
                  className="h-2 rounded-full bg-accent"
                  style={{ width: `${(app.seconds / maxToday) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
          By source
        </h2>
        <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-6">
          {stats &&
            Object.entries(stats.by_source).map(([source, count]) => (
              <div key={source}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="text-ink">
                    {sourceLabels[source] ?? source}
                  </span>
                  <span className="text-ink-muted">{count}</span>
                </div>
                <div className="h-2 w-full rounded-full bg-surface-muted">
                  <div
                    className="h-2 rounded-full bg-accent"
                    style={{ width: `${(count / maxSourceCount) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          {stats && Object.keys(stats.by_source).length === 0 && (
            <p className="text-sm text-ink-muted">No memories saved yet.</p>
          )}
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Recent activity
        </h2>
        <div className="flex flex-col gap-2">
          {activity.length === 0 && (
            <p className="text-sm text-ink-muted">
              No activity tracked yet.
            </p>
          )}
          {activity.map((entry) => (
            <div
              key={entry.id}
              className="rounded-md border border-border bg-surface px-4 py-2"
            >
              <p className="text-sm text-ink">
                {entry.window_title || entry.app_name}
              </p>
              <p className="font-mono text-xs text-ink-muted">
                {entry.app_name} ·{" "}
                {new Date(entry.started_at).toLocaleString()} ·{" "}
                {entry.ended_at === null
                  ? "now"
                  : formatDuration(entry.duration_seconds ?? 0)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}