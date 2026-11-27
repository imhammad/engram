# 0010: Change-aware recapture, and no LLM rewriting of captures

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

The owner's principle for capture is that it must be automatic: nobody should
have to press a button to remember something. Until Phase 4 Engram captured a
window once, 30 seconds after it came to the front, and never again while the
user stayed there. An hour spent reading one long page or editing one
document left a single memory of the first screen.

Captured text also needs tidying. An earlier experiment on the
wip/capture-cleanup branch asked the bundled TinyLlama model to strip UI
clutter from captures.

## Decision

**Look again, keep only what changed.** While the user stays on one window,
the tracker looks again on an interval (default every 2 minutes). The engine
compares the new text with the last capture from the same window, identified
by app plus URL, or app plus title when there is no URL. It uses Jaccard
similarity of word 3-gram shingles:

- below 0.7 the content has meaningfully changed (scrolling to a new section,
  a different document) and it is stored with trigger `changed`;
- at 0.7 or above it is unchanged and nothing is stored. Unchanged checks are
  not written to the Ledger, which would otherwise fill up every few minutes;
- at 0.9 or above, any capture (automatic or manual) is a near-duplicate and
  is never stored; the Ledger records it as "Already saved".

On realistic page lengths a clock, a badge count or a cursor change leaves
similarity above 0.9, while scrolling half a screen drops it well below 0.7.
Tests cover both. Captures record their trigger: `dwell` (first capture after
the dwell delay), `changed` or `manual`.

**Settings, applied live.** The dwell delay (15, 30 or 60 seconds) and the
recapture interval (off, 1, 2 or 5 minutes) are stored in the settings table.
The tracker re-reads them every 30 seconds and immediately when they change
in Settings.

**Popups only for connections.** With recapture, a popup for every save would
be constant noise, so the popup now appears only when a capture connects to
an earlier memory. Captures stay visible in the menu bar ("Capturing") and on
the Ledger.

**Capture now is secondary.** The old Capture Screen button is now a small
"Capture now" link. Automatic capture is the main path.

**System dialogs are ignored.** Notification and permission prompts
(UserNotificationCenter, SecurityAgent, coreautha), the login window and
screen saver, the Dock and similar system processes are neither timed nor
captured. On the owner's Mac a permission prompt had been counted as 24
minutes of "work".

**Deterministic clean-up, no LLM rewriting.** `cleanup.py` normalises
whitespace, keeps repeated lines once, drops common navigation and cookie
banner lines, drops lone counters, and drops lines that keep appearing in
the same app's captures of other windows (site headers, sidebars). It never
rewrites text.

We tested the LLM approach before deciding. `scripts/evaluate_llm_cleanup.py`
ran the stricter prompt from the wip branch through TinyLlama (temperature
0.1) on four sample captures. It measured the share of output words that do
not appear in the input:

| sample | invented words | what happened |
|---|---|---|
| profile page | 50% | turned a profile into a biography with a made-up "Toronto-based startup" |
| article | 12% | kept the navigation clutter and broke words ("Sei-zu-re") |
| code | 12% | kept the editor's menu bar |
| noise | 0% | passed the noise through unchanged instead of rejecting it |

A memory that invents facts is worse than a noisy one, because the user can
no longer trust what they recall. LLM rewriting of captures is therefore not
shipped. This could be revisited with a much stronger local model and a
check that rejects output containing words the source does not.

## Consequences

Long sessions in one window are remembered as they progress, without
duplicates, and the user never needs to capture by hand. Memories contain
only text that was on screen.

The costs: recapture runs a capture every interval while the user stays on a
window. With Accessibility this is cheap. With the OCR fallback it is one
Vision pass (about 100 ms). The similarity thresholds are heuristics and may
need tuning with more use. Rule-based clean-up leaves some interface text
behind that a perfect cleaner would remove.
