# 0012: The Recall pipeline: routing, grounding and abstention

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

Recall is the reason Engram exists: the user asks "what did I work on
yesterday?" or "what was that EEG article about?" and gets a correct answer
in seconds, with its sources, entirely on the Mac. The worst outcome is a
confident wrong answer, because a memory aid people can't trust is worse
than none. Questions also differ in kind: "how long was I in Chrome today?"
is arithmetic over activity data that a language model shouldn't be doing.

## Decision

**Time first, deterministically.** `timeparse.py` turns phrases into a
half-open range in the user's local time zone: today, yesterday, the day
before yesterday, this morning, afternoon or evening, last night, this week,
last week, this month, last month, weekday names ("on Tuesday", "last
Friday"), dates ("the 25th", "25 Nov", "November 25"), "N hours ago", "in the
last N days", "since 3pm", "between 2 and 4pm" and "around 10am". Dates are
where small models are least reliable, so the model never interprets them.
33 tests pin the behaviour, including time zones.

**Three routes.**

- *Activity* ("how long", "which apps", "when did I last use") is answered
  from the `activity_sessions` table with plain code and a template. The
  numbers never pass through the model, so they cannot be invented, and the
  answer comes back with a per-app breakdown. System dialog processes are
  left out.
- *Summary* ("what did I work on yesterday", "recap") starts with the
  period's activity totals, written by code, then asks the model for two to
  four cited sentences about that period's memories: the longest capture
  from each window, most recent first, up to eight.
- *Content* (everything else) runs hybrid search with the question's period
  and app as filters, and the model answers from the results.

**Only relevant sources.** Recall's search returns a memory only with real
evidence: a keyword match on a word that isn't a stopword, or a vector
cosine distance of 0.6 or less. If nothing qualifies, the answer is "I
couldn't find that in your memories" and the model is never asked. Each
source is cut to 1,000 characters (its opening paragraph and its
best-matching part) and all sources together to 4,500, which fits the
4,096-token context with room for the answer. A cross-encoder reranker was considered but not added: retrieval
already found the right memory for every evaluation question, so there was
nothing to measure an improvement against.

**Grounded answers.** Sources are numbered in the prompt with their app,
window and time, and the model is told to use only them, end every sentence
with its source numbers, and reply with the exact not-found sentence when
they don't answer the question. Generation runs at temperature 0.1. The
answer is then checked:

- citations to sources that don't exist are removed;
- a sentence without a citation is kept only if the next cited sentence's
  source supports it (at least 60 percent of its content words appear in
  that source). Writers often cite once at the end of a short run of
  sentences, and this keeps those runs without letting an unsupported claim
  through;
- other uncited sentences are dropped, and the interface says how many;
- if nothing cited survives, the answer becomes the not-found sentence.

Sentence splitting copes with "Dr.", version numbers, "..." inside quotes,
and citations placed after the full stop. Memories used in an answer get
`last_recalled_at` set, ready for forgetting in Phase 6.

**Streaming.** `POST /recall` returns newline-delimited JSON: a `meta` event
with the route, period and candidate sources, `token` events as the model
writes, and a `done` event with the checked answer, the cited sources and,
for activity, the breakdown. The Recall page shows tokens as they arrive and
then replaces them with the checked answer.

**History.** Questions and answers are kept in a `recall_history` table in
the encrypted store, shown on the Recall page with a Clear history button,
included in the export and in "Delete everything".

**Evaluation.** `evaluation/recall_fixture.py` is a synthetic three-day
memory (16 captures, 17 sessions: coding, papers, a meeting note, mail,
chat, shopping, travel) with 30 questions: 8 activity, 14 content, 3
summaries and 5 that can't be answered. `scripts/eval_recall.py` reports
retrieval recall at 5, citation correctness, answer accuracy (every
required keyword group present), abstention, and latency. With the chosen
model (ADR 0011): retrieval recall at 5 was 100%, citations 100%, answer
accuracy 100% (25/25), all 5 unanswerable questions declined with none
wrongly declined, first token p50 0.19 s and p95 0.43 s, and full answer p50
0.82 s and p95 3.6 s. The first run scored 84%. All of the misses were the
checker splitting a sentence at "Apache 2.0" or at the "..." inside a quoted
key, or dropping a correct first sentence whose citation came one sentence
later. Fixing those is
what the support rule and the splitter above are for.

**What real memories changed.** Asking about the owner's own captures
exposed three things the synthetic set didn't:
- Accessibility text from web pages arrives in fragments split around
  links. It is now reflowed into prose before it reaches the model.
- Several captures of the same page wasted the context. Sources are now
  one per page, using the fullest capture.
- Long pages need their opening paragraph as well as the best-matching
  part, so a source starts with the page's first real paragraph.

Before those fixes "What was that EEG article about?" came back as "I
couldn't find that"; after them it answered from the Wikipedia capture with
a citation. Sources were also tightened to 1,000 characters each and 4,500
in total, which brought the first token on real memories down to about one
second.

## Consequences

Activity questions are always exact. Content answers say where each claim
came from, and when the memories don't hold the answer, Recall says so
instead of guessing. Everything stays on the device.

The limits: routing is keyword-based, so an unusual phrasing of an activity
question goes to content search instead. The evaluation set is small and
synthetic. Summaries see at most eight memories per period. The support
rule is lexical, so a paraphrased claim with few shared words is dropped
even when it is true.
