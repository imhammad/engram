"""Which windows Engram must never record.

The built-in list covers apps whose windows routinely show secrets or
system controls, and private browsing windows. Users add their own rules
(app name contains, or window title contains) in Settings.

The desktop shell fetches this list from GET /exclusions and applies it
before it logs activity or triggers a capture. The engine applies the same
rules again on /activity and /capture as a second line of defence. The Rust
matcher in app/src-tauri/src/exclusions.rs mirrors match_exclusion() below;
keep the two in step.
"""

# Matched against the app name, case-insensitively and exactly.
BUILTIN_APPS = [
    "Engram",
    "Terminal",
    "iTerm2",
    "Warp",
    "1Password",
    "1Password 7",
    "Bitwarden",
    "Keychain Access",
    "System Settings",
    "System Preferences",
]

# Matched against the window title, case-insensitively, as substrings.
# Firefox marks private windows with "Private Browsing" and some browsers on
# other platforms add "Incognito" or "InPrivate". On macOS, Chrome-family
# browsers put no marker in the title at all (verified: an incognito window
# and a normal window showing the same page have identical window info), so
# the shell asks those browsers for the window mode over AppleScript instead
# (exclusions.rs, chromium_window_is_private). Safari exposes neither, so
# Safari private windows cannot be detected.
PRIVATE_TITLE_PATTERNS = [
    "incognito",
    "private browsing",
    "private window",
    "inprivate",
]

EXCLUDED_TITLE_MARKER = "[excluded]"


def match_exclusion(app_name: str, window_title: str, user_rules: list[dict]) -> str | None:
    """Return a short reason if the window is excluded, otherwise None."""
    app = (app_name or "").strip().lower()
    title = (window_title or "").lower()

    if app in {a.lower() for a in BUILTIN_APPS}:
        return f"built-in exclusion: {app_name}"
    for pattern in PRIVATE_TITLE_PATTERNS:
        if pattern in title:
            return "private browsing window"
    for rule in user_rules:
        pattern = (rule.get("pattern") or "").strip().lower()
        if not pattern:
            continue
        if rule.get("kind") == "app" and pattern in app:
            return f"your rule: app contains '{rule['pattern']}'"
        if rule.get("kind") == "title" and pattern in title:
            return f"your rule: title contains '{rule['pattern']}'"
    return None
