import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

type Presence = {
  show_in_dock: boolean;
  mark_visible: boolean;
  ask_shortcut: string;
  keep_shortcut: string;
  launch_at_login: boolean;
};

/** "Alt+Shift+K" -> "⌥⇧K", the way macOS menus write shortcuts. */
export function prettyShortcut(s: string): string {
  const symbols: Record<string, string> = { Cmd: "⌘", Ctrl: "⌃", Alt: "⌥", Shift: "⇧", Space: "Space", Enter: "↩" };
  return s
    .split("+")
    .map((p) => symbols[p] ?? p)
    .join("");
}

/** Turn a keydown into Engram's shortcut form, or null while only modifiers are down. */
function fromKeyEvent(e: React.KeyboardEvent): string | null {
  const code = e.code;
  let key: string | null = null;
  if (code === "Space") key = "Space";
  else if (code === "Enter") key = "Enter";
  else if (code.startsWith("Key")) key = code.slice(3);
  else if (code.startsWith("Digit")) key = code.slice(5);
  else if (/^F\d{1,2}$/.test(code)) key = code;
  if (!key) return null;
  const mods = [e.metaKey && "Cmd", e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift"].filter(Boolean);
  return [...mods, key].join("+");
}

function ShortcutField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (s: string) => Promise<void>;
}) {
  const [recording, setRecording] = useState(false);
  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium text-ink">{label}</p>
        <p className="text-xs text-ink-muted">{hint}</p>
      </div>
      <button
        aria-label={`${label} shortcut, currently ${value}. Press to change.`}
        onClick={() => setRecording(true)}
        onBlur={() => setRecording(false)}
        onKeyDown={async (e) => {
          if (!recording) return;
          e.preventDefault();
          if (e.key === "Escape") {
            setRecording(false);
            return;
          }
          const s = fromKeyEvent(e);
          if (s) {
            setRecording(false);
            await onChange(s);
          }
        }}
        className={`min-w-28 rounded-md border px-3 py-1 font-mono text-sm ${
          recording ? "border-accent text-accent" : "border-border text-ink"
        }`}
      >
        {recording ? "Press keys..." : prettyShortcut(value)}
      </button>
    </div>
  );
}

function Toggle({ label, hint, on, set }: { label: string; hint: string; on: boolean; set: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-ink">{label}</p>
        <p className="text-xs text-ink-muted">{hint}</p>
      </div>
      <input type="checkbox" className="h-4 w-4 accent-accent" checked={on} onChange={(e) => set(e.target.checked)} />
    </label>
  );
}

export default function PresenceSection() {
  const [p, setP] = useState<Presence | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    invoke<Presence>("get_presence_settings").then(setP);
  }, []);

  async function update(change: Partial<Presence>) {
    setError(null);
    try {
      setP(await invoke<Presence>("set_presence_settings", { update: change }));
    } catch (err) {
      setError(String(err));
    }
  }

  if (!p) return null;
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">Everyday use</h2>
      <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
        <ShortcutField
          label="Ask Engram"
          hint="Opens the ask bar from any app. Return answers; Cmd-Return saves what you typed as a note."
          value={p.ask_shortcut}
          onChange={(s) => update({ ask_shortcut: s })}
        />
        <div className="border-t border-border" />
        <ShortcutField
          label="Keep this window"
          hint="Captures the window in front now and keeps it, so it never fades."
          value={p.keep_shortcut}
          onChange={(s) => update({ keep_shortcut: s })}
        />
        {error && (
          <p role="alert" className="text-xs text-red-700">
            That shortcut can't be used: {error}.
          </p>
        )}
        <div className="border-t border-border" />
        <Toggle
          label="Show the mark"
          hint="The small Engram mark that floats above your windows. Click it to ask; drag it to move it."
          on={p.mark_visible}
          set={(v) => update({ mark_visible: v })}
        />
        <Toggle
          label="Show in the Dock"
          hint="Engram lives in the menu bar. Turn this on to also have a Dock icon."
          on={p.show_in_dock}
          set={(v) => update({ show_in_dock: v })}
        />
        <Toggle
          label="Open at login"
          hint="Start Engram when you log in to your Mac. Off unless you turn it on."
          on={p.launch_at_login}
          set={(v) => update({ launch_at_login: v })}
        />
      </div>
    </div>
  );
}
