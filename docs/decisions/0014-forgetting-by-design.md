# 0014: Forgetting by design

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

A recorder that keeps everything grows without limit. It holds more private
material every day, and gets noisier to search. ADR 0002 chose a different
model: raw traces fade unless they are recalled or pinned, while episodes and
day summaries last. Until consolidation existed (ADR 0013), fading would have
meant losing the past outright, so it could not be built.

Forgetting is also the most consequential thing Engram does to the user's
data without being asked each time. It must never surprise anyone.

## Decision

**Off until the user chooses.** The setting starts at Never. The choices are
Never, Gentle (30 days), Balanced (14 days) and Brisk (7 days). Turning
forgetting on, or making it stricter, requires confirming a preview first.
The Settings page shows how many raw captures would fade now, and how many
would be spared because they are kept or were recently recalled. The engine
enforces this too: the request is refused without `confirm` and returns the
preview instead.

**What fades.** A raw capture fades when all of these hold:
- it is older than the chosen number of days;
- it is not pinned (the Keep action on a memory or a Recall source);
- it has not been used in a Recall answer within that many days (being cited
  refreshes it);
- its day has already been consolidated into an episode.

The last rule means nothing can disappear before it has been summarised.
Typed notes follow the same rules as captures.

**What stays.** Episodes, day summaries, their stats, and the
`episode_sources` snapshot of what each episode drew on. When a source
fades, its snapshot row is marked faded, so an episode keeps its summary and
can show that its sources are gone. Activity sessions, the Ledger and Recall
history are not affected.

**How it runs.** After each consolidation run, whether at startup, while idle
on power, or on demand. Faded captures are deleted from the database, from
the FTS5 index (by the existing triggers) and from the vector table. One
Ledger entry records how many faded and why. After 200 deletions, or a week,
the database is vacuumed so the space is actually released.

## Consequences

Retained raw data is bounded by the chosen window, which makes Engram's
privacy promise stronger over time instead of weaker. The index stays small,
and the past remains searchable through episodes and day summaries.

The costs are real and deliberate. Once a capture fades, its exact text is
gone. Recall can still say what the episode was about, but not quote the
page. Pinning and recall-refresh keep what matters, but only if the user
pins it or happens to recall it in time. That is why the default is Never,
and why the preview comes before anything is removed.
