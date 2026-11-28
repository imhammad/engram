# 0015: The presence: menu-bar mode, a floating mark and global shortcuts

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

Through Phase 6, using Engram meant switching to its window. That breaks
the moment it is meant to help with: to ask "where did I see that?" or to
keep what is on screen, the user had to leave what they were doing. The
"Capture now" button made this worse, because capturing from inside Engram
meant capturing whatever had been in front *before* Engram. Connection
nudges appeared in a separate corner popup window that took focus and had
no history. Engram also showed a Dock icon like a document app, although it
runs all day in the background.

## Decision

**Menu-bar first.** Engram runs with the macOS Accessory activation
policy: a menu-bar item, no Dock icon, no entry in Cmd-Tab. A setting puts
the Dock icon back. The menu has Open Engram, Ask Engram..., Pause or
Resume capture (its label follows the state from anywhere), Settings...
and Quit Engram. Closing the main window hides it; Engram keeps running.

**The mark.** A 34-point floating mark (a 30-point disc with a single line
that thins and fades at one end, a memory trace) is a non-activating
`NSPanel` (via `tauri-nspanel`) at status-bar level that joins all Spaces,
stays over full-screen apps, and never appears in Cmd-Tab or Mission
Control cycling. Being non-activating, clicking it never pulls the user's
app out of focus. It can be dragged anywhere; the position is remembered
(`presence.json` in the app's config folder). It can be hidden in Settings.

Its look is a small state machine in Rust with a fixed priority:
paused (dimmed) over kept (a brief firm confirmation, 2 s) over capturing
(a slow pulse while a capture runs) over connection (a warm glow, until the
user opens the panel or 90 s pass) over idle. Animations are dropped under
Reduce Motion, where pulse becomes a static ring. The mark carries a
VoiceOver label for each state and can be operated with the keyboard.

**The ask panel.** Clicking the mark, the menu item or the ask shortcut
(Option-Space by default) opens a Spotlight-style panel: a question field,
the streamed answer from the same Recall pipeline (ADR 0012) with up to
four compact sources, and the latest connection when nothing has been
asked. Return asks; Cmd-Return saves the text as a note instead; Escape or
a click elsewhere closes it. This panel is also a non-activating `NSPanel`,
but one that can become key, so typing works without activating Engram's
other windows.

**Keep.** Option-Shift-K (by default) captures the window in front right
now and pins the result, so forgetting (ADR 0014) never removes it. If the
window was already captured and has not changed, the existing capture is
pinned instead of saving a duplicate. Exclusions and private-window
detection apply exactly as for automatic capture. The mark confirms. This
replaces "Capture now", which is removed from the Memories page.

**Shortcuts** are registered with `tauri-plugin-global-shortcut`, which
uses the Carbon hot-key API and so needs no Input Monitoring permission.
Both can be changed in Settings by pressing the new keys. Engram rejects a
shortcut without a modifier, Shift alone, the same shortcut for both, and
a list of system ones (Cmd-Space, Cmd-Tab, screenshots and so on). If the
system refuses to register a new pair, the old pair is put back.

**Connections** found after a capture now go to the mark's glow and the
panel's "Latest connection" instead of the corner popup, which is deleted.

**Launch at login** is available through `tauri-plugin-autostart` (a
LaunchAgent) and is off unless the user turns it on.

**Transparency.** The mark and panel windows are transparent, which on
macOS needs Tauri's `macos-private-api` feature. That rules out the Mac App
Store, which Engram does not target.

**The day ends at 4 AM.** The first live test, at 00:08, answered "what did
I do today?" with three minutes of activity, because the calendar day had
just begun. Engram now treats the hours before 4 AM as part of the previous
day (`timeparse.DAY_START_HOUR`): before 4 AM, "today" covers the day that
began the previous morning, "tonight" and "last night" mean the evening
still going on, "yesterday" is the day before that, the morning recap shows
that day, and consolidation leaves the evening alone until 4 AM. When
this shifts what a word means, the answer opens with one sentence saying so
("Since it's just after midnight, I'm counting all of Saturday 28 November,
up to now, as today."). The hour is a constant for now; it can become a
setting.

**Fonts.** The interface loaded IBM Plex from Google Fonts at runtime,
which broke the no-network promise for the webview (the engine was
already network-zero). The fonts are now bundled with `@fontsource`.

## Consequences

Asking and keeping work from any app in one keystroke, and Engram stays out
of the Dock and the app switcher. The mark makes background capture
visible at a glance, which matters for trust: the user can see when Engram
is reading the screen and when it is paused.

The mark sits over every app, so a badly placed mark can cover something;
it can be moved or hidden. Option-Space is used by some apps and keyboard
layouts (it types a non-breaking space in many text fields); the shortcut
can be changed. `tauri-nspanel` is a community crate pinned to 2.1 and
touches AppKit directly; a Tauri or macOS update could break the panels,
and the rest of the app does not depend on them. On other platforms the
mark and panel are not built.
