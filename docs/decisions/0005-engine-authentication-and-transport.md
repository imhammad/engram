# 0005: Engine authentication and transport

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

The engine is an HTTP server on the loopback interface. Until this decision
it listened on the fixed port 8000, accepted requests from anyone, and sent
`Access-Control-Allow-Origin: *`. Loopback is not a security boundary on its
own: every process the user runs can connect to 127.0.0.1, and so can any web
page open in a browser, because browsers will send requests to localhost.
With a wildcard CORS policy a malicious page could have read every memory or
deleted them all. A fixed port also made the engine easy to find and meant a
second copy of the app, or an orphaned engine, would silently share data.

## Decision

**A secret per launch.** On every start the Rust shell draws 256 bits from the
operating system's random source and passes them to the engine as
`ENGRAM_TOKEN`. The engine refuses to start without a token of at least 32
characters, and rejects any request whose `X-Engram-Token` header does not
match, using a constant-time comparison. This includes `/health`, which now
returns only `{"status": "ok"}`. The interactive API docs are switched off.

**A random port per launch.** The shell asks the OS for a free loopback port
and passes it as `ENGRAM_PORT`. The engine binds 127.0.0.1 only. There is a
short window between the shell releasing the port and the engine binding it;
if another program takes it, the engine exits and the app reports a start
failure. If something already answering on that port does not know the
token, the shell's readiness check gets a 401 and reports that too.

**Strict CORS.** Only the app's own webview origins are allowed:
`tauri://localhost`, `http://tauri.localhost` and `https://tauri.localhost`.
Debug builds also pass `ENGRAM_DEV_ORIGIN=http://localhost:1420` for the Vite
dev server. A preflight from any other origin gets no approval, and since
the token is in a custom header, a cross-origin page cannot even send an
authenticated request without a preflight.

**One client.** The frontend gets the base URL and token from the
`engine_connection` command and sends every request through `src/lib/api.ts`.
The Rust window tracker builds its requests through `engine::request`, which
adds the header.

**No orphans.** The shell also passes its own process id as
`ENGRAM_PARENT_PID`, and the engine shuts itself down within about two
seconds of that process disappearing. Without this, `tauri dev` (which
kills and restarts the app on every Rust change) left a full engine running
on a stale port each time, and a crash of the app would do the same.

**Development.** With `ENGRAM_DEV_ENGINE=1` the shell does not spawn the
sidecar; it reads `ENGRAM_TOKEN` and `ENGRAM_PORT` from its own environment,
which the developer sets to the same values used to start the engine.

### Why not a Unix domain socket

A Unix socket in the app's data directory, readable only by the user, would
take the engine off the network stack entirely and replace the token with
file permissions. We evaluated it and kept TCP for now. The webview cannot
open a Unix socket: `fetch` only speaks TCP. Every frontend call would have
to become a Tauri command that the Rust side forwards to the socket, which
means duplicating each endpoint in Rust or writing a generic proxy, and
giving up streaming responses we will want for answers later. The token and
strict CORS close the practical attack, a web page or another local user's
process reaching the engine, without that restructuring. If the engine gains
endpoints that make a proxy worthwhile anyway, this should be revisited.

## Consequences

Web pages can no longer read or change memories, and other local processes
need the token, which exists only in the app's and the engine's memory and
environment. Processes running as the same user can still read another
process's environment with enough effort, so this does not defend against
malware already running as the user; that is out of scope (see
docs/threat-model.md). Running the engine by hand now needs two environment
variables. Every request carries one extra header.
