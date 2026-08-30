import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";

type Memory = {
  id: string;
  content: string;
  source: string;
  created_at: string;
};

const API_BASE = "http://127.0.0.1:8000";

export default function MemoriesPage() {
  const [newMemory, setNewMemory] = useState("");
  const [memories, setMemories] = useState<Memory[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Memory[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [captureMessage, setCaptureMessage] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [audioMessage, setAudioMessage] = useState<string | null>(null);
  const [captureEnabled, setCaptureEnabled] = useState(true);
  const [connectionMessage, setConnectionMessage] = useState<string | null>(null);

  async function loadMemories() {
    const res = await fetch(`${API_BASE}/memories`);
    const data = await res.json();
    setMemories(data);
  }

  useEffect(() => {
    loadMemories();
  }, []);

async function saveMemory() {
  if (!newMemory.trim()) return;
  setLoading(true);
  try {
    const res = await fetch(`${API_BASE}/memories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: newMemory }),
    });
    const data = await res.json();
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

  async function captureScreen() {
  setCapturing(true);
  setCaptureMessage(null);
  try {
    const res = await fetch(`${API_BASE}/capture/screen`, { method: "POST" });
    const data = await res.json();
    if (data.saved) {
      setCaptureMessage("Captured and saved!");
      await loadMemories();
    } else {
      setCaptureMessage(data.reason || "Nothing readable was captured.");
    }
  } catch (err) {
    setCaptureMessage("Error: could not reach AI engine.");
  } finally {
    setCapturing(false);
    setTimeout(() => setCaptureMessage(null), 3000);
  }
}

async function captureAudio() {
  setRecording(true);
  setAudioMessage("Listening... speak now (8 seconds)");
  try {
    const res = await fetch(`${API_BASE}/capture/audio`, { method: "POST" });
    const data = await res.json();
    if (data.saved) {
      setAudioMessage("Transcribed and saved!");
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
      const res = await fetch(
        `${API_BASE}/search?q=${encodeURIComponent(searchQuery)}`
      );
      const data = await res.json();
      setSearchResults(data);
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
          🔗 {connectionMessage}
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
      <div className="flex gap-3">
        <button
          onClick={captureScreen}
          disabled={capturing}
          className="rounded-md border border-border bg-canvas px-4 py-2 text-sm font-medium hover:bg-surface-muted disabled:opacity-50"
        >
          {capturing ? "Capturing..." : "📸 Capture Screen"}
        </button>
        <button
          onClick={captureAudio}
          disabled={recording}
          className="rounded-md border border-border bg-canvas px-4 py-2 text-sm font-medium hover:bg-surface-muted disabled:opacity-50"
        >
          {recording ? "🎙️ Recording..." : "🎙️ Record 8s"}
        </button>
      </div>
      {(captureMessage || audioMessage) && (
        <p className="mt-2 text-sm text-ink-muted">
          {captureMessage || audioMessage}
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
          className="rounded-md border border-border bg-surface p-3"
        >
          <p className="text-sm text-ink">{m.content}</p>
          <p className="mt-1 font-mono text-xs text-ink-muted">
            {new Date(m.created_at).toLocaleString()} · {m.source}
          </p>
        </div>
      ))}
    </div>
  </div>
);
}