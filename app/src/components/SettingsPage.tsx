import { useState } from "react";

const API_BASE = "http://127.0.0.1:8000";

export default function SettingsPage() {
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function exportData() {
    setExporting(true);
    try {
      const res = await fetch(`${API_BASE}/export`);
      const data = await res.json();
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
      const memRes = await fetch(`${API_BASE}/memories`, { method: "DELETE" });
      const memData = await memRes.json();
      await fetch(`${API_BASE}/activity`, { method: "DELETE" });
      setMessage(`Deleted ${memData.deleted_count} memories and all activity history.`);
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
      setTimeout(() => setMessage(null), 5000);
    }
  }

  return (
    <div className="flex h-full w-full flex-col gap-6 p-8">
      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Your data
        </h2>
        <p className="mb-4 text-sm text-ink-muted">
          Everything Engram captures — typed notes, screen captures,
          audio transcriptions, and activity history — stays on this
          device. Nothing is ever sent anywhere. You have full control
          to export or permanently delete it below.
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
                Permanently removes every memory and activity record.
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