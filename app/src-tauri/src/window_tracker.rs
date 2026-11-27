//! Follows the frontmost window, logs app switches, and captures a window
//! after it has been in front for a while. Excluded windows (see
//! exclusions.rs) are logged by app name only and never captured.

use active_win_pos_rs::get_active_window;
use serde::Serialize;
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager};

use crate::{engine, exclusions};

const POLL_INTERVAL_SECS: u64 = 5;
const DWELL_THRESHOLD_SECS: u64 = 30;
const EXCLUSION_REFRESH_SECS: u64 = 30;
const EXCLUDED_TITLE: &str = "[excluded]";

/// A window that may be captured: not Engram, not excluded.
#[derive(Clone, Serialize)]
pub struct WindowSnapshot {
    pub app_name: String,
    pub title: String,
    pub x: i64,
    pub y: i64,
    pub width: i64,
    pub height: i64,
}

/// The most recent capturable window, used by the manual Capture Screen button
/// so it captures what the user was looking at rather than Engram itself.
pub struct LastWindow(pub Mutex<Option<WindowSnapshot>>);

impl LastWindow {
    pub fn new() -> Self {
        Self(Mutex::new(None))
    }
}

async fn check_private(app_name: &str) -> bool {
    let name = app_name.to_string();
    tauri::async_runtime::spawn_blocking(move || exclusions::chromium_window_is_private(&name))
        .await
        .ok()
        .flatten()
        .unwrap_or(false)
}

/// Capture one window through the engine, with a tray hint while it runs.
pub async fn capture_window(app: &AppHandle, window: &WindowSnapshot, trigger: &str) -> Result<Value, String> {
    let req = engine::request(app, reqwest::Method::POST, "/capture/screen")
        .ok_or("the engine is not running")?;
    crate::set_capture_indicator(app, true);
    let result = req
        .json(&json!({
            "region": { "x": window.x, "y": window.y, "width": window.width, "height": window.height },
            "app_name": window.app_name,
            "window_title": window.title,
            "trigger": trigger,
        }))
        .send()
        .await;
    crate::set_capture_indicator(app, false);
    let response = result.map_err(|e| format!("capture request failed: {e}"))?;
    response.json::<Value>().await.map_err(|e| format!("bad capture response: {e}"))
}

async fn log_excluded(app: &AppHandle, app_name: &str, reason: &str) {
    if let Some(req) = engine::request(app, reqwest::Method::POST, "/ledger") {
        let _ = req
            .json(&json!({ "app_name": app_name, "trigger": "auto", "outcome": "excluded", "reason": reason }))
            .send()
            .await;
    }
}

fn popup_message(body: &Value, window: &WindowSnapshot) -> String {
    if let Some(related) = body["related_memory"].as_object() {
        let content = related.get("content").and_then(|c| c.as_str()).unwrap_or("");
        let snippet: String = content.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(140).collect();
        format!("This connects to something you saved before: \"{snippet}\"")
    } else if window.title.is_empty() {
        format!("Captured content from {}", window.app_name)
    } else {
        format!("Captured content from \"{}\"", window.title)
    }
}

pub fn start_tracking(app: AppHandle, paused: Arc<AtomicBool>) {
    tauri::async_runtime::spawn(async move {
        // Keyed on process and title: without Screen Recording permission macOS
        // reports empty titles, and app switches must still be noticed.
        let mut last_key = (0u64, String::new());
        let own_pid = std::process::id() as u64;
        let mut window_start = Instant::now();
        let mut handled_this_session = false;
        let mut last_refresh: Option<Instant> = None;
        let mut current_private = false;

        loop {
            tokio::time::sleep(Duration::from_secs(POLL_INTERVAL_SECS)).await;
            if paused.load(Ordering::Relaxed) || !engine::is_ready(&app) {
                continue;
            }
            if last_refresh.map_or(true, |t| t.elapsed().as_secs() >= EXCLUSION_REFRESH_SECS) {
                if exclusions::refresh(&app).await {
                    last_refresh = Some(Instant::now());
                }
            }
            // Without the exclusion list nothing is logged or captured.
            let Some(rules) = exclusions::current(&app) else {
                continue;
            };
            let Ok(window) = get_active_window() else {
                continue;
            };
            // Never track or capture Engram's own windows.
            if window.process_id == own_pid {
                continue;
            }

            let key = (window.process_id, window.title.clone());
            let is_switch = key != last_key;
            let mut excluded = rules.matches(&window.app_name, &window.title);
            // Asking a browser for its window mode costs an AppleScript call, so
            // do it once per window switch and remember the answer.
            if is_switch {
                current_private = check_private(&window.app_name).await;
            }
            if excluded.is_none() && current_private {
                excluded = Some("private browsing window".into());
            }
            let snapshot = WindowSnapshot {
                app_name: window.app_name.clone(),
                title: window.title.clone(),
                x: window.position.x as i64,
                y: window.position.y as i64,
                width: window.position.width as i64,
                height: window.position.height as i64,
            };
            if excluded.is_none() {
                *app.state::<LastWindow>().0.lock().unwrap() = Some(snapshot.clone());
            }

            if is_switch {
                last_key = key;
                window_start = Instant::now();
                handled_this_session = false;
                let logged_title = if excluded.is_some() { EXCLUDED_TITLE } else { window.title.as_str() };
                println!("[window-tracker] switched to {} {}", window.app_name, if excluded.is_some() { "(excluded)" } else { "" });
                if let Some(req) = engine::request(&app, reqwest::Method::POST, "/activity") {
                    let _ = req
                        .json(&json!({ "window_title": logged_title, "app_name": window.app_name }))
                        .send()
                        .await;
                }
                continue;
            }

            if handled_this_session || window_start.elapsed().as_secs() < DWELL_THRESHOLD_SECS {
                continue;
            }
            handled_this_session = true;

            if let Some(reason) = excluded {
                println!("[window-tracker] dwell on excluded window ({}), not capturing", window.app_name);
                log_excluded(&app, &window.app_name, &reason).await;
                continue;
            }

            println!("[window-tracker] dwell threshold reached on {}, capturing", window.app_name);
            let app_handle = app.clone();
            tauri::async_runtime::spawn(async move {
                if let Ok(body) = capture_window(&app_handle, &snapshot, "auto").await {
                    if body["saved"].as_bool() == Some(true) {
                        crate::present_popup(&app_handle, &popup_message(&body, &snapshot));
                    }
                }
            });
        }
    });
}

/// The Capture Screen button: capture the last window the user had in front
/// before switching to Engram, after re-checking it against the rules.
#[tauri::command]
pub async fn capture_previous_window(app: AppHandle) -> Result<Value, String> {
    let snapshot = app
        .state::<LastWindow>()
        .0
        .lock()
        .unwrap()
        .clone()
        .ok_or("Switch to the window you want to capture, then come back and press Capture Screen.")?;
    exclusions::refresh(&app).await;
    if let Some(reason) = exclusions::current(&app).and_then(|r| r.matches(&snapshot.app_name, &snapshot.title)) {
        return Ok(json!({ "saved": false, "reason": format!("Not captured: {reason}.") }));
    }
    if check_private(&snapshot.app_name).await {
        return Ok(json!({ "saved": false, "reason": "Not captured: private browsing window." }));
    }
    // The captured window is usually behind Engram, and a screen grab sees
    // whatever is on top, so step out of the way for the moment of capture.
    let main = app.get_webview_window("main");
    let was_visible = main.as_ref().and_then(|w| w.is_visible().ok()).unwrap_or(false);
    if was_visible {
        if let Some(w) = &main {
            let _ = w.hide();
        }
        tokio::time::sleep(Duration::from_millis(350)).await;
    }
    let result = capture_window(&app, &snapshot, "manual").await;
    if was_visible {
        if let Some(w) = &main {
            let _ = w.show();
            let _ = w.set_focus();
        }
    }
    result
}
