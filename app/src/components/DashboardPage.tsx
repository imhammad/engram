import { useState, useEffect } from "react";

type Stats = {
  total_memories: number;
  by_source: Record<string, number>;
};

type ActivityEntry = {
  id: string;
  window_title: string;
  app_name: string;
  started_at: string;
};

const API_BASE = "http://127.0.0.1:8000";

const sourceLabels: Record<string, string> = {
  manual: "Typed notes",
  screen_ocr: "Screen captures",
  audio_transcription: "Audio recordings",
};

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);

  useEffect(() => {
    fetch(`${API_BASE}/stats`).then((r) => r.json()).then(setStats);
    fetch(`${API_BASE}/activity`).then((r) => r.json()).then(setActivity);
  }, []);

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
              <p className="text-sm text-ink">{entry.window_title}</p>
              <p className="font-mono text-xs text-ink-muted">
                {entry.app_name} ·{" "}
                {new Date(entry.started_at).toLocaleString()}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}