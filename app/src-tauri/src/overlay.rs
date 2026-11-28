//! The presence (ADR 0015): Engram lives in the menu bar, shows a small
//! floating mark, and answers from a compact panel that opens next to the
//! mark or anywhere with a global shortcut. Nothing here steals focus from
//! the app the user is working in.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager};

pub const MARK_LABEL: &str = "mark";
pub const QUICK_LABEL: &str = "quick";
const MARK_SIZE: f64 = 34.0;
const QUICK_WIDTH: f64 = 560.0;
const QUICK_HEIGHT: f64 = 440.0;

// --- preferences ---------------------------------------------------------------

/// Presence settings, kept in the app's config folder (they must be known
/// before the engine is running, so they don't live in the database).
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct PresencePrefs {
    pub show_in_dock: bool,
    pub mark_visible: bool,
    /// Logical top-left position of the mark on screen.
    pub mark_position: Option<(f64, f64)>,
    pub ask_shortcut: String,
    pub keep_shortcut: String,
}

impl Default for PresencePrefs {
    fn default() -> Self {
        Self {
            show_in_dock: false,
            mark_visible: true,
            mark_position: None,
            ask_shortcut: "Alt+Space".into(),
            keep_shortcut: "Alt+Shift+K".into(),
        }
    }
}

pub struct PrefsState(pub Mutex<PresencePrefs>);

fn prefs_path(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|d| d.join("presence.json"))
}

pub fn load_prefs(app: &AppHandle) -> PresencePrefs {
    prefs_path(app)
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn save_prefs(app: &AppHandle, prefs: &PresencePrefs) {
    if let Some(path) = prefs_path(app) {
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        let _ = std::fs::write(path, serde_json::to_string_pretty(prefs).unwrap_or_default());
    }
}

pub fn prefs(app: &AppHandle) -> PresencePrefs {
    app.state::<PrefsState>().0.lock().unwrap().clone()
}

// --- the mark's state ------------------------------------------------------------

/// What the mark shows. Priority: paused, then kept, capturing, connection, idle.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum MarkLook {
    Idle,
    Capturing,
    Connection,
    Kept,
    Paused,
}

#[derive(Default)]
pub struct MarkMachine {
    pub paused: bool,
    capturing: bool,
    kept_until: Option<Instant>,
    connection_until: Option<Instant>,
}

pub const KEPT_FOR: Duration = Duration::from_secs(2);
pub const CONNECTION_FOR: Duration = Duration::from_secs(90);

impl MarkMachine {
    pub fn look(&self, now: Instant) -> MarkLook {
        if self.paused {
            MarkLook::Paused
        } else if self.kept_until.is_some_and(|t| now < t) {
            MarkLook::Kept
        } else if self.capturing {
            MarkLook::Capturing
        } else if self.connection_until.is_some_and(|t| now < t) {
            MarkLook::Connection
        } else {
            MarkLook::Idle
        }
    }
    pub fn set_capturing(&mut self, on: bool) {
        self.capturing = on;
    }
    pub fn kept(&mut self, now: Instant) {
        self.kept_until = Some(now + KEPT_FOR);
    }
    pub fn connection(&mut self, now: Instant) {
        self.connection_until = Some(now + CONNECTION_FOR);
    }
    /// Opening the panel acknowledges a connection; the glow stops.
    pub fn acknowledge(&mut self) {
        self.connection_until = None;
    }
}

pub struct MarkState {
    pub machine: Mutex<MarkMachine>,
    last_sent: Mutex<Option<MarkLook>>,
    /// The latest "this connects to" message, shown in the panel.
    pub connection: Mutex<Option<String>>,
}

impl MarkState {
    pub fn new() -> Self {
        Self { machine: Mutex::new(MarkMachine::default()), last_sent: Mutex::new(None), connection: Mutex::new(None) }
    }
}

/// Recompute the mark's look and tell the mark window if it changed.
pub fn refresh_mark(app: &AppHandle) {
    let state = app.state::<MarkState>();
    let look = state.machine.lock().unwrap().look(Instant::now());
    let mut last = state.last_sent.lock().unwrap();
    if *last != Some(look) {
        *last = Some(look);
        let _ = app.emit_to(MARK_LABEL, "mark-look", look);
    }
}

pub fn update_mark(app: &AppHandle, f: impl FnOnce(&mut MarkMachine)) {
    f(&mut app.state::<MarkState>().machine.lock().unwrap());
    refresh_mark(app);
}

/// A capture connected to an older memory: the mark glows and the panel
/// shows the message (this replaces the old corner popup).
pub fn connection_found(app: &AppHandle, message: String) {
    *app.state::<MarkState>().connection.lock().unwrap() = Some(message.clone());
    let _ = app.emit_to(QUICK_LABEL, "connection", message);
    update_mark(app, |m| m.connection(Instant::now()));
}

/// Timed looks (kept, connection) end on their own; tick to notice.
pub fn start_mark_ticker(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_millis(500)).await;
            refresh_mark(&app);
        }
    });
}

#[tauri::command]
pub fn mark_look(state: tauri::State<MarkState>) -> MarkLook {
    state.machine.lock().unwrap().look(Instant::now())
}

#[tauri::command]
pub fn latest_connection(state: tauri::State<MarkState>) -> Option<String> {
    state.connection.lock().unwrap().clone()
}

// --- shortcuts -------------------------------------------------------------------

/// Shortcuts macOS or common apps already own; registering them would
/// either fail or break something the user relies on.
const RESERVED: &[&str] = &[
    "Cmd+Space", "Cmd+Tab", "Cmd+Q", "Cmd+W", "Cmd+C", "Cmd+V", "Cmd+X", "Cmd+Z", "Cmd+A", "Cmd+S",
    "Cmd+Shift+3", "Cmd+Shift+4", "Cmd+Shift+5", "Ctrl+Space", "Cmd+Alt+Esc",
];

/// Normalise a shortcut string ("option+space" -> "Alt+Space") and check it
/// has at least one modifier and a key.
pub fn normalise_shortcut(raw: &str) -> Result<String, String> {
    let mut mods: Vec<&str> = Vec::new();
    let mut key: Option<String> = None;
    for part in raw.split('+').map(str::trim).filter(|p| !p.is_empty()) {
        match part.to_lowercase().as_str() {
            "cmd" | "command" | "super" | "meta" => mods.push("Cmd"),
            "ctrl" | "control" => mods.push("Ctrl"),
            "alt" | "option" | "opt" => mods.push("Alt"),
            "shift" => mods.push("Shift"),
            other => {
                if key.is_some() {
                    return Err(format!("\"{raw}\" has more than one key"));
                }
                let k = match other {
                    "space" => "Space".to_string(),
                    "return" | "enter" => "Enter".to_string(),
                    k if k.len() == 1 && k.chars().all(|c| c.is_ascii_alphanumeric()) => k.to_uppercase(),
                    k if k.starts_with('f') && k[1..].parse::<u8>().is_ok_and(|n| (1..=20).contains(&n)) => k.to_uppercase(),
                    _ => return Err(format!("\"{part}\" is not a key Engram can use")),
                };
                key = Some(k);
            }
        }
    }
    let key = key.ok_or_else(|| format!("\"{raw}\" has no key"))?;
    if mods.is_empty() {
        return Err("a shortcut needs at least one of Cmd, Ctrl, Option or Shift".into());
    }
    let order = ["Cmd", "Ctrl", "Alt", "Shift"];
    let mut sorted: Vec<&str> = order.iter().copied().filter(|m| mods.contains(m)).collect();
    if sorted.len() == 1 && sorted[0] == "Shift" {
        return Err("Shift alone would block typing; add Cmd, Ctrl or Option".into());
    }
    sorted.dedup();
    Ok(format!("{}+{}", sorted.join("+"), key))
}

pub fn check_shortcuts(ask: &str, keep: &str) -> Result<(String, String), String> {
    let ask = normalise_shortcut(ask)?;
    let keep = normalise_shortcut(keep)?;
    if ask == keep {
        return Err("the Ask and Keep shortcuts must be different".into());
    }
    for s in [&ask, &keep] {
        if RESERVED.iter().any(|r| r.eq_ignore_ascii_case(s)) {
            return Err(format!("{s} is used by macOS or by most apps"));
        }
    }
    Ok((ask, keep))
}

/// The plugin's parser spells Option as "Alt" and the Cmd key as "Super".
pub fn plugin_form(shortcut: &str) -> String {
    shortcut.replace("Cmd", "Super")
}

pub fn register_shortcuts(app: &AppHandle, ask: &str, keep: &str) -> Result<(), String> {
    use tauri_plugin_global_shortcut::GlobalShortcutExt;
    let gs = app.global_shortcut();
    let _ = gs.unregister_all();
    gs.register(plugin_form(ask).as_str())
        .map_err(|e| format!("{ask} could not be registered (another app may own it): {e}"))?;
    gs.register(plugin_form(keep).as_str())
        .map_err(|e| format!("{keep} could not be registered (another app may own it): {e}"))?;
    Ok(())
}

// --- panels ------------------------------------------------------------------------

#[cfg(target_os = "macos")]
mod mark_panel {
    tauri_nspanel::tauri_panel! {
        panel!(MarkPanel {
            config: {
                can_become_key_window: false,
                is_floating_panel: true
            }
        })
    }
}

#[cfg(target_os = "macos")]
mod quick_panel {
    tauri_nspanel::tauri_panel! {
        panel!(QuickPanel {
            config: {
                can_become_key_window: true,
                is_floating_panel: true
            }
        })
    }
}

fn default_mark_position(app: &AppHandle) -> (f64, f64) {
    if let Ok(Some(m)) = app.primary_monitor() {
        let scale = m.scale_factor();
        let area = m.work_area();
        let x = (area.position.x as f64 + area.size.width as f64) / scale - MARK_SIZE - 24.0;
        let y = (area.position.y as f64 + area.size.height as f64) / scale - MARK_SIZE - 120.0;
        return (x, y);
    }
    (1200.0, 700.0)
}

/// Create the mark and the quick panel (hidden). macOS uses non-activating
/// panels on every Space and over full-screen apps.
pub fn create_windows(app: &AppHandle) -> tauri::Result<()> {
    let p = prefs(app);
    let (mx, my) = p.mark_position.unwrap_or_else(|| default_mark_position(app));

    #[cfg(target_os = "macos")]
    {
        use tauri::{LogicalPosition, LogicalSize, Position, Size, WebviewUrl};
        use tauri_nspanel::{CollectionBehavior, PanelBuilder, PanelLevel, StyleMask};

        let everywhere = CollectionBehavior::new()
            .can_join_all_spaces()
            .stationary()
            .full_screen_auxiliary()
            .ignores_cycle();

        let mark = PanelBuilder::<_, mark_panel::MarkPanel>::new(app, MARK_LABEL)
            .url(WebviewUrl::App("mark.html".into()))
            .title("Engram")
            .with_window(|w| w.decorations(false).transparent(true).skip_taskbar(true))
            .size(Size::Logical(LogicalSize::new(MARK_SIZE, MARK_SIZE)))
            .position(Position::Logical(LogicalPosition::new(mx, my)))
            .level(PanelLevel::Status)
            .add_style_mask(StyleMask::empty().nonactivating_panel())
            .collection_behavior(everywhere)
            .no_activate(true)
            .hides_on_deactivate(false)
            .has_shadow(false)
            .opaque(false)
            .transparent(true)
            .build()?;
        if p.mark_visible {
            mark.show();
        }

        let quick = PanelBuilder::<_, quick_panel::QuickPanel>::new(app, QUICK_LABEL)
            .url(WebviewUrl::App("quick.html".into()))
            .title("Ask Engram")
            .with_window(|w| w.decorations(false).transparent(true).skip_taskbar(true))
            .size(Size::Logical(LogicalSize::new(QUICK_WIDTH, QUICK_HEIGHT)))
            .level(PanelLevel::Status)
            .add_style_mask(StyleMask::empty().nonactivating_panel())
            .collection_behavior(CollectionBehavior::new().can_join_all_spaces().full_screen_auxiliary().ignores_cycle())
            .no_activate(true)
            .hides_on_deactivate(false)
            .has_shadow(true)
            .corner_radius(14.0)
            .transparent(true)
            .build()?;
        quick.hide();
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (mx, my);
    }

    // Remember where the user drags the mark.
    if let Some(window) = app.get_webview_window(MARK_LABEL) {
        let handle = app.clone();
        window.on_window_event(move |event| {
            if let tauri::WindowEvent::Moved(pos) = event {
                if let Some(w) = handle.get_webview_window(MARK_LABEL) {
                    let scale = w.scale_factor().unwrap_or(1.0);
                    let logical = (pos.x as f64 / scale, pos.y as f64 / scale);
                    let state = handle.state::<PrefsState>();
                    let mut p = state.0.lock().unwrap();
                    p.mark_position = Some(logical);
                    save_prefs(&handle, &p);
                }
            }
        });
    }
    Ok(())
}

pub fn set_mark_visible(app: &AppHandle, visible: bool) {
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::ManagerExt;
        if let Ok(panel) = app.get_webview_panel(MARK_LABEL) {
            if visible { panel.show() } else { panel.hide() }
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (app, visible);
    }
}

/// Where the quick panel opens.
#[derive(Clone, Copy, Deserialize, Debug, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum Anchor {
    /// Next to the mark.
    Mark,
    /// Centred near the top of the screen, like Spotlight.
    Center,
}

/// Position for the panel: beside the mark (above it if there's room,
/// otherwise below), kept on screen; or centred in the upper third.
pub fn panel_position(anchor: Anchor, mark: (f64, f64), screen: (f64, f64, f64, f64)) -> (f64, f64) {
    let (sx, sy, sw, sh) = screen;
    let (x, y) = match anchor {
        Anchor::Center => (sx + (sw - QUICK_WIDTH) / 2.0, sy + sh * 0.18),
        Anchor::Mark => {
            let x = mark.0 + MARK_SIZE - QUICK_WIDTH;
            let above = mark.1 - QUICK_HEIGHT - 10.0;
            let y = if above >= sy { above } else { mark.1 + MARK_SIZE + 10.0 };
            (x, y)
        }
    };
    (x.clamp(sx + 8.0, sx + sw - QUICK_WIDTH - 8.0), y.clamp(sy + 8.0, sy + sh - QUICK_HEIGHT - 8.0))
}

pub fn show_quick(app: &AppHandle, anchor: Anchor) {
    let mark_pos = prefs(app).mark_position.unwrap_or_else(|| default_mark_position(app));
    let screen = app
        .primary_monitor()
        .ok()
        .flatten()
        .map(|m| {
            let s = m.scale_factor();
            let a = m.work_area();
            (a.position.x as f64 / s, a.position.y as f64 / s, a.size.width as f64 / s, a.size.height as f64 / s)
        })
        .unwrap_or((0.0, 0.0, 1440.0, 900.0));
    let (x, y) = panel_position(anchor, mark_pos, screen);
    if let Some(w) = app.get_webview_window(QUICK_LABEL) {
        let _ = w.set_position(tauri::Position::Logical(tauri::LogicalPosition::new(x, y)));
    }
    update_mark(app, |m| m.acknowledge());
    let _ = app.emit_to(QUICK_LABEL, "quick-open", ());
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::ManagerExt;
        if let Ok(panel) = app.get_webview_panel(QUICK_LABEL) {
            panel.show_and_make_key();
        }
    }
}

pub fn hide_quick_panel(app: &AppHandle) {
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::ManagerExt;
        if let Ok(panel) = app.get_webview_panel(QUICK_LABEL) {
            panel.hide();
        }
    }
    #[cfg(not(target_os = "macos"))]
    let _ = app;
}

pub fn quick_visible(app: &AppHandle) -> bool {
    #[cfg(target_os = "macos")]
    {
        use tauri_nspanel::ManagerExt;
        return app.get_webview_panel(QUICK_LABEL).map(|p| p.is_visible()).unwrap_or(false);
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        false
    }
}

#[tauri::command]
pub fn toggle_quick(app: AppHandle, anchor: Anchor) {
    if quick_visible(&app) {
        hide_quick_panel(&app);
    } else {
        show_quick(&app, anchor);
    }
}

#[tauri::command]
pub fn hide_quick(app: AppHandle) {
    hide_quick_panel(&app);
}

/// Open the full Engram window, optionally on a page (from the panel or tray).
#[tauri::command]
pub fn open_main(app: AppHandle, page: Option<String>) {
    hide_quick_panel(&app);
    crate::show_main_window(&app);
    if let Some(page) = page {
        let _ = app.emit_to("main", "navigate", page);
    }
}

// --- settings commands --------------------------------------------------------------

#[derive(Serialize)]
pub struct PresenceSettings {
    #[serde(flatten)]
    prefs: PresencePrefs,
    launch_at_login: bool,
}

#[tauri::command]
pub fn get_presence_settings(app: AppHandle) -> PresenceSettings {
    use tauri_plugin_autostart::ManagerExt as _;
    PresenceSettings { prefs: prefs(&app), launch_at_login: app.autolaunch().is_enabled().unwrap_or(false) }
}

#[derive(Deserialize)]
pub struct PresenceUpdate {
    show_in_dock: Option<bool>,
    mark_visible: Option<bool>,
    ask_shortcut: Option<String>,
    keep_shortcut: Option<String>,
    launch_at_login: Option<bool>,
}

#[tauri::command]
pub fn set_presence_settings(app: AppHandle, update: PresenceUpdate) -> Result<PresenceSettings, String> {
    let mut p = prefs(&app);
    if update.ask_shortcut.is_some() || update.keep_shortcut.is_some() {
        let ask = update.ask_shortcut.clone().unwrap_or(p.ask_shortcut.clone());
        let keep = update.keep_shortcut.clone().unwrap_or(p.keep_shortcut.clone());
        let (ask, keep) = check_shortcuts(&ask, &keep)?;
        if let Err(e) = register_shortcuts(&app, &ask, &keep) {
            let _ = register_shortcuts(&app, &p.ask_shortcut, &p.keep_shortcut); // put the old ones back
            return Err(e);
        }
        p.ask_shortcut = ask;
        p.keep_shortcut = keep;
    }
    if let Some(v) = update.mark_visible {
        p.mark_visible = v;
        set_mark_visible(&app, v);
    }
    if let Some(v) = update.show_in_dock {
        p.show_in_dock = v;
        apply_dock_policy(&app, v);
    }
    if let Some(v) = update.launch_at_login {
        use tauri_plugin_autostart::ManagerExt as _;
        let auto = app.autolaunch();
        let result = if v { auto.enable() } else { auto.disable() };
        result.map_err(|e| format!("could not change launch at login: {e}"))?;
    }
    *app.state::<PrefsState>().0.lock().unwrap() = p.clone();
    save_prefs(&app, &p);
    Ok(get_presence_settings(app))
}

/// Menu-bar mode: no Dock icon unless the user asks for one.
pub fn apply_dock_policy(app: &AppHandle, show_in_dock: bool) {
    #[cfg(target_os = "macos")]
    {
        let policy = if show_in_dock { tauri::ActivationPolicy::Regular } else { tauri::ActivationPolicy::Accessory };
        let _ = app.set_activation_policy(policy);
    }
    #[cfg(not(target_os = "macos"))]
    let _ = (app, show_in_dock);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mark_priorities() {
        let now = Instant::now();
        let mut m = MarkMachine::default();
        assert_eq!(m.look(now), MarkLook::Idle);
        m.connection(now);
        assert_eq!(m.look(now), MarkLook::Connection);
        m.set_capturing(true);
        assert_eq!(m.look(now), MarkLook::Capturing);
        m.kept(now);
        assert_eq!(m.look(now), MarkLook::Kept);
        m.paused = true;
        assert_eq!(m.look(now), MarkLook::Paused);
    }

    #[test]
    fn timed_looks_expire_and_acknowledge_clears_the_glow() {
        let now = Instant::now();
        let mut m = MarkMachine::default();
        m.kept(now);
        assert_eq!(m.look(now + KEPT_FOR + Duration::from_millis(1)), MarkLook::Idle);
        m.connection(now);
        assert_eq!(m.look(now + Duration::from_secs(10)), MarkLook::Connection);
        assert_eq!(m.look(now + CONNECTION_FOR + Duration::from_millis(1)), MarkLook::Idle);
        m.connection(now);
        m.acknowledge();
        assert_eq!(m.look(now + KEPT_FOR + Duration::from_millis(1)), MarkLook::Idle);
    }

    #[test]
    fn shortcuts_are_normalised() {
        assert_eq!(normalise_shortcut("option+space").unwrap(), "Alt+Space");
        assert_eq!(normalise_shortcut("Shift + Alt + k").unwrap(), "Alt+Shift+K");
        assert_eq!(normalise_shortcut("cmd+shift+f5").unwrap(), "Cmd+Shift+F5");
        assert!(normalise_shortcut("space").is_err());          // no modifier
        assert!(normalise_shortcut("shift+a").is_err());        // shift alone
        assert!(normalise_shortcut("alt+a+b").is_err());        // two keys
        assert!(normalise_shortcut("alt+").is_err());           // no key
        assert!(normalise_shortcut("alt+tab").is_err());        // unsupported key
    }

    #[test]
    fn shortcut_conflicts_are_caught() {
        assert!(check_shortcuts("Alt+Space", "Alt+Shift+K").is_ok());
        assert!(check_shortcuts("Alt+Space", "option+space").is_err()); // same
        assert!(check_shortcuts("Cmd+Space", "Alt+Shift+K").is_err());  // Spotlight
        assert_eq!(plugin_form("Cmd+Shift+E"), "Super+Shift+E");
    }

    #[test]
    fn prefs_round_trip_and_tolerate_missing_fields() {
        let p = PresencePrefs { mark_position: Some((100.0, 200.0)), ..Default::default() };
        let back: PresencePrefs = serde_json::from_str(&serde_json::to_string(&p).unwrap()).unwrap();
        assert_eq!(back, p);
        let partial: PresencePrefs = serde_json::from_str(r#"{"mark_visible": false}"#).unwrap();
        assert!(!partial.mark_visible && partial.ask_shortcut == "Alt+Space");
    }

    #[test]
    fn panel_stays_on_screen() {
        let screen = (0.0, 25.0, 1440.0, 875.0);
        let (x, y) = panel_position(Anchor::Mark, (1380.0, 760.0), screen);
        assert!(x >= 8.0 && x + QUICK_WIDTH <= 1440.0 - 8.0 + 1e-9);
        assert!(y + QUICK_HEIGHT <= 760.0);                    // above the mark
        let (_, y_low) = panel_position(Anchor::Mark, (1380.0, 40.0), screen);
        assert!(y_low > 40.0);                                  // below when no room above
        let (cx, cy) = panel_position(Anchor::Center, (0.0, 0.0), screen);
        assert!((cx - (1440.0 - QUICK_WIDTH) / 2.0).abs() < 1e-9 && cy < 300.0);
    }
}
