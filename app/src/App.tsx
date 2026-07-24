import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

function App() {
  const [response, setResponse] = useState("");

  async function testPing() {
    const result = await invoke<string>("ping");
    setResponse(result);
  }

  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-4 bg-slate-900">
      <h1 className="text-4xl font-bold text-white">Engram is alive 🧠</h1>
      <button
        onClick={testPing}
        className="rounded-lg bg-indigo-600 px-4 py-2 text-white hover:bg-indigo-500"
      >
        Test IPC Bridge
      </button>
      {response && (
        <p className="text-lg text-green-400">Rust says: {response}</p>
      )}
    </div>
  );
}

export default App;