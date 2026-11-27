//! Lifecycle of the Python AI engine sidecar: where its data lives, starting
//! it, waiting until it is ready, and stopping it when the app exits.

use serde::Serialize;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Header carrying the per-launch token; the engine rejects requests without it.
pub const TOKEN_HEADER: &str = "X-Engram-Token";

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

/// Where the engine listens and the secret it expects, fresh for every launch.
#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineConnection {
    pub base_url: String,
    pub token: String,
}

pub struct EngineState {
    child: Mutex<Option<CommandChild>>,
    status: Mutex<EngineStatus>,
    connection: Mutex<Option<EngineConnection>>,
    client: reqwest::Client,
}

impl EngineState {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            status: Mutex::new(EngineStatus { state: "starting", detail: None }),
            connection: Mutex::new(None),
            client: reqwest::Client::builder()
                .timeout(Duration::from_secs(60))
                .build()
                .expect("failed to build HTTP client"),
        }
    }
}

/// The frontend asks for this once and sends the token on every request.
#[tauri::command]
pub fn engine_connection(state: tauri::State<EngineState>) -> Result<EngineConnection, String> {
    state
        .connection
        .lock()
        .unwrap()
        .clone()
        .ok_or_else(|| "the engine connection is not set up".to_string())
}

/// Build an authenticated request to the engine, if it has been configured.
pub fn request(app: &AppHandle, method: reqwest::Method, path: &str) -> Option<reqwest::RequestBuilder> {
    let state = app.state::<EngineState>();
    let conn = state.connection.lock().unwrap().clone()?;
    Some(
        state
            .client
            .request(method, format!("{}{}", conn.base_url, path))
            .header(TOKEN_HEADER, conn.token),
    )
}

/// 256 random bits from the operating system, hex encoded.
fn generate_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("could not generate a token: {e}"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

/// Ask the OS for a free loopback port. There is a small window between
/// releasing it here and the engine binding it; a clash shows up as the
/// engine exiting, which is reported like any other start failure.
fn pick_free_port() -> Result<u16, String> {
    let listener = std::net::TcpListener::bind(("127.0.0.1", 0))
        .map_err(|e| format!("could not find a free port: {e}"))?;
    listener
        .local_addr()
        .map(|addr| addr.port())
        .map_err(|e| format!("could not read the free port: {e}"))
}

fn set_connection(app: &AppHandle, port: u16, token: String) {
    *app.state::<EngineState>().connection.lock().unwrap() = Some(EngineConnection {
        base_url: format!("http://127.0.0.1:{port}"),
        token,
    });
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
    let app = app.clone();
    // Off the main thread: reading the key can wait on a macOS Keychain
    // prompt, and the window must stay responsive (showing "Starting
    // Engram") while the user answers it.
    tauri::async_runtime::spawn(async move {
        let dev_engine = std::env::var("ENGRAM_DEV_ENGINE").map(|v| v == "1").unwrap_or(false);
        let result = if dev_engine {
            // The developer started the engine by hand with these two variables.
            match (std::env::var("ENGRAM_TOKEN"), std::env::var("ENGRAM_PORT")) {
                (Ok(token), port) if token.len() >= 32 => {
                    let port = port.ok().and_then(|p| p.parse().ok()).unwrap_or(8000);
                    println!("[engine] ENGRAM_DEV_ENGINE=1: using the engine already running on port {port}");
                    set_connection(&app, port, token);
                    Ok(())
                }
                _ => Err("ENGRAM_DEV_ENGINE=1 needs ENGRAM_TOKEN (32+ characters) and ENGRAM_PORT, the same values the engine was started with".to_string()),
            }
        } else {
            let handle = app.clone();
            tauri::async_runtime::spawn_blocking(move || spawn_sidecar(&handle))
                .await
                .unwrap_or_else(|e| Err(format!("engine start task failed: {e}")))
        };
        if let Err(err) = result {
            eprintln!("[engine] {err}");
            set_status(&app, "failed", Some(err));
            return;
        }
        wait_until_ready(app).await;
    });
}

fn spawn_sidecar(app: &AppHandle) -> Result<(), String> {
    let data_dir = resolve_dir(app, "ENGRAM_DATA_DIR", "data")?;
    let model_dir = resolve_dir(app, "ENGRAM_MODEL_DIR", "models")?;
    println!("[engine] data dir:  {}", data_dir.display());
    println!("[engine] model dir: {}", model_dir.display());

    let token = generate_token()?;
    let port = pick_free_port()?;
    set_status(app, "starting", Some("Waiting for the database key from the Keychain".into()));
    let db_key = crate::keys::database_key()?;
    set_status(app, "starting", None);
    println!("[engine] port:      {port}");

    let mut command = app
        .shell()
        .sidecar("engram-ai-engine")
        .map_err(|e| format!("could not find the engine sidecar: {e}"))?
        .env("ENGRAM_DATA_DIR", &data_dir)
        .env("ENGRAM_MODEL_DIR", &model_dir)
        .env("ENGRAM_TOKEN", &token)
        .env("ENGRAM_PORT", port.to_string())
        // Lets the engine notice if the app dies without stopping it.
        .env("ENGRAM_PARENT_PID", std::process::id().to_string());
    if cfg!(debug_assertions) {
        // `tauri dev` serves the UI from Vite, so allow that origin too.
        command = command.env("ENGRAM_DEV_ORIGIN", "http://localhost:1420");
    }
    let (mut rx, mut child) = command
        .spawn()
        .map_err(|e| format!("could not start the engine sidecar: {e}"))?;
    // The database key goes over stdin: unlike argv and the environment,
    // other processes cannot read it. It is never logged.
    child
        .write(format!("{db_key}\n").as_bytes())
        .map_err(|e| format!("could not hand the database key to the engine: {e}"))?;
    drop(db_key);
    *app.state::<EngineState>().child.lock().unwrap() = Some(child);
    set_connection(app, port, token);

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
    let started = Instant::now();

    while started.elapsed() < READY_TIMEOUT {
        if app.state::<EngineState>().status.lock().unwrap().state == "failed" {
            return;
        }
        let Some(req) = request(&app, reqwest::Method::GET, "/health") else {
            return;
        };
        if let Ok(resp) = req.timeout(Duration::from_secs(2)).send().await {
            if resp.status() == reqwest::StatusCode::UNAUTHORIZED {
                // Something else is listening on our port and does not know the token.
                set_status(&app, "failed", Some("another program answered on the engine's port".into()));
                return;
            }
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

/// Tell the engine the user quit, so the open activity session ends now.
pub fn notify_quit(app: &AppHandle) {
    if !is_ready(app) {
        return;
    }
    if let Some(req) = request(app, reqwest::Method::POST, "/activity/stop") {
        let send = req
            .timeout(Duration::from_secs(1))
            .json(&serde_json::json!({ "reason": "quit" }))
            .send();
        let _ = tauri::async_runtime::block_on(send);
    }
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
