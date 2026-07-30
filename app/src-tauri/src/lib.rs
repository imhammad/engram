// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/

use tauri_plugin_shell::ShellExt;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[tauri::command]
fn ping() -> String {
    "pong from rust".into()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![greet, ping])
        .setup(|app| {
            let model_dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../../ai-engine/models");
            let data_dir = concat!(env!("CARGO_MANIFEST_DIR"), "/../../ai-engine/data");
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

