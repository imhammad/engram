use active_win_pos_rs::get_active_window;
use serde_json::json;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager};

const POLL_INTERVAL_SECS: u64 = 5;
const DWELL_THRESHOLD_SECS: u64 = 30;

pub fn start_tracking(app: AppHandle, paused: Arc<AtomicBool>) {
    tauri::async_runtime::spawn(async move {
        let mut last_title = String::new();
        let mut window_start = Instant::now();
        let mut captured_this_session = false;
        let client = reqwest::Client::new();

        loop {
            if paused.load(Ordering::Relaxed) {
                tokio::time::sleep(Duration::from_secs(POLL_INTERVAL_SECS)).await;
                continue;
            }

            if let Ok(window) = get_active_window() {
                if window.title != last_title {
                    println!(
                        "[window-tracker] switched to: {} ({})",
                        window.title, window.app_name
                    );
                    last_title = window.title.clone();
                    window_start = Instant::now();
                    captured_this_session = false;

                    let payload = json!({
                        "window_title": window.title,
                        "app_name": window.app_name,
                    });
                    let _ = client
                        .post("http://127.0.0.1:8000/activity")
                        .json(&payload)
                        .send()
                        .await;
                } else {
                    let dwell_secs = window_start.elapsed().as_secs();
                    if !captured_this_session && dwell_secs >= DWELL_THRESHOLD_SECS {
                        println!(
                            "[window-tracker] dwell threshold reached on '{}' ({}s) — triggering capture",
                            window.title, dwell_secs
                        );
                        captured_this_session = true;

                        // --- UPDATED CAPTURE BLOCK START ---
                        let capture_client = client.clone();
                        let app_handle = app.clone();
                        let window_title = window.title.clone();
                        let region = json!({
                            "x": window.position.x as i64,
                            "y": window.position.y as i64,
                            "width": window.position.width as i64,
                            "height": window.position.height as i64,
                        });

                        tauri::async_runtime::spawn(async move {
                            let result = capture_client
                                .post("http://127.0.0.1:8000/capture/screen")
                                .json(&json!({ "region": region }))
                                .send()
                                .await;

                            if let Ok(response) = result {
                                if let Ok(body) = response.json::<serde_json::Value>().await {
                                    if body["saved"].as_bool() == Some(true) {
                                        if let Some(popup) = app_handle.get_webview_window("popup") {
                                            let message = if let Some(related) = body["related_memory"].as_object() {
                                                let related_content = related
                                                    .get("content")
                                                    .and_then(|c| c.as_str())
                                                    .unwrap_or("");
                                                let snippet: String = related_content.chars().take(80).collect();
                                                format!("This connects to something you saved before: \"{}...\"", snippet)
                                            } else {
                                                format!("Captured content from \"{}\"", window_title)
                                            };
                                            let _ = popup.emit("popup-message", message);
                                            let _ = popup.show();
                                        }
                                    }
                                }
                            }
                        });
                        
                    }
                }
            }
            tokio::time::sleep(Duration::from_secs(POLL_INTERVAL_SECS)).await;
        }
    });
}