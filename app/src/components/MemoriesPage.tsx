import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { api } from "../lib/api";

type Memory = {
  id: string;
  content: string;
  source: string;
  created_at: string;
  pinned?: boolean;
};

export default function MemoriesPage() {
  const [newMemory, setNewMemory] = useState("");
  const [memories, setMemories] = useState<Memory[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Memory[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [audioMessage, setAudioMessage] = useState<string | null>(null);
  const [captureEnabled, setCaptureEnabled] = useState(true);
  const [connectionMessage, setConnectionMessage] = useState<string | null>(null);

  async function loadMemories() {
    setMemories(await api<Memory[]>("/memories"));
  }

  useEffect(() => {
    loadMemories();
    // Pause can also be set from the menu bar; keep the label in step.
    invoke<boolean>("get_capture_paused").then((p) => setCaptureEnabled(!p));
    const off = listen<boolean>("capture-paused", (e) => setCaptureEnabled(!e.payload));
    return () => {
      off.then((f) => f());
    };
  }, []);

async function saveMemory() {
  if (!newMemory.trim()) return;
  setLoading(true);
  try {
    const data = await api<{ related_memory: Memory | null }>("/memories", {
      method: "POST",
      body: { content: newMemory },
    });
    setNewMemory("");
    if (data.related_memory) {
      setConnectionMessage(
        `This connects to: "${data.related_memory.content}"`
      );
      setTimeout(() => setConnectionMessage(null), 6000);
    }
    await loadMemories();
  } finally {
    setLoading(false);
  }
}

  async function toggleCapture() {
  const newPausedState = captureEnabled; // if currently enabled, we're about to pause it
  await invoke("set_capture_paused", { paused: newPausedState });
  setCaptureEnabled(!newPausedState);
  }

async function toggleKeep(m: Memory) {
  await api(`/memories/${m.id}/keep`, { method: "POST", body: { pinned: !m.pinned } });
  await loadMemories();
}

async function deleteMemory(id: string) {
  await api(`/memories/${id}`, { method: "DELETE" });
  await loadMemories();
}

async function captureAudio() {
  setRecording(true);
  setAudioMessage("Listening... speak now (8 seconds)");
  try {
    const data = await api<{ saved: boolean; reason?: string }>("/capture/audio", {
      method: "POST",
    });
    if (data.saved) {
      setAudioMessage("Transcribed and saved.");
      await loadMemories();
    } else {
      setAudioMessage(data.reason || "No speech detected.");
    }
  } catch (err) {
    setAudioMessage("Error: could not reach AI engine.");
  } finally {
    setRecording(false);
    setTimeout(() => setAudioMessage(null), 3000);
  }
}

  async function runSearch() {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    setLoading(true);
    try {
      setSearchResults(
        await api<Memory[]>(`/search?q=${encodeURIComponent(searchQuery)}`),
      );
    } finally {
      setLoading(false);
    }
  }

  const listToShow = searchResults ?? memories;

  return (
  <div className="flex h-full w-full flex-col gap-6 overflow-y-auto p-8">
    <div>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
        Save a memory
      </h2>
      <div className="flex gap-2">
        <input
          value={newMemory}
          onChange={(e) => setNewMemory(e.target.value)}
          placeholder="Write something to remember..."
          className="flex-1 rounded-md border border-border bg-surface px-4 py-2 text-ink outline-none placeholder:text-ink-muted focus:border-accent"
        />
        {connectionMessage && (
        <p className="mt-2 rounded-md border border-accent/30 bg-accent/5 px-3 py-2 text-sm text-accent">
          {connectionMessage}
        </p>
      )}
        <button
          onClick={saveMemory}
          disabled={loading}
          className="rounded-md bg-accent px-4 py-2 font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
        >
          Save
        </button>
      </div>
    </div>

    <div className="rounded-md border border-border bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
          Capture
        </h2>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-ink-muted">
            Auto-capture:{" "}
            <span className={captureEnabled ? "text-accent" : "text-red-600"}>
              {captureEnabled ? "Active" : "Paused"}
            </span>
          </span>
          <button
            onClick={toggleCapture}
            className="rounded-md border border-border px-2 py-1 text-xs hover:bg-surface-muted"
          >
            {captureEnabled ? "Pause" : "Resume"}
          </button>
        </div>
      </div>
      <p className="mb-3 text-sm text-ink-muted">
        Engram captures the window you are working in on its own, and again
        when what you are looking at changes. You do not need to press
        anything. To keep the window in front for good, press Keep
        (Option-Shift-K by default) from anywhere.
      </p>
      <div className="flex items-center gap-3">
        <button
          onClick={captureAudio}
          disabled={recording}
          className="rounded-md px-2 py-1 text-xs text-ink-muted underline-offset-2 hover:text-ink hover:underline disabled:opacity-50"
        >
          {recording ? "Recording..." : "Record 8s"}
        </button>
      </div>
      {audioMessage && (
        <p className="mt-2 text-sm text-ink-muted">
          {audioMessage}
        </p>
      )}
    </div>

    <div>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-muted">
        Search your memories
      </h2>
      <div className="flex gap-2">
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Ask about something you saved..."
          className="flex-1 rounded-md border border-border bg-surface px-4 py-2 text-ink outline-none placeholder:text-ink-muted focus:border-accent"
        />
        <button
          onClick={runSearch}
          disabled={loading}
          className="rounded-md bg-accent px-4 py-2 font-medium text-white hover:bg-accent-hover disabled:opacity-50"
        >
          Search
        </button>
        {searchResults && (
          <button
            onClick={() => {
              setSearchResults(null);
              setSearchQuery("");
            }}
            className="rounded-md border border-border px-4 py-2 text-sm hover:bg-surface-muted"
          >
            Clear
          </button>
        )}
      </div>
    </div>

    <div className="flex flex-col gap-2 pr-2">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
        {searchResults ? "Search results" : "All memories"}
      </h2>
      {listToShow.length === 0 && (
        <p className="text-sm text-ink-muted">Nothing here yet.</p>
      )}
      {listToShow.map((m) => (
        <div
          key={m.id}
          className="flex items-start justify-between rounded-md border border-border bg-surface p-3"
        >
          <div>
            <p className="text-sm text-ink">{m.content}</p>
            <p className="mt-1 font-mono text-xs text-ink-muted">
              {new Date(m.created_at).toLocaleString()} · {m.source}
            </p>
          </div>
          <div className="ml-2 flex shrink-0 items-center gap-3">
            <button
              onClick={() => toggleKeep(m)}
              title={m.pinned ? "Kept: this memory will never fade" : "Keep this memory so it never fades"}
              className={`text-xs ${m.pinned ? "font-medium text-accent" : "text-ink-muted hover:text-ink"}`}
            >
              {m.pinned ? "Kept" : "Keep"}
            </button>
            <button
              onClick={() => deleteMemory(m.id)}
              className="text-xs text-ink-muted hover:text-red-600"
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  </div>
);
}