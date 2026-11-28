# 0013: Consolidation into episodes and day summaries

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

ADR 0002 modelled Engram on human memory: raw captures are short-lived
traces, and a consolidation step turns them into episodes and day summaries
that last. Phase 3 created empty `episodes` and `days` tables for this.
Without consolidation, Recall has to dig through hundreds of raw captures to
answer "what did I do on Thursday?", and nothing could ever be allowed to
fade, because it is the only record.

## Decision

**Episodes from time and topic.** For each finished local day, code groups
the day's activity sessions and captures (`consolidation.build_episodes`):

- a pause longer than 20 minutes starts a new episode;
- so does an episode longer than three hours;
- so does a change of topic: a session of ten minutes or more, in an app not
  already part of the episode, whose window titles and captured text share
  less than 8 percent of their words with the episode so far. Short detours,
  like a few minutes in a browser while coding, stay in the episode;
- captures join the episode they fall in, or the nearest one within ten
  minutes;
- episodes under three minutes with no captures are dropped as noise, and
  system dialogs never form episodes.

**Summaries that cite.** For each episode, the local model (ADR 0011) gets up
to six of its captures as numbered sources, one per page using the fullest
capture, 600 characters each. It writes a title of at most eight words and a
one-to-three sentence summary whose sentences cite the sources. The Recall
citation check (ADR 0012) runs on the summary. If the model's title is
missing or rambles, the title falls back to the main app and window. Episodes
with activity but no captures get a plain "Time in ..." line from code. The
day summary is written the same way from the episodes, citing them.

Times, durations and app totals are always computed by code and stored as
the day's stats (focused time, top apps), never written by the model.

**Storage.** Episodes go in `episodes` with their apps and focused time;
`episode_sources` keeps a snapshot of each cited source (trace id, app,
title, URL, time). That snapshot outlives the trace when it fades, so an
episode can still say what it was built from. Episode text is embedded in
`episode_vectors` for search. Re-running a day replaces its episodes and
summary in one transaction, so consolidation is idempotent.

**When it runs.** At engine start, for any finished day that has activity or
captures but no summary (up to 14 days back). When the user has been idle for
five minutes and the Mac is on mains power, at most once an hour (the shell
asks the engine). And on demand from Settings. Today is never consolidated,
because it isn't finished.

**What Recall does with it.** "What did I do on Thursday?" (a whole past day
that has been consolidated) is answered from the day summary, with the
episodes as sources, without running the model again. Content questions get
matching episodes ahead of raw captures as sources.

**Open loops.** During consolidation, sentences in the user's own notes,
messages and code that look like commitments ("TODO", "remind me to", "I
need to", "please reply by Monday") are found by rules. The model only
answers yes or no to "is this a task the user still has to do?" and never
rewrites the sentence. Text in web browsers is skipped, because commitments
in an article are the author's, not the user's. Open loops appear in the
morning recap with Done and Dismiss.

**The morning recap.** On the first visit of the day, the Recall page shows
yesterday: the day summary, focused time, top apps, the episodes with their
times, and open loops. It can be dismissed until the next day.

**Measured.** On the evaluation fixture, consolidating two finished days
into 12 episodes took 21 seconds with Qwen3-4B. Of four new questions
answered from consolidated memory, three were correct. The miss was a cited
but vague answer about code written on Friday. On the owner's real 27
November, consolidation produced three episodes (reviewing the Engram
interface, the GitHub profile page, finishing the Phase 0 pull request) and
a day summary that matched them. It also surfaced one false open loop (a
"to-do app" phrase in a profile bio), which led to skipping captures from
unknown apps and dropping the bare "to-do" pattern.

## Consequences

Recall answers questions about whole days quickly and coherently, and memory
can now be allowed to fade (ADR 0014) without losing the shape of the past.
Consolidating a day takes a few seconds per episode on the local model, so
it runs in the background, preferably while the Mac is idle and plugged in.

The grouping thresholds are heuristics. A day of rapid context switching can
produce many small episodes, and a long single-app day can be split into
three-hour blocks that aren't separate topics. Episode summaries are only as
good as the captures behind them; an episode of only activity has no
content summary at all.
