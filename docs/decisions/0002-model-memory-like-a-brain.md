# 0002: Model memory like a brain

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Engram captures what a person sees and hears while they work: screen text,
active windows, typed notes, and short audio clips. The obvious design for such
a tool is a recorder that keeps everything forever and searches it later, much
like a DVR for the desktop.

That design has real costs. Keeping every raw capture indefinitely means a
growing store of sensitive material on the device, much of it passwords,
private messages, and other incidental text that was never meant to be kept.
The search index grows without bound, which makes retrieval slower and noisier
as months pass. And it produces a product that looks like many others: a large,
undifferentiated archive that the user must dig through.

Engram's name already points at a different model. Human memory does not keep
a perfect recording. It holds brief impressions, consolidates the meaningful
ones into lasting memories, and lets the rest fade.

## Decision

Engram is modeled on human memory rather than on a recorder.

- **Raw captures are short-lived traces.** Screen text, window activity, and
  audio transcripts enter the system as raw traces. They are useful for a
  while, but they are not the permanent record.
- **Consolidation turns traces into memories.** A consolidation step groups
  related traces into episodes, such as a working session on one document or a
  meeting, and writes a summary for each day. Episodes and day summaries are
  the durable layer that the user browses and that questions are answered from.
- **Raw traces fade on a forgetting curve.** Each trace loses strength over
  time and is eventually deleted. Recalling a trace, by having it cited in an
  answer or opening it directly, strengthens it and slows its decay. The user
  can pin any trace or episode to keep it indefinitely.
- **Asking a question is recall.** When the user asks Engram something, it
  retrieves from episodes, summaries, and any surviving traces, and every
  answer cites the sources it drew on so the user can check them.

## Consequences

Privacy improves by default, because most incidental captures are gone within
a bounded time instead of accumulating forever. The index stays small and
focused on consolidated material, which keeps retrieval fast and the results
relevant. The product has a clear and distinctive identity that follows from
its name.

The costs are also real. Engram will sometimes forget a detail the user later
wants, so pinning must be easy and the forgetting schedule must be visible and
adjustable. Consolidation is new work that has to run reliably on the device
without draining resources, and its summaries must be good enough to stand in
for the traces they replace. Cited sources must point to material that still
exists, so citations need to resolve to episodes and summaries, not only to raw
traces that may have faded. Existing stored captures will need a migration path
into this model.
