pub mod ax;
mod engine;
mod exclusions;
mod keys;
mod overlay;
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

/// Pause or resume automatic capture, from Memories, the tray or anywhere.
pub fn set_paused(app: &AppHandle, paused: bool) {
    app.state::<CaptureState>().paused.store(paused, Ordering::Relaxed);
    overlay::update_mark(app, |m| m.paused = paused);
    if let Some(item) = app.try_state::<PauseItem>() {
        let _ = item.0.set_text(if paused { "Resume capture" } else { "Pause capture" });
    }
    let _ = app.emit("capture-paused", paused);
}

#[tauri::command]
fn set_capture_paused(app: AppHandle, paused: bool) {
    set_paused(&app, paused);
}

#[tauri::command]
fn get_capture_paused(state: tauri::State<CaptureState>) -> bool {
    state.paused.load(Ordering::Relaxed)
}

const TRAY_ID: &str = "engram-tray";

/// The tray's Pause/Resume item, so its label can follow the state.
struct PauseItem(MenuItem<tauri::Wry>);

/// While a capture runs, the menu bar item and the mark say so.
pub fn set_capture_indicator(app: &AppHandle, capturing: bool) {
    overlay::update_mark(app, |m| m.set_capturing(capturing));
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let _ = tray.set_tooltip(Some(if capturing { "Engram is capturing a window" } else { "Engram" }));
    }
}

pub fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
    #[cfg(target_os = "macos")]
    let _ = app.show();
}

fn on_shortcut(app: &AppHandle, shortcut: &tauri_plugin_global_shortcut::Shortcut) {
    let p = overlay::prefs(app);
    let matches = |s: &str| {
        s.parse::<tauri_plugin_global_shortcut::Shortcut>()
            .map(|parsed| parsed == *shortcut)
            .unwrap_or(false)
    };
    if matches(&overlay::plugin_form(&p.ask_shortcut)) {
        overlay::toggle_quick(app.clone(), overlay::Anchor::Center);
    } else if matches(&overlay::plugin_form(&p.keep_shortcut)) {
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            window_tracker::keep_front_window(&app).await;
        });
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_autostart::init(tauri_plugin_autostart::MacosLauncher::LaunchAgent, None))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if event.state() == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                        on_shortcut(app, shortcut);
                    }
                })
                .build(),
        );
    #[cfg(target_os = "macos")]
    let builder = builder.plugin(tauri_nspanel::init());
    let app = builder
        .manage(engine::EngineState::new())
        .manage(exclusions::ExclusionState::new())
        .manage(window_tracker::LastWindow::new())
        .manage(window_tracker::TimingState::new())
        .manage(overlay::MarkState::new())
        .invoke_handler(tauri::generate_handler![
            ping,
            set_capture_paused,
            get_capture_paused,
            overlay::toggle_quick,
            overlay::hide_quick,
            overlay::open_main,
            overlay::mark_look,
            overlay::latest_connection,
            overlay::get_presence_settings,
            overlay::set_presence_settings,
            engine::engine_status,
            engine::engine_connection,
            exclusions::refresh_exclusions,
            window_tracker::capture_previous_window,
            window_tracker::refresh_capture_settings,
            permissions::screen_recording_status,
            ax::accessibility_status,
            ax::request_accessibility,
            permissions::request_screen_recording,
            permissions::open_privacy_settings,
        ])
        .setup(|app| {
            let paused = Arc::new(AtomicBool::new(false));
            app.manage(CaptureState { paused: paused.clone() });

            // The presence: menu-bar mode, the mark and the quick panel (ADR 0015).
            let prefs = overlay::load_prefs(app.handle());
            app.manage(overlay::PrefsState(std::sync::Mutex::new(prefs.clone())));
            overlay::apply_dock_policy(app.handle(), prefs.show_in_dock);
            overlay::create_windows(app.handle())?;
            if let Err(err) = overlay::register_shortcuts(app.handle(), &prefs.ask_shortcut, &prefs.keep_shortcut) {
                eprintln!("[presence] {err}");
            }
            overlay::start_mark_ticker(app.handle().clone());

            engine::start(app.handle());
            window_tracker::start_tracking(app.handle().clone(), paused);

            let open_item = MenuItem::with_id(app, "open", "Open Engram", true, None::<&str>)?;
            let ask_item = MenuItem::with_id(app, "ask", "Ask Engram...", true, None::<&str>)?;
            let pause_item = MenuItem::with_id(app, "pause", "Pause capture", true, None::<&str>)?;
            let settings_item = MenuItem::with_id(app, "settings", "Settings...", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit Engram", true, None::<&str>)?;
            let separator = tauri::menu::PredefinedMenuItem::separator(app)?;
            let menu = Menu::with_items(app, &[&open_item, &ask_item, &pause_item, &separator, &settings_item, &quit_item])?;
            app.manage(PauseItem(pause_item));

            TrayIconBuilder::with_id(TRAY_ID)
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Engram")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_main_window(app),
                    "ask" => overlay::show_quick(app, overlay::Anchor::Center),
                    "pause" => {
                        let now_paused = !app.state::<CaptureState>().paused.load(Ordering::Relaxed);
                        set_paused(app, now_paused);
                    }
                    "settings" => overlay::open_main(app.clone(), Some("settings".into())),
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
