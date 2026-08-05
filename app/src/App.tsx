import { useState } from "react";
import "./App.css";
import MemoriesPage from "./components/MemoriesPage";

type Tab = "dashboard" | "memories" | "settings";

function App() {
  const [activeTab, setActiveTab] = useState<Tab>("memories");

  const navItem = (tab: Tab, label: string) => (
    <span
      onClick={() => setActiveTab(tab)}
      className={`cursor-pointer rounded-md px-3 py-2 text-sm font-medium transition-colors ${
        activeTab === tab
          ? "bg-surface text-accent shadow-sm"
          : "text-ink-muted hover:bg-surface/60"
      }`}
    >
      {label}
    </span>
  );

  return (
    <div className="flex h-screen w-screen bg-canvas font-sans text-ink">
      <aside className="w-64 border-r border-border bg-surface-muted p-4">
        <h1 className="mb-6 flex items-center gap-2 text-lg font-semibold">
          🧠 Engram
        </h1>
        <nav className="flex flex-col gap-1">
          {navItem("dashboard", "Dashboard")}
          {navItem("memories", "Memories")}
          {navItem("settings", "Settings")}
        </nav>
      </aside>

      <main className="flex flex-1">
        {activeTab === "memories" && <MemoriesPage />}
        {activeTab === "dashboard" && (
          <div className="flex flex-1 items-center justify-center text-ink-muted">
            Dashboard — coming later
          </div>
        )}
        {activeTab === "settings" && (
          <div className="flex flex-1 items-center justify-center text-ink-muted">
            Settings — coming later
          </div>
        )}
      </main>
    </div>
  );
}

export default App;