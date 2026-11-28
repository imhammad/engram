# 0011: Qwen3-4B-Instruct-2507 as the answer model

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

Recall answers questions from the user's memories with a local language
model. Until now the bundled model was TinyLlama 1.1B, chosen in the original
build only to validate the pipeline. In the Phase 4 test it invented content
when asked to rewrite text (ADR 0010), and it can't follow the citation rules
grounded answers need.

The replacement has to run on a 16 GB Apple Silicon Mac alongside the rest of
Engram, answer in a few seconds, follow instructions closely enough to cite
sources and to say when it doesn't know, and carry a licence that allows
use in a public project.

## Decision

Use **Qwen3-4B-Instruct-2507** in the Q4_K_M GGUF quantisation (2.5 GB, from
`unsloth/Qwen3-4B-Instruct-2507-GGUF` at a pinned revision), run by
llama.cpp with Metal and a 4,096-token context. `scripts/fetch_models.py`
installs it with its SHA-256. TinyLlama is no longer installed or loaded.

**Shortlist and licences.**
- Qwen3-4B-Instruct-2507: Apache 2.0.
- Phi-4-mini-instruct (3.8B): MIT.
- Llama 3.2 3B Instruct: left out. Its community licence adds an acceptable
  use policy and attribution terms, which complicates a public portfolio
  project when two permissively licensed models of the same size exist.

**Comparison** on the Recall evaluation (`scripts/eval_recall.py`: a
synthetic three-day memory with 30 questions, see ADR 0012), M5 MacBook Air,
16 GB:

| | Qwen3-4B-Instruct-2507 | Phi-4-mini-instruct |
|---|---|---|
| answer accuracy, all answerable questions | 100% (25/25) | 96% (24/25) |
| content questions | 100% (14/14) | 93% (13/14) |
| declined unanswerable questions | 100% (5/5) | 100% (5/5) |
| wrongly declined an answerable question | 0% | 7% (1/14) |
| citations pointing at a gold memory | 100% | 100% |
| uncited sentences the checker had to drop | 0 | 2 |
| time to first token, p50 / p95 | 0.23 s / 0.51 s | 0.20 s / 0.56 s |
| full answer, p50 / p95 | 0.88 s / 3.8 s | 0.97 s / 5.6 s |
| generation speed | 33 tokens/s | 27 tokens/s |
| peak memory of the evaluation process | 3.6 GB | 3.4 GB |

(Both models were measured with the same pipeline. After the later tuning in
ADR 0012, Qwen measured 0.19 s / 0.43 s to first token, 0.82 s / 3.6 s for a
full answer, and 37 tokens/s, still at 100% accuracy.)

Activity answers don't use the model and take well under a millisecond with
either.

Qwen answered every question correctly, cited every sentence without needing
correction, and was faster overall. Phi was slightly quicker to its first
token but slower to finish, and it once declined a question whose answer
was in the top source ("Where is my next meeting with Dr. Lee?").

## Consequences

Answers are grounded and fast enough to feel immediate: under a second for
most questions, up to about four seconds for summaries. The model adds 2.5 GB
on disk and about 3 GB of memory while Engram runs, a real cost on a 16 GB
Mac that consolidation (Phase 6) will also have to share.

The evaluation is small and was written alongside the pipeline, so 100% is a
statement about these 30 questions, not a guarantee. It should grow with
questions taken from real use. Qwen3's 262k-token native context is mostly
unused at 4k; a longer context would let summaries cover more memories at
the cost of memory and speed. Changing the model later means changing the
pinned entry in `fetch_models.py` and `paths.LLM_FILENAME`, and re-running
the evaluation.
