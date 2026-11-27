import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { api } from "../lib/api";

type Rule = { id: string; kind: "app" | "title"; pattern: string };
type Exclusions = {
  builtin_apps: string[];
  private_title_patterns: string[];
  rules: Rule[];
};

export default function ExclusionsSection() {
  const [data, setData] = useState<Exclusions | null>(null);
  const [kind, setKind] = useState<"app" | "title">("app");
  const [pattern, setPattern] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setData(await api<Exclusions>("/exclusions"));
  }

  useEffect(() => {
    load();
  }, []);

  async function changed() {
    await load();
    // Tell the window tracker right away instead of waiting for its refresh.
    await invoke("refresh_exclusions").catch(() => {});
  }

  async function addRule() {
    if (!pattern.trim()) return;
    setError(null);
    try {
      await api("/exclusions/rules", { method: "POST", body: { kind, pattern } });
      setPattern("");
      await changed();
    } catch {
      setError("Could not save the rule.");
    }
  }

  async function removeRule(id: string) {
    await api(`/exclusions/rules/${id}`, { method: "DELETE" });
    await changed();
  }

  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
        Never capture
      </h2>
      <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
        <p className="text-xs text-ink-muted">
          Engram never captures these windows and logs only the app name,
          not the window title. Always excluded:{" "}
          {data?.builtin_apps.join(", ")}, and private browsing windows.
          Chrome, Edge and Brave incognito windows are detected by asking the
          browser, so macOS asks once for permission to control it; allow it,
          or Engram cannot tell them apart. Firefox private windows are
          detected from their title. Safari private windows cannot be
          detected, so add Safari below if you use them.
        </p>

        {data && data.rules.length > 0 && (
          <ul className="flex flex-col gap-2">
            {data.rules.map((rule) => (
              <li
                key={rule.id}
                className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
              >
                <span>
                  <span className="text-ink-muted">
                    {rule.kind === "app" ? "App name contains" : "Window title contains"}
                  </span>{" "}
                  <span className="font-medium text-ink">{rule.pattern}</span>
                </span>
                <button
                  onClick={() => removeRule(rule.id)}
                  className="text-xs text-ink-muted hover:text-red-600"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex gap-2">
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as "app" | "title")}
            className="rounded-md border border-border bg-surface px-2 py-2 text-sm text-ink"
          >
            <option value="app">App name contains</option>
            <option value="title">Window title contains</option>
          </select>
          <input
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addRule()}
            placeholder={kind === "app" ? "e.g. Safari" : "e.g. Bank"}
            className="flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <button
            onClick={addRule}
            className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-surface-muted"
          >
            Add rule
          </button>
        </div>
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>
    </div>
  );
}
