import { useEffect, useState } from "react";
import { api } from "../lib/api";

type Preview = { days: number; would_fade: number; kept_by_pin: number; kept_by_recall: number };
type Forgetting = { days: number; label: string; previews: Record<string, Preview> };
type Consolidation = { running: boolean; pending_days: string[]; last: { at: string; days: string[] } | null };

const OPTIONS: { days: number; label: string; note: string }[] = [
  { days: 0, label: "Never", note: "Keep every memory until you delete it." },
  { days: 30, label: "Gentle", note: "Raw captures fade after 30 days." },
  { days: 14, label: "Balanced", note: "Raw captures fade after 14 days." },
  { days: 7, label: "Brisk", note: "Raw captures fade after 7 days." },
];

export default function MemoryLifecycleSection() {
  const [forgetting, setForgetting] = useState<Forgetting | null>(null);
  const [consolidation, setConsolidation] = useState<Consolidation | null>(null);
  const [pending, setPending] = useState<number | null>(null); // choice awaiting confirmation
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    setForgetting(await api<Forgetting>("/forgetting"));
    setConsolidation(await api<Consolidation>("/consolidation"));
  }

  useEffect(() => {
    load();
  }, []);

  async function choose(days: number) {
    if (!forgetting || days === forgetting.days) return;
    const stricter = days > 0 && (forgetting.days === 0 || days < forgetting.days);
    if (stricter) {
      setPending(days); // show the preview first
      return;
    }
    await api("/forgetting", { method: "PUT", body: { days } });
    await load();
  }

  async function confirm() {
    if (pending === null) return;
    await api("/forgetting", { method: "PUT", body: { days: pending, confirm: true } });
    setPending(null);
    await load();
  }

  async function consolidateNow() {
    setWorking(true);
    setMessage(null);
    try {
      const result = await api<{ consolidated: string[]; faded: number }>("/consolidate", {
        method: "POST",
        body: {},
      });
      setMessage(
        result.consolidated.length
          ? `Consolidated ${result.consolidated.length} day${result.consolidated.length > 1 ? "s" : ""}.`
          : "Every finished day is already consolidated.",
      );
      await load();
    } finally {
      setWorking(false);
    }
  }

  const preview = pending !== null ? forgetting?.previews[String(pending)] : null;

  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
        How Engram remembers
      </h2>
      <div className="flex flex-col gap-4 rounded-md border border-border bg-surface p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-ink">Consolidation</p>
            <p className="text-xs text-ink-muted">
              Each finished day is turned into episodes and a short summary, while
              your Mac is idle and plugged in.{" "}
              {consolidation?.pending_days.length
                ? `${consolidation.pending_days.length} day(s) waiting.`
                : "Up to date."}
            </p>
          </div>
          <button
            onClick={consolidateNow}
            disabled={working || consolidation?.running}
            className="shrink-0 rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-surface-muted disabled:opacity-50"
          >
            {working || consolidation?.running ? "Working..." : "Consolidate now"}
          </button>
        </div>
        {message && <p className="text-xs text-ink-muted">{message}</p>}

        <div className="border-t border-border" />

        <div>
          <p className="text-sm font-medium text-ink">Forgetting</p>
          <p className="mb-3 text-xs text-ink-muted">
            Like a brain, Engram can let raw captures fade once their day has been
            summarised. Episodes and day summaries stay. Anything you Keep, and
            anything a recent answer used, does not fade.
          </p>
          <div className="grid grid-cols-4 gap-2">
            {OPTIONS.map((o) => (
              <button
                key={o.days}
                onClick={() => choose(o.days)}
                title={o.note}
                className={`rounded-md border px-3 py-2 text-sm ${
                  forgetting?.days === o.days
                    ? "border-accent bg-accent/5 font-medium text-accent"
                    : "border-border text-ink hover:bg-surface-muted"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
          {preview && (
            <div className="mt-3 rounded-md border border-accent/30 bg-accent/5 p-3 text-sm">
              <p className="text-ink">
                At {OPTIONS.find((o) => o.days === pending)?.label} ({pending} days),{" "}
                <span className="font-medium">{preview.would_fade}</span> raw capture
                {preview.would_fade === 1 ? "" : "s"} would fade now.{" "}
                {preview.kept_by_pin + preview.kept_by_recall > 0 &&
                  `${preview.kept_by_pin} kept by you and ${preview.kept_by_recall} recently recalled would stay.`}
              </p>
              <div className="mt-2 flex gap-2">
                <button
                  onClick={() => setPending(null)}
                  className="rounded-md border border-border px-3 py-1 text-xs hover:bg-surface-muted"
                >
                  Cancel
                </button>
                <button
                  onClick={confirm}
                  className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-white hover:bg-accent-hover"
                >
                  Turn on
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
