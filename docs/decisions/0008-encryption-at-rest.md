# 0008: Encryption at rest and Keychain key handling

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Engram's database holds what a person read and heard while working. Before
Phase 3 it was a plain SQLite file, protected only by FileVault, if the user
had turned it on, and by file permissions. Anything that copied the file (a
backup to an unencrypted drive, a sync tool, a stolen disk image, a careless
upload) exposed every memory in readable form.

## Decision

**SQLCipher.** The database is encrypted with SQLCipher 4 (AES-256 in CBC
mode with HMAC-SHA512 page authentication), through the `sqlcipher3` Python
package. The whole file is encrypted, including FTS5 and sqlite-vec data. The
file has no plain SQLite header and cannot be opened by `sqlite3` or any
other tool without the key. A wrong key fails on the first read, and the
engine stops with an explanation instead of creating a new empty database.

**A random key in the Keychain.** On first run the Rust shell draws 256 bits
from the operating system's random source and stores them, hex-encoded, as a
generic password in the user's login Keychain (service `dev.engram.app`,
account `database-key`). On later runs it reads the key back. It is a raw
key, passed to SQLCipher as `x'...'`, so no password-based key derivation is
involved and there is no password to guess.

**Handed over on stdin.** The shell writes the key as one line to the engine's
standard input right after starting it. The engine reads that line before it
does anything else. The key is never placed in argv, which every process can
see in `ps`, or in the environment, which other processes of the same user
can read. It is never logged, by the shell or the engine, and tests check
that it does not appear in the engine's output or environment.

**Development.** Running the engine by hand needs the same key, piped in:
`security find-generic-password -s dev.engram.app -a database-key -w | python main.py`.

**Other platforms.** Only macOS has a key store wired up. On other platforms
the shell refuses to start the encrypted engine; Windows Credential Manager
support is future work.

## Consequences

A copy of `memory.db` on its own reveals nothing. Decrypting it needs the
Keychain item, which macOS protects with the user's login, and which is not
included in iCloud Keychain sync because it is a local login-keychain item.

The costs and risks:

- **Losing the key loses the data.** If the Keychain item is deleted, or the
  database is moved to another Mac without it, the database cannot be opened.
  The Settings page says this plainly. A key export and recovery path should
  be added before Engram is used by people other than its developer.
- **Same-user processes.** A program running as the user can ask the
  Keychain for the item; macOS may prompt the first time a different program
  asks. This does not protect against malware already running as the user
  (see docs/threat-model.md).
- **Old plain files.** The pre-Phase-3 plain database is moved into a backup
  folder during the one-time import. It stays readable there until the user
  deletes it, which they should do once they are satisfied the import worked.
- SQLCipher adds a small cost to every page read and write; the benchmark in
  ADR 0007 includes it.
