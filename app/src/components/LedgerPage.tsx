import { useEffect, useState } from "react";
import { api } from "../lib/api";

type Entry = {
  id: string;
  created_at: string;
  app_name: string;
  window_title: string;
  trigger: "manual" | "auto" | "dwell" | "changed";
  text_source?: string;
  url?: string;
  outcome: "saved" | "dropped-noise" | "duplicate" | "excluded" | "failed";
  reason: string | null;
  memory_id: string | null;
};

const outcomeLabels: Record<Entry["outcome"], string> = {
  saved: "Saved",
  "dropped-noise": "Dropped, unreadable",
  duplicate: "Already saved",
  excluded: "Not captured, excluded",
  failed: "Failed",
};

const outcomeColors: Record<Entry["outcome"], string> = {
  saved: "text-accent",
  "dropped-noise": "text-ink-muted",
  duplicate: "text-ink-muted",
  excluded: "text-ink-muted",
  failed: "text-red-600",
};

const triggerLabels: Record<string, string> = {
  auto: "Automatic",
  dwell: "Automatic",
  changed: "Automatic, content changed",
  manual: "Capture now",
};

const sourceLabels: Record<string, string> = {
  accessibility: "Read from the app",
  ocr: "Read from the screen",
};

export default function LedgerPage() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [confirmClear, setConfirmClear] = useState(false);

  async function load() {
    setEntries(await api<Entry[]>("/ledger"));
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, []);

  async function remove(id: string) {
    await api(`/ledger/${id}`, { method: "DELETE" });
    await load();
  }

  async function clearAll() {
    await api("/ledger", { method: "DELETE" });
    setConfirmClear(false);
    await load();
  }

  return (
    <div className="flex h-full w-full flex-col gap-6 overflow-y-auto p-8">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
            Capture ledger
          </h2>
          {entries.length > 0 &&
            (confirmClear ? (
              <div className="flex gap-2">
                <button
                  onClick={() => setConfirmClear(false)}
                  className="rounded-md border border-border px-3 py-1 text-xs hover:bg-surface-muted"
                >
                  Cancel
                </button>
                <button
                  onClick={clearAll}
                  className="rounded-md bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-500"
                >
                  Clear ledger
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmClear(true)}
                className="rounded-md border border-border px-3 py-1 text-xs hover:bg-surface-muted"
              >
                Clear all
              </button>
            ))}
        </div>
        <p className="mb-4 text-sm text-ink-muted">
          Every time Engram tries to capture a window, it is listed here, with
          what happened. Clearing the ledger does not delete saved memories.
        </p>

        {entries.length === 0 ? (
          <p className="text-sm text-ink-muted">No captures yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {entries.map((e) => (
              <li
                key={e.id}
                className="flex items-start justify-between gap-4 rounded-md border border-border bg-surface px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm text-ink">
                    {e.app_name || "Unknown app"}
                    {e.window_title && (
                      <span className="text-ink-muted"> · {e.window_title}</span>
                    )}
                  </p>
                  <p className="mt-1 text-xs text-ink-muted">
                    {new Date(e.created_at).toLocaleString()} ·{" "}
                    {triggerLabels[e.trigger] ?? e.trigger} ·{" "}
                    {e.text_source && (
                      <>{sourceLabels[e.text_source] ?? e.text_source} · </>
                    )}
                    <span className={outcomeColors[e.outcome]}>
                      {outcomeLabels[e.outcome] ?? e.outcome}
                    </span>
                    {e.reason && <span> ({e.reason})</span>}
                  </p>
                </div>
                <button
                  onClick={() => remove(e.id)}
                  className="shrink-0 text-xs text-ink-muted hover:text-red-600"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
