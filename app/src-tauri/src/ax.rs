//! Read the frontmost window's real text through the macOS Accessibility API.
//!
//! This is Engram's first choice for capture (ADR 0009): it returns the text
//! an app actually shows (a web page's content, an editor's document) instead
//! of pixels to be guessed at by OCR, plus the page URL for browsers. It needs
//! the Accessibility permission; without it the caller falls back to OCR.
//!
//! Rules that never change: secure text fields (passwords) are never read,
//! and the walk is bounded in nodes, characters, depth and time.

use serde::Serialize;

#[derive(Debug, Clone, Default, Serialize)]
pub struct AxText {
    pub text: String,
    pub url: String,
    /// "web", "editor" or "window": where the text came from.
    pub kind: String,
}

/// Limits on how much of an app's accessibility tree is read.
pub const MAX_NODES: usize = 6000;
pub const MAX_CHARS: usize = 20_000;
pub const MAX_DEPTH: usize = 40;
pub const TIME_BUDGET_MS: u128 = 600;

/// Password fields and anything marked secure are never read.
pub fn is_secure(role: &str, subrole: &str) -> bool {
    role == "AXSecureTextField" || subrole == "AXSecureTextField" || role.contains("Secure") || subrole.contains("Secure")
}

/// Roles whose value is page or document text worth keeping.
pub fn is_text_role(role: &str) -> bool {
    matches!(role, "AXStaticText" | "AXHeading" | "AXTextArea" | "AXCell")
}

/// Roles whose subtree is UI furniture rather than content.
pub fn is_chrome_role(role: &str) -> bool {
    matches!(role, "AXMenuBar" | "AXMenu" | "AXToolbar" | "AXTabGroup" | "AXScrollBar" | "AXPopUpButton")
}

/// Join collected fragments into lines, dropping empty and repeated ones,
/// within the character cap.
pub fn join_fragments(fragments: &[String]) -> String {
    let mut out = String::new();
    let mut last = String::new();
    for frag in fragments {
        let line = frag.split_whitespace().collect::<Vec<_>>().join(" ");
        if line.is_empty() || line == last {
            continue;
        }
        if out.len() + line.len() + 1 > MAX_CHARS {
            break;
        }
        if !out.is_empty() {
            out.push('\n');
        }
        out.push_str(&line);
        last = line;
    }
    out
}

#[cfg(target_os = "macos")]
mod mac {
    use super::*;
    use core_foundation::array::CFArray;
    use core_foundation::base::{CFType, CFTypeRef, TCFType};
    use core_foundation::boolean::CFBoolean;
    use core_foundation::dictionary::CFDictionary;
    use core_foundation::string::{CFString, CFStringRef};
    use core_foundation::url::CFURL;
    use std::collections::VecDeque;
    use std::ffi::c_void;
    use std::time::Instant;

    type AXUIElementRef = *const c_void;
    type AXError = i32;
    const AX_SUCCESS: AXError = 0;

    #[link(name = "ApplicationServices", kind = "framework")]
    extern "C" {
        fn AXIsProcessTrusted() -> bool;
        fn AXIsProcessTrustedWithOptions(options: CFTypeRef) -> bool;
        fn AXUIElementCreateApplication(pid: i32) -> AXUIElementRef;
        fn AXUIElementCopyAttributeValue(element: AXUIElementRef, attribute: CFStringRef, value: *mut CFTypeRef) -> AXError;
        fn AXUIElementSetAttributeValue(element: AXUIElementRef, attribute: CFStringRef, value: CFTypeRef) -> AXError;
        fn AXUIElementSetMessagingTimeout(element: AXUIElementRef, seconds: f32) -> AXError;
    }

    /// An AXUIElement, owned (released on drop).
    struct Element(CFType);

    impl Element {
        fn raw(&self) -> AXUIElementRef {
            self.0.as_CFTypeRef()
        }

        fn attr(&self, name: &'static str) -> Option<CFType> {
            let key = CFString::from_static_string(name);
            let mut value: CFTypeRef = std::ptr::null();
            // SAFETY: valid element and key; on success value is +1 and owned below.
            let err = unsafe { AXUIElementCopyAttributeValue(self.raw(), key.as_concrete_TypeRef(), &mut value) };
            if err != AX_SUCCESS || value.is_null() {
                return None;
            }
            Some(unsafe { CFType::wrap_under_create_rule(value) })
        }

        fn string(&self, name: &'static str) -> Option<String> {
            self.attr(name)?.downcast::<CFString>().map(|s| s.to_string())
        }

        fn url(&self, name: &'static str) -> Option<String> {
            let value = self.attr(name)?;
            if let Some(url) = value.downcast::<CFURL>() {
                return Some(url.get_string().to_string());
            }
            value.downcast::<CFString>().map(|s| s.to_string())
        }

        fn element(&self, name: &'static str) -> Option<Element> {
            self.attr(name).map(Element)
        }

        fn children(&self) -> Vec<Element> {
            let Some(value) = self.attr("AXChildren") else { return Vec::new() };
            if value.type_of() != CFArray::<CFType>::type_id() {
                return Vec::new();
            }
            // SAFETY: type checked above; get rule because `value` keeps its own reference.
            let array: CFArray<CFType> =
                unsafe { CFArray::wrap_under_get_rule(value.as_CFTypeRef() as core_foundation::array::CFArrayRef) };
            array.iter().map(|child| Element(child.clone())).collect()
        }

        fn set_bool(&self, name: &'static str, on: bool) {
            let key = CFString::from_static_string(name);
            let value = if on { CFBoolean::true_value() } else { CFBoolean::false_value() };
            // SAFETY: valid element, key and CFBoolean; failure is harmless.
            unsafe { AXUIElementSetAttributeValue(self.raw(), key.as_concrete_TypeRef(), value.as_CFTypeRef()) };
        }
    }

    pub fn trusted() -> bool {
        // SAFETY: plain query.
        unsafe { AXIsProcessTrusted() }
    }

    /// Ask macOS to show its Accessibility prompt (first time only).
    pub fn request_trust() -> bool {
        let key = CFString::from_static_string("AXTrustedCheckOptionPrompt");
        let options = CFDictionary::from_CFType_pairs(&[(key.as_CFType(), CFBoolean::true_value().as_CFType())]);
        // SAFETY: valid dictionary.
        unsafe { AXIsProcessTrustedWithOptions(options.as_CFTypeRef()) }
    }

    struct Walk {
        started: Instant,
        nodes: usize,
        chars: usize,
        fragments: Vec<String>,
    }

    impl Walk {
        fn exhausted(&self) -> bool {
            self.nodes >= MAX_NODES || self.chars >= MAX_CHARS || self.started.elapsed().as_millis() > TIME_BUDGET_MS
        }
    }

    /// Depth-first collection of visible text under `root`, skipping secure
    /// fields and UI furniture.
    fn collect(root: &Element, depth: usize, walk: &mut Walk) {
        if depth > MAX_DEPTH || walk.exhausted() {
            return;
        }
        walk.nodes += 1;
        let role = root.string("AXRole").unwrap_or_default();
        let subrole = root.string("AXSubrole").unwrap_or_default();
        if is_secure(&role, &subrole) || is_chrome_role(&role) {
            return;
        }
        if is_text_role(&role) {
            if let Some(value) = root.string("AXValue").or_else(|| root.string("AXTitle")) {
                walk.chars += value.len();
                walk.fragments.push(value);
            }
            if role == "AXStaticText" || role == "AXTextArea" {
                return; // their children repeat the same text
            }
        }
        for child in root.children() {
            collect(&child, depth + 1, walk);
            if walk.exhausted() {
                return;
            }
        }
    }

    /// Breadth-first search for the first element with one of the given roles.
    fn find_role(root: &Element, roles: &[&str], limit: usize) -> Option<Element> {
        let mut queue = VecDeque::from([Element(root.0.clone())]);
        let mut seen = 0;
        while let Some(el) = queue.pop_front() {
            seen += 1;
            if seen > limit {
                return None;
            }
            let role = el.string("AXRole").unwrap_or_default();
            if roles.contains(&role.as_str()) {
                return Some(el);
            }
            queue.extend(el.children());
        }
        None
    }

    pub fn read_front_window(pid: i32, chromium: bool) -> Option<AxText> {
        if !trusted() {
            return None;
        }
        // SAFETY: returns a +1 AXUIElement for the process (even if it has exited).
        let raw = unsafe { AXUIElementCreateApplication(pid) };
        if raw.is_null() {
            return None;
        }
        let app = Element(unsafe { CFType::wrap_under_create_rule(raw) });
        // SAFETY: valid element. Never let one slow app stall the tracker.
        unsafe { AXUIElementSetMessagingTimeout(app.raw(), 0.25) };
        // Electron apps (VS Code, Slack) and Chromium browsers only build
        // their accessibility tree when asked to.
        app.set_bool("AXManualAccessibility", true);
        if chromium {
            app.set_bool("AXEnhancedUserInterface", true);
        }

        let window = app.element("AXFocusedWindow")?;
        let mut walk = Walk { started: Instant::now(), nodes: 0, chars: 0, fragments: Vec::new() };
        let mut url = window.url("AXDocument").unwrap_or_default();

        // Browsers: the page lives in an AXWebArea; read only that.
        let kind = if let Some(web) = find_role(&window, &["AXWebArea"], 400) {
            if let Some(page) = web.url("AXURL") {
                url = page;
            }
            collect(&web, 0, &mut walk);
            "web"
        } else if let Some(focused) = app.element("AXFocusedUIElement") {
            let role = focused.string("AXRole").unwrap_or_default();
            let subrole = focused.string("AXSubrole").unwrap_or_default();
            if role == "AXTextArea" && !is_secure(&role, &subrole) {
                // An editor's document: its whole value.
                if let Some(value) = focused.string("AXValue") {
                    walk.fragments.extend(value.lines().map(str::to_string));
                }
                "editor"
            } else {
                collect(&window, 0, &mut walk);
                "window"
            }
        } else {
            collect(&window, 0, &mut walk);
            "window"
        };

        let text = join_fragments(&walk.fragments);
        Some(AxText { text, url, kind: kind.into() })
    }
}

/// True if Engram has the Accessibility permission.
pub fn trusted() -> bool {
    #[cfg(target_os = "macos")]
    return mac::trusted();
    #[cfg(not(target_os = "macos"))]
    false
}

pub fn request_trust() -> bool {
    #[cfg(target_os = "macos")]
    return mac::request_trust();
    #[cfg(not(target_os = "macos"))]
    false
}

/// Text, URL and kind of the focused window of process `pid`, or None if
/// Accessibility is not allowed or the app exposes nothing.
pub fn read_front_window(pid: u64, chromium: bool) -> Option<AxText> {
    #[cfg(target_os = "macos")]
    return mac::read_front_window(pid as i32, chromium);
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (pid, chromium);
        None
    }
}

#[tauri::command]
pub fn accessibility_status() -> &'static str {
    if cfg!(target_os = "macos") {
        if trusted() { "granted" } else { "denied" }
    } else {
        "unsupported"
    }
}

#[tauri::command]
pub fn request_accessibility() -> bool {
    request_trust()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn secure_fields_are_recognised() {
        assert!(is_secure("AXSecureTextField", ""));
        assert!(is_secure("AXTextField", "AXSecureTextField"));
        assert!(!is_secure("AXTextField", ""));
        assert!(!is_secure("AXStaticText", ""));
    }

    #[test]
    fn only_content_roles_are_collected() {
        assert!(is_text_role("AXStaticText"));
        assert!(is_text_role("AXTextArea"));
        assert!(!is_text_role("AXButton"));
        assert!(!is_text_role("AXSecureTextField"));
        assert!(is_chrome_role("AXToolbar"));
        assert!(!is_chrome_role("AXGroup"));
    }

    #[test]
    fn fragments_are_joined_deduplicated_and_capped() {
        let frags = vec!["  Hello   world ".to_string(), "Hello world".to_string(), String::new(), "Next".to_string()];
        assert_eq!(join_fragments(&frags), "Hello world\nNext");
        let long = vec!["x".repeat(MAX_CHARS - 5), "this line does not fit".to_string()];
        assert_eq!(join_fragments(&long).len(), MAX_CHARS - 5);
    }

    #[test]
    fn permission_query_answers() {
        // Just exercises the FFI on the CI Mac; the value depends on the machine.
        let _ = trusted();
    }
}
