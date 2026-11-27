# 0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Engram has grown through ten phases of work, and many of its important choices
live only in commit messages, pull request descriptions, and memory. As the
project moves to macOS and starts a new phased plan, we need a durable place to
explain why the system is shaped the way it is, so that later changes are made
with the original reasoning in view rather than rediscovered or accidentally
undone.

## Decision

We will keep Architecture Decision Records in `docs/decisions/`. Each record is
a short Markdown file, numbered in sequence, with Context, Decision, and
Consequences sections. A record is written when a choice is hard to reverse,
affects more than one part of the system, or would surprise a new reader of the
code.

## Consequences

Significant decisions gain a written rationale that travels with the code and
is reviewed in the same pull requests. Writing a record takes a little time,
and the folder only stays useful if we keep it current: superseded decisions
must be marked as such rather than silently left behind.
