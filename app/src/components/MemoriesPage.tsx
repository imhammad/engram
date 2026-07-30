import { useState, useEffect } from "react";

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
      await fetch(`${API_BASE}/memories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: newMemory }),
      });
      setNewMemory("");
      await loadMemories();
    } finally {
      setLoading(false);
    }
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
    <div className="flex h-full w-full flex-col gap-6 p-8 text-white">
      <div>
        <h2 className="mb-2 text-lg font-semibold">Save a memory</h2>
        <div className="flex gap-2">
          <input
            value={newMemory}
            onChange={(e) => setNewMemory(e.target.value)}
            placeholder="Write something to remember..."
            className="flex-1 rounded-lg bg-slate-800 px-4 py-2 outline-none"
          />
          <button
            onClick={saveMemory}
            disabled={loading}
            className="rounded-lg bg-indigo-600 px-4 py-2 hover:bg-indigo-500 disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-lg font-semibold">Capture your screen</h2>
        <div className="flex items-center gap-3">
          <button
            onClick={captureScreen}
            disabled={capturing}
            className="rounded-lg bg-emerald-600 px-4 py-2 hover:bg-emerald-500 disabled:opacity-50"
          >
            {capturing ? "Capturing..." : "📸 Capture Screen"}
          </button>
          {captureMessage && (
            <span className="text-sm text-slate-400">{captureMessage}</span>
          )}
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-lg font-semibold">Search your memories</h2>
        <div className="flex gap-2">
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Ask about something you saved..."
            className="flex-1 rounded-lg bg-slate-800 px-4 py-2 outline-none"
          />
          <button
            onClick={runSearch}
            disabled={loading}
            className="rounded-lg bg-indigo-600 px-4 py-2 hover:bg-indigo-500 disabled:opacity-50"
          >
            Search
          </button>
          {searchResults && (
            <button
              onClick={() => {
                setSearchResults(null);
                setSearchQuery("");
              }}
              className="rounded-lg bg-slate-700 px-4 py-2 hover:bg-slate-600"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2 overflow-y-auto">
        <h2 className="text-lg font-semibold">
          {searchResults ? "Search results" : "All memories"}
        </h2>
        {listToShow.length === 0 && (
          <p className="text-slate-400">Nothing here yet.</p>
        )}
        {listToShow.map((m) => (
          <div key={m.id} className="rounded-lg bg-slate-800 p-3">
            <p>{m.content}</p>
            <p className="mt-1 text-xs text-slate-500">
              {new Date(m.created_at).toLocaleString()}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}