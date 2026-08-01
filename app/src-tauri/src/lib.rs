// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/

use tauri_plugin_shell::ShellExt;
mod window_tracker;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tauri::Manager;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[tauri::command]
fn ping() -> String {
    "pong from rust".into()
}

struct CaptureState {
    paused: Arc<AtomicBool>,
}

#[tauri::command]
fn set_capture_paused(state: tauri::State<CaptureState>, paused: bool) {
    state.paused.store(paused, Ordering::Relaxed);
}

#[tauri::command]
fn get_capture_paused(state: tauri::State<CaptureState>) -> bool {
    state.paused.load(Ordering::Relaxed)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![greet, ping, set_capture_paused, get_capture_paused])
        .setup(|app| {
            let model_dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../../ai-engine/models");
            let data_dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../../ai-engine/data");
            let paused = Arc::new(AtomicBool::new(false));
            app.manage(CaptureState { paused: paused.clone() });
            window_tracker::start_tracking(paused);

            let sidecar = app
                .shell()
                .sidecar("engram-ai-engine")
                .expect("failed to create sidecar command")
                .env("ENGRAM_MODEL_DIR", model_dir)
                .env("ENGRAM_DATA_DIR", data_dir);
            let (mut _rx, _child) = sidecar.spawn().expect("failed to spawn ai engine sidecar");
            Ok(())
            })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

