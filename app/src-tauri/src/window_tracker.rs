use active_win_pos_rs::get_active_window;
use std::time::Duration;
use tauri::AppHandle;
use tauri_plugin_shell::ShellExt;

pub fn start_tracking(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut last_title = String::new();

        loop {
            if let Ok(window) = get_active_window() {
                if window.title != last_title {
                    println!(
                        "[window-tracker] switched to: {} ({})",
                        window.title, window.app_name
                    );
                    last_title = window.title.clone();
                    // In the next step, we'll send this to the Python
                    // engine instead of just printing it.
                }
            }
            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    });
}