import { useState } from "react";
import "./App.css";

function App() {
  const [prompt, setPrompt] = useState("");
  const [response, setResponse] = useState("");
  const [loading, setLoading] = useState(false);

  async function askEngram() {
    if (!prompt.trim()) return;
    setLoading(true);
    setResponse("");
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/generate?prompt=${encodeURIComponent(prompt)}`
      );
      const data = await res.json();
      setResponse(data.response);
    } catch (err) {
      setResponse("Error: could not reach AI engine. Is it running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-screen w-screen bg-slate-900 text-white">
      <aside className="w-64 border-r border-slate-700 bg-slate-950 p-4">
        <h1 className="mb-6 text-xl font-bold">🧠 Engram</h1>
        <nav className="flex flex-col gap-2 text-sm text-slate-300">
          <span className="cursor-pointer rounded px-2 py-1 hover:bg-slate-800">
            Dashboard
          </span>
          <span className="cursor-pointer rounded px-2 py-1 hover:bg-slate-800">
            Memories
          </span>
          <span className="cursor-pointer rounded px-2 py-1 hover:bg-slate-800">
            Settings
          </span>
        </nav>
      </aside>

      <main className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Ask Engram something..."
          className="w-full max-w-lg rounded-lg bg-slate-800 px-4 py-2 outline-none"
        />
        <button
          onClick={askEngram}
          disabled={loading}
          className="rounded-lg bg-indigo-600 px-4 py-2 hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading ? "Thinking..." : "Ask"}
        </button>
        {response && (
          <p className="max-w-lg whitespace-pre-wrap text-slate-300">
            {response}
          </p>
        )}
      </main>
    </div>
  );
}

export default App;