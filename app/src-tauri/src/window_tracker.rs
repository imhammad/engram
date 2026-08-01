use active_win_pos_rs::get_active_window;
use serde_json::json;
use std::time::{Duration, Instant};

const POLL_INTERVAL_SECS: u64 = 5;
const DWELL_THRESHOLD_SECS: u64 = 30;

pub fn start_tracking() {
    tauri::async_runtime::spawn(async move {
        let mut last_title = String::new();
        let mut window_start = Instant::now();
        let mut captured_this_session = false;
        let client = reqwest::Client::new();

        loop {
            if let Ok(window) = get_active_window() {
                if window.title != last_title {
                    // Window changed — reset the dwell timer and capture flag
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
                    // Same window — check how long they've dwelled here
                    let dwell_secs = window_start.elapsed().as_secs();
                    if !captured_this_session && dwell_secs >= DWELL_THRESHOLD_SECS {
                        println!(
                            "[window-tracker] dwell threshold reached on '{}' ({}s) — triggering capture",
                            window.title, dwell_secs
                        );
                        captured_this_session = true;

                        // Spawn as a separate task so a slow OCR capture
                        // never blocks our 5-second polling loop.
                        let capture_client = client.clone();
                        tauri::async_runtime::spawn(async move {
                            let _ = capture_client
                                .post("http://127.0.0.1:8000/capture/screen")
                                .send()
                                .await;
                        });
                    }
                }
            }
            tokio::time::sleep(Duration::from_secs(POLL_INTERVAL_SECS)).await;
        }
    });
}