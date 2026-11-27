# 0007: One SQLite file with sqlite-vec and FTS5 instead of ChromaDB

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Until Phase 3 Engram kept its data in two places: a plain SQLite file for
memories, activity and the ledger, and a ChromaDB folder for vectors. Every
save wrote to both, every delete had to remember both, and nothing kept them
consistent if one write failed. ChromaDB also brought a large dependency tree
(ONNX Runtime, gRPC, OpenTelemetry, a Kubernetes client) into the engine and
the sidecar, and it had telemetry that had to be switched off. Search was
vector-only, so exact names, numbers and rare words that embeddings blur were
easy to miss. And the memory model in ADR 0002 needs room for episodes, days,
pinning and recall times that the old schema did not have.

## Decision

**One database.** Everything lives in `data/memory.db`, a SQLCipher-encrypted
SQLite file (encryption is ADR 0008). It holds:

- `traces`, the first memory tier: content, source, app, redacted window
  title, URL, time, quality score, a content hash, pinned and last-recalled
  fields.
- `traces_fts`, an FTS5 index over trace text and titles (Porter stemming),
  kept in step by triggers.
- `trace_vectors`, a sqlite-vec `vec0` table of 384-dimensional cosine
  vectors keyed by the trace's rowid.
- `episodes`, `days` and their link tables, empty until consolidation exists.
- `activity_sessions`, `capture_log`, `exclusion_rules` and `settings`.

A trace, its keyword entry and its vector are written in one transaction.
Schema changes are numbered SQL files in `ai-engine/migrations/`, recorded in
`schema_migrations` and applied at startup.

We verified first that the pieces fit: the `sqlcipher3` 0.6.5 wheel (SQLCipher
4.20 on SQLite 3.54) loads the `sqlite-vec` 0.1.9 extension and has FTS5, on
macOS arm64 and on Linux x86_64 for CI. No fallback was needed.

**Hybrid search.** `/search` runs an FTS5 BM25 query and a vector query and
merges the two rankings with reciprocal rank fusion (k = 60), with optional
`since`, `until` and `app` filters. User text is reduced to quoted words before
it reaches FTS5, so punctuation cannot break the query. A test fixture checks
the point of fusion: a document that is second in both rankings beats one
that wins only on keywords and one that wins only on meaning.

**Dedupe.** Each trace stores a SHA-256 of its whitespace- and case-normalised
text with a unique index. Saving or capturing identical text returns the
existing memory, and the ledger records the capture as a duplicate.

**Activity as sessions.** The shell reports window switches and the moments
activity stops: idle (no input for five minutes, from the CoreGraphics idle
time), screen lock (from the CoreGraphics session dictionary), sleep (a gap
in the wall clock between two polls) and quit. Each switch closes the open
session and starts a new one, so each row has a start, end and duration. The
Dashboard's "Today" panel adds these up per app.

**Measurements** (`ai-engine/scripts/benchmark_store.py`, M5 MacBook Air,
10,000 synthetic traces of 20 to 80 words, random vectors, 200 queries):

| | p50 | p95 |
|---|---|---|
| hybrid search | 29.7 ms | 36.6 ms |
| hybrid search with an app filter | 31.0 ms | 35.7 ms |
| keyword only | 8.4 ms | 9.4 ms |
| vector only | 20.1 ms | 25.2 ms |

Inserting took 0.29 ms per trace and the database was 25.8 MB (2.6 KB per
trace including its vector and index entries). Vector search in `vec0` is
exact (brute force), which is the right trade at personal scale: no index to
tune and no recall loss. At around 100,000 traces it would approach 200 ms
and an approximate index should be considered.

Removing ChromaDB and its dependencies shrank the sidecar from 345.0 MB to
315.9 MB; most of what remains is PyTorch, used by the embedding model.

## Consequences

Saves and deletes are atomic, backups are one file, and search finds both
exact terms and paraphrases. The engine has far fewer dependencies. The
schema now matches the memory model in ADR 0002, ready for consolidation and
forgetting.

The costs: sqlite-vec is a young project (0.1.x), so its API may change, and
the pinned version should be upgraded deliberately. Brute-force vector search
will need replacing if a user reaches hundreds of thousands of traces. FTS5
uses English Porter stemming, which suits English text and helps less with
other languages.
