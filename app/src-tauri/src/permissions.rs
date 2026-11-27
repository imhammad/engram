//! macOS privacy permissions. Screen Recording has no Info.plist key, so the
//! app checks it directly and sends the user to System Settings to grant it.

#[cfg(target_os = "macos")]
#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGPreflightScreenCaptureAccess() -> bool;
    fn CGRequestScreenCaptureAccess() -> bool;
}

/// "granted", "denied" (not yet granted) or "unsupported" on other platforms.
#[tauri::command]
pub fn screen_recording_status() -> &'static str {
    #[cfg(target_os = "macos")]
    {
        // SAFETY: a plain CoreGraphics query with no arguments.
        if unsafe { CGPreflightScreenCaptureAccess() } {
            "granted"
        } else {
            "denied"
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        "unsupported"
    }
}

/// Ask macOS to add Engram to the Screen Recording list. The system shows its
/// prompt only the first time; afterwards the user must use System Settings.
#[tauri::command]
pub fn request_screen_recording() -> bool {
    #[cfg(target_os = "macos")]
    {
        // SAFETY: a plain CoreGraphics call with no arguments.
        unsafe { CGRequestScreenCaptureAccess() }
    }
    #[cfg(not(target_os = "macos"))]
    {
        true
    }
}

/// Open a Privacy & Security pane in System Settings. Only known panes are allowed.
#[tauri::command]
pub fn open_privacy_settings(pane: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        let anchor = match pane.as_str() {
            "screen-recording" => "Privacy_ScreenCapture",
            "microphone" => "Privacy_Microphone",
            "accessibility" => "Privacy_Accessibility",
            _ => return Err(format!("unknown privacy pane: {pane}")),
        };
        std::process::Command::new("open")
            .arg(format!("x-apple.systempreferences:com.apple.preference.security?{anchor}"))
            .spawn()
            .map(|_| ())
            .map_err(|e| format!("could not open System Settings: {e}"))
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = pane;
        Err("privacy settings are only available on macOS".into())
    }
}
