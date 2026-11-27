import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { api } from "../lib/api";
import ExclusionsSection from "./ExclusionsSection";


type PermissionState = "granted" | "denied" | "unsupported";

type CaptureTiming = { dwell_seconds: number; recapture_minutes: number };

function CaptureTimingSection() {
  const [timing, setTiming] = useState<CaptureTiming | null>(null);

  useEffect(() => {
    api<CaptureTiming>("/settings/capture").then(setTiming);
  }, []);

  async function update(change: Partial<CaptureTiming>) {
    if (!timing) return;
    const next = await api<CaptureTiming>("/settings/capture", {
      method: "PUT",
      body: { ...timing, ...change },
    });
    setTiming(next);
    // Apply now rather than at the tracker's next 30-second refresh.
    await invoke("refresh_capture_settings").catch(() => {});
  }

  const select =
    "rounded-md border border-border bg-surface px-2 py-1 text-sm text-ink";

  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
        Capture timing
      </h2>
      <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-ink">First capture after</p>
            <p className="text-xs text-ink-muted">
              How long a window stays in front before Engram captures it.
            </p>
          </div>
          <select
            className={select}
            value={timing?.dwell_seconds ?? 30}
            onChange={(e) => update({ dwell_seconds: Number(e.target.value) })}
          >
            <option value={15}>15 seconds</option>
            <option value={30}>30 seconds</option>
            <option value={60}>1 minute</option>
          </select>
        </div>
        <div className="border-t border-border" />
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-ink">Look again every</p>
            <p className="text-xs text-ink-muted">
              While you stay on one window, Engram checks it again and saves
              only if the content changed, for example after you scroll.
            </p>
          </div>
          <select
            className={select}
            value={timing?.recapture_minutes ?? 2}
            onChange={(e) => update({ recapture_minutes: Number(e.target.value) })}
          >
            <option value={0}>Off</option>
            <option value={1}>1 minute</option>
            <option value={2}>2 minutes</option>
            <option value={5}>5 minutes</option>
          </select>
        </div>
      </div>
    </div>
  );
}

function PermissionsSection() {
  const [screen, setScreen] = useState<PermissionState | null>(null);
  const [axs, setAxs] = useState<PermissionState | null>(null);

  async function refresh() {
    setScreen(await invoke<PermissionState>("screen_recording_status"));
    setAxs(await invoke<PermissionState>("accessibility_status"));
  }

  async function openAccessibility() {
    await invoke("request_accessibility");
    await invoke("open_privacy_settings", { pane: "accessibility" });
  }

  useEffect(() => {
    refresh();
    // Re-check when the user comes back from System Settings.
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, []);

  async function openScreenRecording() {
    // Adds Engram to the list (first time only), then opens the pane.
    await invoke("request_screen_recording");
    await invoke("open_privacy_settings", { pane: "screen-recording" });
  }

  if (screen === null || screen === "unsupported") return null;

  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
        Permissions
      </h2>
      <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-ink">
              Screen Recording{" "}
              <span
                className={`ml-2 text-xs font-normal ${
                  screen === "granted" ? "text-accent" : "text-red-600"
                }`}
              >
                {screen === "granted" ? "Allowed" : "Not allowed"}
              </span>
            </p>
            <p className="text-xs text-ink-muted">
              Needed to read window titles and capture on-screen text. macOS
              applies a change after Engram restarts.
            </p>
          </div>
          <button
            onClick={openScreenRecording}
            className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-surface-muted"
          >
            Open Settings
          </button>
        </div>

        <div className="border-t border-border" />

        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-ink">
              Accessibility{" "}
              <span
                className={`ml-2 text-xs font-normal ${
                  axs === "granted" ? "text-accent" : "text-red-600"
                }`}
              >
                {axs === "granted" ? "Allowed" : "Not allowed"}
              </span>
            </p>
            <p className="text-xs text-ink-muted">
              Lets Engram read the actual text of the window in front (a web
              page, a document) and a page's address, instead of reading the
              screen. It never reads password fields. Without it, Engram reads
              the screen instead.
            </p>
          </div>
          <button
            onClick={openAccessibility}
            className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-surface-muted"
          >
            Open Settings
          </button>
        </div>

        <div className="border-t border-border" />

        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-ink">Microphone</p>
            <p className="text-xs text-ink-muted">
              macOS asks the first time you press Record. Change it here if
              you declined.
            </p>
          </div>
          <button
            onClick={() =>
              invoke("open_privacy_settings", { pane: "microphone" })
            }
            className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-surface-muted"
          >
            Open Settings
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function exportData() {
    setExporting(true);
    try {
      const data = await api("/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `engram-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setMessage("Export downloaded.");
    } finally {
      setExporting(false);
      setTimeout(() => setMessage(null), 3000);
    }
  }

  async function deleteEverything() {
    setDeleting(true);
    try {
      const memData = await api<{ deleted_count: number }>("/memories", {
        method: "DELETE",
      });
      await api("/activity", { method: "DELETE" });
      await api("/ledger", { method: "DELETE" });
      setMessage(
        `Deleted ${memData.deleted_count} memories, all activity history and the capture ledger.`,
      );
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
      setTimeout(() => setMessage(null), 5000);
    }
  }

  return (
    <div className="flex h-full w-full flex-col gap-6 overflow-y-auto p-8">
      <PermissionsSection />

      <CaptureTimingSection />

      <ExclusionsSection />

      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Your data
        </h2>
        <p className="mb-4 text-sm text-ink-muted">
          Everything Engram captures, including typed notes, screen captures,
          audio transcriptions, and activity history, stays on this
          device. Nothing is ever sent anywhere. You have full control
          to export or permanently delete it below.
        </p>
        <p className="mb-4 text-sm text-ink-muted">
          It is kept in one encrypted database (SQLCipher, AES-256) in
          Application Support. The key is a random 256-bit secret stored in
          your macOS Keychain as "dev.engram.app", so the file cannot be read
          without your Mac login. If you delete that Keychain item, the
          database can no longer be opened.
        </p>

        <div className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-ink">Export all data</p>
              <p className="text-xs text-ink-muted">
                Downloads a JSON file of every memory and activity entry.
              </p>
            </div>
            <button
              onClick={exportData}
              disabled={exporting}
              className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-surface-muted disabled:opacity-50"
            >
              {exporting ? "Exporting..." : "Export"}
            </button>
          </div>

          <div className="border-t border-border" />

          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-ink">
                Delete all data
              </p>
              <p className="text-xs text-ink-muted">
                Permanently removes every memory, activity record and
                ledger entry.
                This cannot be undone.
              </p>
            </div>
            {!confirmDelete ? (
              <button
                onClick={() => setConfirmDelete(true)}
                className="rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
              >
                Delete everything
              </button>
            ) : (
              <div className="flex gap-2">
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="rounded-md border border-border px-3 py-2 text-sm hover:bg-surface-muted"
                >
                  Cancel
                </button>
                <button
                  onClick={deleteEverything}
                  disabled={deleting}
                  className="rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
                >
                  {deleting ? "Deleting..." : "Confirm delete"}
                </button>
              </div>
            )}
          </div>
        </div>

        {message && (
          <p className="mt-3 text-sm text-ink-muted">{message}</p>
        )}
      </div>
    </div>
  );
}