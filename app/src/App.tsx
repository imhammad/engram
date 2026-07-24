import "./App.css";

function App() {
  return (
    <div className="flex h-screen w-screen bg-slate-900 text-white">
      {/* Sidebar */}
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

      {/* Main content */}
      <main className="flex flex-1 items-center justify-center">
        <p className="text-slate-400">
          Main content area: this is where features will live.
        </p>
      </main>
    </div>
  );
}

export default App;