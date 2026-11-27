mod engine;
mod exclusions;
mod keys;
mod permissions;
mod presence;
mod window_tracker;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, RunEvent};

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

/// Show the popup with a message in the bottom-right corner of the screen's
/// work area, which on macOS excludes the menu bar and the Dock.
pub fn present_popup(app: &AppHandle, message: &str) {
    let Some(popup) = app.get_webview_window("popup") else {
        return;
    };
    let _ = popup.emit("popup-message", message);

    let monitor = popup
        .current_monitor()
        .ok()
        .flatten()
        .or_else(|| popup.primary_monitor().ok().flatten());
    if let Some(monitor) = monitor {
        let scale = monitor.scale_factor();
        let area = monitor.work_area();
        let size = popup
            .outer_size()
            .unwrap_or(tauri::PhysicalSize::new((340.0 * scale) as u32, (100.0 * scale) as u32));
        let margin = (16.0 * scale) as i32;
        let x = area.position.x + area.size.width as i32 - size.width as i32 - margin;
        let y = area.position.y + area.size.height as i32 - size.height as i32 - margin;
        let _ = popup.set_position(tauri::PhysicalPosition::new(x, y));
    }
    let _ = popup.show();
}

#[tauri::command]
fn show_popup(app: AppHandle, message: String) {
    present_popup(&app, &message);
}

#[tauri::command]
fn hide_popup(app: AppHandle) {
    if let Some(popup) = app.get_webview_window("popup") {
        let _ = popup.hide();
    }
}

const TRAY_ID: &str = "engram-tray";

/// While a capture runs, the menu bar item says so, so capture is never silent.
pub fn set_capture_indicator(app: &AppHandle, capturing: bool) {
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        if capturing {
            let _ = tray.set_tooltip(Some("Engram is capturing a window"));
            #[cfg(target_os = "macos")]
            let _ = tray.set_title(Some("Capturing"));
        } else {
            let _ = tray.set_tooltip(Some("Engram"));
            #[cfg(target_os = "macos")]
            let _ = tray.set_title(None::<&str>);
        }
    }
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .manage(engine::EngineState::new())
        .manage(exclusions::ExclusionState::new())
        .manage(window_tracker::LastWindow::new())
        .invoke_handler(tauri::generate_handler![
            ping,
            set_capture_paused,
            get_capture_paused,
            show_popup,
            hide_popup,
            engine::engine_status,
            engine::engine_connection,
            exclusions::refresh_exclusions,
            window_tracker::capture_previous_window,
            permissions::screen_recording_status,
            permissions::request_screen_recording,
            permissions::open_privacy_settings,
        ])
        .setup(|app| {
            let paused = Arc::new(AtomicBool::new(false));
            app.manage(CaptureState { paused: paused.clone() });

            engine::start(app.handle());
            window_tracker::start_tracking(app.handle().clone(), paused);

            let show_item = MenuItem::with_id(app, "show", "Show Engram", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            TrayIconBuilder::with_id(TRAY_ID)
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Engram")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // Closing the main window hides it; Engram keeps running in the tray.
            if let Some(window) = app.get_webview_window("main") {
                let window_clone = window.clone();
                window.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let _ = window_clone.hide();
                    }
                });
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app, event| match event {
        RunEvent::Exit => {
            engine::notify_quit(app);
            engine::stop(app);
        }
        // Clicking the Dock icon brings the hidden main window back.
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => show_main_window(app),
        _ => {}
    });
}
