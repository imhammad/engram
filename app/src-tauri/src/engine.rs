//! Lifecycle of the Python AI engine sidecar: where its data lives, starting
//! it, waiting until it is ready, and stopping it when the app exits.

use serde::Serialize;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

pub const ENGINE_URL: &str = "http://127.0.0.1:8000";

/// The onefile sidecar unpacks itself and loads three models before it
/// answers: about 30 seconds normally on an M-series Mac, and over 80 seconds
/// the first time a newly built binary runs while macOS scans it. Leave headroom.
const READY_TIMEOUT: Duration = Duration::from_secs(120);
const POLL_INTERVAL: Duration = Duration::from_millis(500);

#[derive(Clone, Serialize)]
pub struct EngineStatus {
    /// "starting", "ready" or "failed".
    pub state: &'static str,
    pub detail: Option<String>,
}

pub struct EngineState {
    child: Mutex<Option<CommandChild>>,
    status: Mutex<EngineStatus>,
}

impl EngineState {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            status: Mutex::new(EngineStatus { state: "starting", detail: None }),
        }
    }
}

#[tauri::command]
pub fn engine_status(state: tauri::State<EngineState>) -> EngineStatus {
    state.status.lock().unwrap().clone()
}

pub fn is_ready(app: &AppHandle) -> bool {
    app.state::<EngineState>().status.lock().unwrap().state == "ready"
}

fn set_status(app: &AppHandle, state: &'static str, detail: Option<String>) {
    let status = EngineStatus { state, detail };
    *app.state::<EngineState>().status.lock().unwrap() = status.clone();
    let _ = app.emit("engine-status", status);
}

/// Resolve a directory from an environment override, or else from the app data dir.
fn resolve_dir(app: &AppHandle, env_var: &str, sub: &str) -> Result<PathBuf, String> {
    let dir = match std::env::var_os(env_var) {
        Some(value) if !value.is_empty() => PathBuf::from(value),
        _ => app
            .path()
            .app_data_dir()
            .map_err(|e| format!("could not resolve the app data directory: {e}"))?
            .join(sub),
    };
    std::fs::create_dir_all(&dir).map_err(|e| format!("could not create {}: {e}", dir.display()))?;
    Ok(dir)
}

/// Start the engine (unless ENGRAM_DEV_ENGINE=1) and wait for it in the background.
pub fn start(app: &AppHandle) {
    let dev_engine = std::env::var("ENGRAM_DEV_ENGINE").map(|v| v == "1").unwrap_or(false);

    if dev_engine {
        println!("[engine] ENGRAM_DEV_ENGINE=1: not spawning the sidecar, expecting a running engine at {ENGINE_URL}");
    } else if let Err(err) = spawn_sidecar(app) {
        eprintln!("[engine] {err}");
        set_status(app, "failed", Some(err));
        return;
    }

    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        wait_until_ready(app).await;
    });
}

fn spawn_sidecar(app: &AppHandle) -> Result<(), String> {
    let data_dir = resolve_dir(app, "ENGRAM_DATA_DIR", "data")?;
    let model_dir = resolve_dir(app, "ENGRAM_MODEL_DIR", "models")?;
    println!("[engine] data dir:  {}", data_dir.display());
    println!("[engine] model dir: {}", model_dir.display());

    let command = app
        .shell()
        .sidecar("engram-ai-engine")
        .map_err(|e| format!("could not find the engine sidecar: {e}"))?
        .env("ENGRAM_DATA_DIR", &data_dir)
        .env("ENGRAM_MODEL_DIR", &model_dir);
    let (mut rx, child) = command
        .spawn()
        .map_err(|e| format!("could not start the engine sidecar: {e}"))?;
    *app.state::<EngineState>().child.lock().unwrap() = Some(child);

    // Forward the engine's output to our log, and notice if it dies early.
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    println!("[engine] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Terminated(payload) => {
                    let detail = format!("the engine exited (code {:?})", payload.code);
                    eprintln!("[engine] {detail}");
                    app.state::<EngineState>().child.lock().unwrap().take();
                    set_status(&app, "failed", Some(detail));
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

async fn wait_until_ready(app: AppHandle) {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .expect("failed to build HTTP client");
    let started = Instant::now();

    while started.elapsed() < READY_TIMEOUT {
        if app.state::<EngineState>().status.lock().unwrap().state == "failed" {
            return;
        }
        if let Ok(resp) = client.get(format!("{ENGINE_URL}/health")).send().await {
            if resp.status().is_success() {
                println!("[engine] ready after {:.1}s", started.elapsed().as_secs_f32());
                set_status(&app, "ready", None);
                return;
            }
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }

    let detail = format!("the engine did not become ready within {}s", READY_TIMEOUT.as_secs());
    eprintln!("[engine] {detail}");
    set_status(&app, "failed", Some(detail));
}

/// Stop the sidecar so no orphaned engine keeps holding port 8000.
///
/// The onefile build is two processes: a PyInstaller bootloader and the Python
/// engine it unpacks and starts. SIGKILL on the bootloader cannot be passed on,
/// which would orphan the engine, so ask politely with SIGTERM first (the
/// bootloader forwards it and uvicorn shuts down cleanly), and only force it
/// if that does not work.
pub fn stop(app: &AppHandle) {
    let Some(child) = app.state::<EngineState>().child.lock().unwrap().take() else {
        return;
    };
    let pid = child.pid();
    println!("[engine] stopping sidecar (pid {pid})");

    #[cfg(unix)]
    {
        let pid = pid as libc::pid_t;
        // SAFETY: signalling a process we spawned and still own.
        unsafe { libc::kill(pid, libc::SIGTERM) };
        let deadline = Instant::now() + Duration::from_secs(5);
        // kill(pid, 0) fails once the process has exited and been reaped.
        while Instant::now() < deadline && unsafe { libc::kill(pid, 0) } == 0 {
            std::thread::sleep(Duration::from_millis(100));
        }
        if unsafe { libc::kill(pid, 0) } != 0 {
            return;
        }
        eprintln!("[engine] sidecar did not exit after SIGTERM, killing it");
    }
    let _ = child.kill();
}
