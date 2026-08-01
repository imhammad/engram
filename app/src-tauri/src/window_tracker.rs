use active_win_pos_rs::get_active_window;
use serde_json::json;
use std::time::Duration;

pub fn start_tracking() {
    tauri::async_runtime::spawn(async move {
        let mut last_title = String::new();
        let client = reqwest::Client::new();

        loop {
            if let Ok(window) = get_active_window() {
                if window.title != last_title {
                    println!(
                        "[window-tracker] switched to: {} ({})",
                        window.title, window.app_name
                    );
                    last_title = window.title.clone();

                    let payload = json!({
                        "window_title": window.title,
                        "app_name": window.app_name,
                    });

                    let _ = client
                        .post("http://127.0.0.1:8000/activity")
                        .json(&payload)
                        .send()
                        .await;
                }
            }
            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    });
}