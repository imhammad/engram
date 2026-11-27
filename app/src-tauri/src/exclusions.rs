//! Windows Engram must never record. The list comes from the engine
//! (GET /exclusions: built-in apps, private-window title patterns and the
//! user's own rules) and is applied here before any activity is logged or a
//! capture is triggered. The matching mirrors match_exclusion() in
//! ai-engine/exclusions.py; keep the two in step.

use serde::Deserialize;
use std::sync::Mutex;
use tauri::{AppHandle, Manager};

use crate::engine;

#[derive(Clone, Deserialize, Default)]
pub struct Rule {
    pub kind: String,
    pub pattern: String,
}

#[derive(Clone, Deserialize, Default)]
pub struct ExclusionList {
    pub builtin_apps: Vec<String>,
    pub private_title_patterns: Vec<String>,
    pub rules: Vec<Rule>,
    /// macOS dialogs, lock screen and screen saver: ignored entirely.
    #[serde(default)]
    pub system_processes: Vec<String>,
}

impl ExclusionList {
    pub fn is_system_process(&self, app_name: &str) -> bool {
        let app = app_name.trim().to_lowercase();
        self.system_processes.iter().any(|p| p.to_lowercase() == app)
    }

    /// A short reason if the window is excluded, otherwise None.
    pub fn matches(&self, app_name: &str, title: &str) -> Option<String> {
        let app = app_name.trim().to_lowercase();
        let title = title.to_lowercase();
        if self.builtin_apps.iter().any(|a| a.to_lowercase() == app) {
            return Some(format!("built-in exclusion: {app_name}"));
        }
        if self.private_title_patterns.iter().any(|p| title.contains(&p.to_lowercase())) {
            return Some("private browsing window".into());
        }
        for rule in &self.rules {
            let pattern = rule.pattern.trim().to_lowercase();
            if pattern.is_empty() {
                continue;
            }
            match rule.kind.as_str() {
                "app" if app.contains(&pattern) => {
                    return Some(format!("your rule: app contains '{}'", rule.pattern))
                }
                "title" if title.contains(&pattern) => {
                    return Some(format!("your rule: title contains '{}'", rule.pattern))
                }
                _ => {}
            }
        }
        None
    }
}

/// Chromium browsers whose AppleScript dictionary reports a window's mode.
pub fn is_chromium(app_name: &str) -> bool {
    CHROMIUM_BROWSERS.contains(&app_name)
}

const CHROMIUM_BROWSERS: &[&str] = &[
    "Google Chrome",
    "Google Chrome Beta",
    "Google Chrome Canary",
    "Chromium",
    "Brave Browser",
    "Microsoft Edge",
    "Vivaldi",
];

/// On macOS, Chrome-family browsers do not mark incognito windows in the
/// window title, so ask the browser itself. This needs the Automation
/// permission (macOS asks once). Returns None if the app is not a Chromium
/// browser or the answer could not be had within two seconds, for example
/// because the user has not answered or has declined the permission prompt.
pub fn chromium_window_is_private(app_name: &str) -> Option<bool> {
    #[cfg(target_os = "macos")]
    {
        use std::io::Read;
        use std::process::{Command, Stdio};
        use std::time::{Duration, Instant};

        if !CHROMIUM_BROWSERS.contains(&app_name) {
            return None;
        }
        let script = format!("tell application \"{app_name}\" to get mode of front window");
        let mut child = Command::new("osascript")
            .arg("-e")
            .arg(script)
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .ok()?;
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            match child.try_wait() {
                Ok(Some(status)) => {
                    if !status.success() {
                        return None;
                    }
                    let mut out = String::new();
                    child.stdout.take()?.read_to_string(&mut out).ok()?;
                    return Some(out.trim() == "incognito");
                }
                Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
                _ => {
                    let _ = child.kill();
                    let _ = child.wait();
                    return None;
                }
            }
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app_name;
        None
    }
}

/// Until the engine has answered, everything is treated as excluded except
/// that nothing is tracked anyway (the tracker waits for the engine).
pub struct ExclusionState(pub Mutex<Option<ExclusionList>>);

impl ExclusionState {
    pub fn new() -> Self {
        Self(Mutex::new(None))
    }
}

pub fn current(app: &AppHandle) -> Option<ExclusionList> {
    app.state::<ExclusionState>().0.lock().unwrap().clone()
}

/// Fetch the latest list from the engine. Returns false if it could not.
pub async fn refresh(app: &AppHandle) -> bool {
    let Some(req) = engine::request(app, reqwest::Method::GET, "/exclusions") else {
        return false;
    };
    let Ok(resp) = req.send().await else {
        return false;
    };
    match resp.json::<ExclusionList>().await {
        Ok(list) => {
            *app.state::<ExclusionState>().0.lock().unwrap() = Some(list);
            true
        }
        Err(_) => false,
    }
}

/// Called by the Settings page after the user adds or removes a rule.
#[tauri::command]
pub async fn refresh_exclusions(app: AppHandle) -> Result<(), String> {
    if refresh(&app).await {
        Ok(())
    } else {
        Err("could not load exclusion rules from the engine".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn list() -> ExclusionList {
        ExclusionList {
            builtin_apps: vec!["Terminal".into(), "1Password".into()],
            private_title_patterns: vec!["incognito".into(), "private browsing".into()],
            rules: vec![
                Rule { kind: "title".into(), pattern: "Payroll".into() },
                Rule { kind: "app".into(), pattern: "bank".into() },
            ],
            system_processes: vec!["UserNotificationCenter".into(), "SecurityAgent".into()],
        }
    }

    #[test]
    fn builtin_apps_match_exactly_ignoring_case() {
        assert!(list().matches("terminal", "zsh").is_some());
        assert!(list().matches("Terminal Notes", "x").is_none());
    }

    #[test]
    fn private_windows_match_by_title() {
        assert!(list().matches("Google Chrome", "Bank - Google Chrome (Incognito)").is_some());
        assert!(list().matches("Firefox", "Mozilla Firefox Private Browsing").is_some());
        assert!(list().matches("Google Chrome", "GitHub - Google Chrome").is_none());
    }

    #[test]
    fn system_dialog_processes_are_recognised() {
        assert!(list().is_system_process("UserNotificationCenter"));
        assert!(list().is_system_process("securityagent"));
        assert!(!list().is_system_process("Google Chrome"));
    }

    #[test]
    fn user_rules_match_substrings() {
        assert!(list().matches("Numbers", "Payroll 2026").is_some());
        assert!(list().matches("Maybank2u", "Home").is_some());
        assert!(list().matches("Notes", "Shopping").is_none());
    }
}
