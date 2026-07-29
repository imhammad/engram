import { useState } from "react";
import "./App.css";
import MemoriesPage from "./components/MemoriesPage";

type Tab = "dashboard" | "memories" | "settings";

function App() {
  const [activeTab, setActiveTab] = useState<Tab>("memories");

  return (
    <div className="flex h-screen w-screen bg-slate-900 text-white">
      <aside className="w-64 border-r border-slate-700 bg-slate-950 p-4">
        <h1 className="mb-6 text-xl font-bold">🧠 Engram</h1>
        <nav className="flex flex-col gap-2 text-sm text-slate-300">
          <span
            onClick={() => setActiveTab("dashboard")}
            className={`cursor-pointer rounded px-2 py-1 hover:bg-slate-800 ${
              activeTab === "dashboard" ? "bg-slate-800 text-white" : ""
            }`}
          >
            Dashboard
          </span>
          <span
            onClick={() => setActiveTab("memories")}
            className={`cursor-pointer rounded px-2 py-1 hover:bg-slate-800 ${
              activeTab === "memories" ? "bg-slate-800 text-white" : ""
            }`}
          >
            Memories
          </span>
          <span
            onClick={() => setActiveTab("settings")}
            className={`cursor-pointer rounded px-2 py-1 hover:bg-slate-800 ${
              activeTab === "settings" ? "bg-slate-800 text-white" : ""
            }`}
          >
            Settings
          </span>
        </nav>
      </aside>

      <main className="flex flex-1">
        {activeTab === "memories" && <MemoriesPage />}
        {activeTab === "dashboard" && (
          <div className="flex flex-1 items-center justify-center text-slate-400">
            Dashboard — coming later
          </div>
        )}
        {activeTab === "settings" && (
          <div className="flex flex-1 items-center justify-center text-slate-400">
            Settings — coming later
          </div>
        )}
      </main>
    </div>
  );
}

export default App;