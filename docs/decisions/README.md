# Architecture Decision Records

This folder holds the Architecture Decision Records (ADRs) for Engram. Each
record captures one significant decision: what we were facing, what we chose,
and what follows from that choice. They exist so that anyone reading the code
later, including us, can see why it looks the way it does.

Records are numbered in the order they were written and are never renumbered.
Each one has three sections:

- **Context**: the situation and the forces at play when the decision was made.
- **Decision**: what we decided to do.
- **Consequences**: what becomes easier, what becomes harder, and what we now
  have to live with.

An accepted record is not edited to change its meaning. If a decision is
reversed or refined, write a new record that supersedes the old one and note
the link in both.

## Index

- [0001: Record architecture decisions](0001-record-architecture-decisions.md)
- [0002: Model memory like a brain](0002-model-memory-like-a-brain.md)
- [0003: Where data and models live, and a network-zero runtime](0003-data-and-model-locations.md)
- [0004: Sidecar packaging and lifecycle](0004-sidecar-packaging-and-lifecycle.md)
- [0005: Engine authentication and transport](0005-engine-authentication-and-transport.md)
- [0006: Capture exclusions, redaction and the quality gate](0006-exclusions-redaction-quality-gate.md)
- [0007: One SQLite file with sqlite-vec and FTS5 instead of ChromaDB](0007-single-sqlite-store.md)
- [0008: Encryption at rest and Keychain key handling](0008-encryption-at-rest.md)
- [0009: Text source order: Accessibility first, Apple Vision OCR as the fallback](0009-text-source-order.md)
- [0010: Change-aware recapture, and no LLM rewriting of captures](0010-change-aware-recapture-no-llm-rewriting.md)

See also [the threat model](../threat-model.md).
