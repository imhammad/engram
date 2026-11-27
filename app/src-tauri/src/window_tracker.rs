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

use crate::{ax, engine, exclusions};

const POLL_INTERVAL_SECS: u64 = 5;
/// Defaults until the engine's capture settings have been read.
const DEFAULT_DWELL_SECS: u64 = 30;
const DEFAULT_RECAPTURE_MINUTES: u64 = 2;
const EXCLUSION_REFRESH_SECS: u64 = 30;
const EXCLUDED_TITLE: &str = "[excluded]";
/// No keyboard or mouse input for this long ends the current session.
const IDLE_THRESHOLD_SECS: f64 = 5.0 * 60.0;
/// A gap this long between two polls means the Mac was asleep.
const SLEEP_GAP_SECS: u64 = POLL_INTERVAL_SECS * 4;

/// A window that may be captured: not Engram, not excluded.
#[derive(Clone, Serialize)]
pub struct WindowSnapshot {
    pub app_name: String,
    pub title: String,
    pub x: i64,
    pub y: i64,
    pub width: i64,
    pub height: i64,
    #[serde(skip)]
    pub process_id: u64,
    #[serde(skip)]
    pub process_path: String,
}

impl WindowSnapshot {
    fn from_active(window: &active_win_pos_rs::ActiveWindow) -> Self {
        Self {
            app_name: window.app_name.clone(),
            title: window.title.clone(),
            x: window.position.x as i64,
            y: window.position.y as i64,
            width: window.position.width as i64,
            height: window.position.height as i64,
            process_id: window.process_id,
            process_path: window.process_path.to_string_lossy().into_owned(),
        }
    }

    fn same_bounds(&self, other: &Self) -> bool {
        (self.x, self.y, self.width, self.height) == (other.x, other.y, other.width, other.height)
    }
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

/// How long to wait before the first capture of a window, and how often to
/// look again while the user stays on it. Read from the engine (Settings).
#[derive(Clone, Copy, serde::Deserialize)]
pub struct CaptureTiming {
    pub dwell_seconds: u64,
    pub recapture_minutes: u64,
}

pub struct TimingState(pub Mutex<CaptureTiming>);

impl TimingState {
    pub fn new() -> Self {
        Self(Mutex::new(CaptureTiming {
            dwell_seconds: DEFAULT_DWELL_SECS,
            recapture_minutes: DEFAULT_RECAPTURE_MINUTES,
        }))
    }
}

async fn refresh_timing(app: &AppHandle) -> bool {
    let Some(req) = engine::request(app, reqwest::Method::GET, "/settings/capture") else {
        return false;
    };
    let Ok(resp) = req.send().await else { return false };
    match resp.json::<CaptureTiming>().await {
        Ok(timing) => {
            *app.state::<TimingState>().0.lock().unwrap() = timing;
            true
        }
        Err(_) => false,
    }
}

/// Called by the Settings page right after the timing changes.
#[tauri::command]
pub async fn refresh_capture_settings(app: AppHandle) -> Result<(), String> {
    if refresh_timing(&app).await { Ok(()) } else { Err("could not load capture settings".into()) }
}

/// Read the window's text through Accessibility, off the async runtime.
/// Only valid while the window is frontmost.
async fn read_accessibility(window: &WindowSnapshot) -> Option<ax::AxText> {
    let (pid, chromium) = (window.process_id, exclusions::is_chromium(&window.app_name));
    tauri::async_runtime::spawn_blocking(move || ax::read_front_window(pid, chromium))
        .await
        .ok()
        .flatten()
}

/// Capture one window through the engine, with a tray hint while it runs.
/// Accessibility text goes along when there is any; the engine falls back
/// to OCR of the region otherwise (ADR 0009).
pub async fn capture_window(app: &AppHandle, window: &WindowSnapshot, trigger: &str) -> Result<Value, String> {
    let req = engine::request(app, reqwest::Method::POST, "/capture/screen")
        .ok_or("the engine is not running")?;
    crate::set_capture_indicator(app, true);
    let ax = read_accessibility(window).await;
    let result = req
        .json(&json!({
            "region": { "x": window.x, "y": window.y, "width": window.width, "height": window.height },
            "app_name": window.app_name,
            "window_title": window.title,
            "url": ax.as_ref().map(|a| a.url.as_str()).unwrap_or(""),
            "text": ax.as_ref().map(|a| a.text.as_str()).filter(|t| !t.trim().is_empty()),
            "trigger": trigger,
        }))
        .send()
        .await;
    crate::set_capture_indicator(app, false);
    let response = result.map_err(|e| format!("capture request failed: {e}"))?;
    response.json::<Value>().await.map_err(|e| format!("bad capture response: {e}"))
}

async fn stop_activity(app: &AppHandle, reason: &str, seconds_ago: f64) {
    if let Some(req) = engine::request(app, reqwest::Method::POST, "/activity/stop") {
        let _ = req
            .json(&json!({ "reason": reason, "ended_seconds_ago": seconds_ago }))
            .send()
            .await;
    }
}

async fn log_excluded(app: &AppHandle, app_name: &str, reason: &str) {
    if let Some(req) = engine::request(app, reqwest::Method::POST, "/ledger") {
        let _ = req
            .json(&json!({ "app_name": app_name, "trigger": "dwell", "outcome": "excluded", "reason": reason }))
            .send()
            .await;
    }
}

/// With automatic recapture, a popup for every save would be constant noise,
/// so the popup only appears when a capture connects to an earlier memory.
fn connection_message(body: &Value) -> Option<String> {
    let related = body["related_memory"].as_object()?;
    let content = related.get("content").and_then(|c| c.as_str()).unwrap_or("");
    let snippet: String = content.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(140).collect();
    Some(format!("This connects to something you saved before: \"{snippet}\""))
}

pub fn start_tracking(app: AppHandle, paused: Arc<AtomicBool>) {
    tauri::async_runtime::spawn(async move {
        // Keyed on process and title: without Screen Recording permission macOS
        // reports empty titles, and app switches must still be noticed.
        let mut last_key = (0u64, String::new());
        let own_pid = std::process::id() as u64;
        let mut window_start = Instant::now();
        let mut handled_this_session = false;
        // When the current window was last captured or re-checked.
        let mut last_look: Option<Instant> = None;
        let mut last_refresh: Option<Instant> = None;
        let mut current_private = false;
        // Set while activity is stopped (idle, sleep, lock, pause); the next
        // window seen after that starts a fresh session.
        let mut away = false;
        // Wall-clock time of the previous poll. Monotonic time stops while
        // the Mac sleeps, so only the wall clock shows the gap.
        let mut last_tick = std::time::SystemTime::now();

        loop {
            tokio::time::sleep(Duration::from_secs(POLL_INTERVAL_SECS)).await;
            let now = std::time::SystemTime::now();
            let gap = now.duration_since(last_tick).map(|d| d.as_secs()).unwrap_or(0);
            last_tick = now;
            if !engine::is_ready(&app) {
                continue;
            }

            // Work out whether the user has stepped away, and end the session if so.
            let stop = if gap >= SLEEP_GAP_SECS {
                Some(("sleep", gap as f64))
            } else if paused.load(Ordering::Relaxed) {
                Some(("pause", 0.0))
            } else if crate::presence::screen_locked() {
                Some(("lock", 0.0))
            } else {
                let idle = crate::presence::idle_seconds();
                (idle >= IDLE_THRESHOLD_SECS).then_some(("idle", idle))
            };
            if let Some((reason, seconds_ago)) = stop {
                // Sleep is reported even if already away, since it ends at the gap.
                if !away || reason == "sleep" {
                    println!("[window-tracker] activity stopped ({reason})");
                    stop_activity(&app, reason, seconds_ago).await;
                }
                away = true;
                if reason != "sleep" {
                    continue;
                }
            }
            if away {
                // Back: treat the current window as a new session.
                away = false;
                last_key = (0, String::new());
            }
            if last_refresh.map_or(true, |t| t.elapsed().as_secs() >= EXCLUSION_REFRESH_SECS) {
                refresh_timing(&app).await;
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
            // Never track or capture Engram's own windows, or system dialogs
            // (notification and permission prompts, the lock screen).
            if window.process_id == own_pid || rules.is_system_process(&window.app_name) {
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
            let snapshot = WindowSnapshot::from_active(&window);
            if excluded.is_none() {
                *app.state::<LastWindow>().0.lock().unwrap() = Some(snapshot.clone());
            }

            if is_switch {
                last_key = key;
                window_start = Instant::now();
                handled_this_session = false;
                last_look = None;
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

            let timing = *app.state::<TimingState>().0.lock().unwrap();
            let trigger = if !handled_this_session {
                if window_start.elapsed().as_secs() < timing.dwell_seconds {
                    continue;
                }
                handled_this_session = true;
                if let Some(reason) = excluded {
                    println!("[window-tracker] dwell on excluded window ({}), not capturing", window.app_name);
                    log_excluded(&app, &window.app_name, &reason).await;
                    continue;
                }
                "dwell"
            } else {
                // Still on the same window: look again on the recapture interval.
                let due = timing.recapture_minutes > 0
                    && last_look.is_some_and(|t| t.elapsed().as_secs() >= timing.recapture_minutes * 60);
                if excluded.is_some() || !due {
                    continue;
                }
                "recheck"
            };
            last_look = Some(Instant::now());

            println!("[window-tracker] {trigger} capture of {}", window.app_name);
            let app_handle = app.clone();
            tauri::async_runtime::spawn(async move {
                if let Ok(body) = capture_window(&app_handle, &snapshot, trigger).await {
                    if body["saved"].as_bool() == Some(true) {
                        if let Some(message) = connection_message(&body) {
                            crate::present_popup(&app_handle, &message);
                        }
                    }
                }
            });
        }
    });
}

/// The .app bundle that contains an executable, e.g.
/// /Applications/Google Chrome.app/Contents/MacOS/Google Chrome -> /Applications/Google Chrome.app
pub fn app_bundle_for(process_path: &str) -> Option<String> {
    std::path::Path::new(process_path)
        .ancestors()
        .find(|p| p.extension().is_some_and(|e| e == "app"))
        .map(|p| p.to_string_lossy().into_owned())
}

/// Bring an app to the front. `open -a` needs no extra permission.
fn activate_app(window: &WindowSnapshot) {
    #[cfg(target_os = "macos")]
    {
        let target = app_bundle_for(&window.process_path).unwrap_or_else(|| window.app_name.clone());
        let _ = std::process::Command::new("open").arg("-a").arg(target).status();
    }
    #[cfg(not(target_os = "macos"))]
    let _ = window;
}

/// Wait until the target app is frontmost and its window has stopped moving
/// (Stage Manager and Mission Control animate windows into place), then
/// return the window as it is now. None if it did not come forward in time.
async fn wait_until_front_and_settled(target_pid: u64) -> Option<WindowSnapshot> {
    let deadline = Instant::now() + Duration::from_millis(2500);
    let mut previous: Option<WindowSnapshot> = None;
    while Instant::now() < deadline {
        if let Ok(window) = get_active_window() {
            if window.process_id == target_pid {
                let current = WindowSnapshot::from_active(&window);
                if previous.as_ref().is_some_and(|p| p.same_bounds(&current)) {
                    return Some(current);
                }
                previous = Some(current);
            }
        }
        tokio::time::sleep(Duration::from_millis(120)).await;
    }
    previous
}

/// The Capture Screen button: capture the last window the user had in front
/// before switching to Engram.
///
/// That window is not on screen while Engram is in front: with Stage Manager
/// on it has been shrunk into the side strip, and without it Engram covers
/// it. A screen grab of its old position therefore saw the desktop or
/// Engram, and the capture was dropped as unreadable. So Engram hides
/// itself, brings the target app forward, waits for its window to settle,
/// re-reads where the window now is, captures that, and comes back.
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

    let main = app.get_webview_window("main");
    let was_visible = main.as_ref().and_then(|w| w.is_visible().ok()).unwrap_or(false);
    if let (true, Some(w)) = (was_visible, &main) {
        let _ = w.hide();
    }
    activate_app(&snapshot);
    let fresh = wait_until_front_and_settled(snapshot.process_id).await;

    let result = match fresh {
        None => Ok(json!({
            "saved": false,
            "reason": format!("Could not bring {} to the front to capture it.", snapshot.app_name),
        })),
        Some(window) => {
            // The front window may not be the one remembered (another window
            // of the same app); check what is actually about to be captured.
            let excluded = exclusions::current(&app).and_then(|r| r.matches(&window.app_name, &window.title));
            if let Some(reason) = excluded {
                Ok(json!({ "saved": false, "reason": format!("Not captured: {reason}.") }))
            } else if check_private(&window.app_name).await {
                Ok(json!({ "saved": false, "reason": "Not captured: private browsing window." }))
            } else {
                // A moment for the window's content to finish redrawing.
                tokio::time::sleep(Duration::from_millis(150)).await;
                capture_window(&app, &window, "manual").await
            }
        }
    };

    if let (true, Some(w)) = (was_visible, &main) {
        let _ = w.show();
        let _ = w.set_focus();
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snap(x: i64, y: i64, w: i64, h: i64) -> WindowSnapshot {
        WindowSnapshot {
            app_name: "Google Chrome".into(),
            title: "t".into(),
            x,
            y,
            width: w,
            height: h,
            process_id: 1,
            process_path: String::new(),
        }
    }

    #[test]
    fn finds_the_app_bundle_of_an_executable() {
        assert_eq!(
            app_bundle_for("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").as_deref(),
            Some("/Applications/Google Chrome.app")
        );
        assert_eq!(
            app_bundle_for("/Applications/Xcode.app/Contents/Developer/Applications/Simulator.app/Contents/MacOS/Simulator").as_deref(),
            Some("/Applications/Xcode.app/Contents/Developer/Applications/Simulator.app")
        );
        assert_eq!(app_bundle_for("/usr/bin/python3"), None);
    }

    #[test]
    fn bounds_compare_position_and_size() {
        assert!(snap(200, 117, 1321, 849).same_bounds(&snap(200, 117, 1321, 849)));
        // A Stage Manager thumbnail versus the window on stage.
        assert!(!snap(16, 393, 125, 128).same_bounds(&snap(200, 117, 1321, 849)));
    }
}
