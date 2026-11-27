import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import "./App.css";
import MemoriesPage from "./components/MemoriesPage";
import DashboardPage from "./components/DashboardPage";
import SettingsPage from "./components/SettingsPage";
import LedgerPage from "./components/LedgerPage";

type Tab = "dashboard" | "memories" | "ledger" | "settings";

type EngineStatus = {
  state: "starting" | "ready" | "failed";
  detail: string | null;
};

function useEngineStatus(): EngineStatus {
  const [status, setStatus] = useState<EngineStatus>({
    state: "starting",
    detail: null,
  });

  useEffect(() => {
    let active = true;
    const unlisten = listen<EngineStatus>("engine-status", (event) => {
      if (active) setStatus(event.payload);
    });
    // The engine may have become ready before this component mounted.
    invoke<EngineStatus>("engine_status").then((current) => {
      if (active) setStatus(current);
    });
    return () => {
      active = false;
      unlisten.then((fn) => fn());
    };
  }, []);

  return status;
}

function EngineStarting({ status }: { status: EngineStatus }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="max-w-sm text-center">
        {status.state === "failed" ? (
          <>
            <p className="text-sm font-medium text-ink">
              Engram could not start its engine
            </p>
            <p className="mt-2 text-sm text-ink-muted">{status.detail}</p>
            <p className="mt-2 text-xs text-ink-muted">
              If the models are missing, run scripts/fetch_models.py once and
              restart Engram.
            </p>
          </>
        ) : (
          <>
            <p className="text-sm font-medium text-ink">Starting Engram</p>
            {status.detail ? (
              <p className="mt-2 text-sm text-ink-muted">
                {status.detail}. If macOS asks whether Engram may use
                "dev.engram.app" in your Keychain, choose Always Allow.
              </p>
            ) : (
              <p className="mt-2 text-sm text-ink-muted">
                Loading the on-device models. This takes a few seconds.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState<Tab>("memories");
  const engine = useEngineStatus();

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
          Engram
        </h1>
        <nav className="flex flex-col gap-1">
          {navItem("dashboard", "Dashboard")}
          {navItem("memories", "Memories")}
          {navItem("ledger", "Ledger")}
          {navItem("settings", "Settings")}
        </nav>
      </aside>

      <main className="flex flex-1">
        {engine.state !== "ready" ? (
          <EngineStarting status={engine} />
        ) : (
          <>
            {activeTab === "memories" && <MemoriesPage />}
            {activeTab === "dashboard" && <DashboardPage />}
            {activeTab === "ledger" && <LedgerPage />}
            {activeTab === "settings" && <SettingsPage />}
          </>
        )}
      </main>
    </div>
  );
}

export default App;