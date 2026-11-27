-- Engram memory store, schema version 1.
-- One SQLCipher-encrypted SQLite file holds everything: memories (traces),
-- their keyword index (FTS5) and vectors (sqlite-vec), activity sessions,
-- the capture ledger, exclusion rules and settings. See ADR 0007.

-- Tier 1: traces. Everything captured or typed starts here.
CREATE TABLE traces (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',   -- manual | screen_ocr | audio_transcription
    app_name TEXT NOT NULL DEFAULT '',
    window_title TEXT NOT NULL DEFAULT '',   -- redacted before storage
    url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    quality REAL,                            -- share of real words, for captures
    content_hash TEXT NOT NULL UNIQUE,       -- dedupe: identical traces are stored once
    pinned INTEGER NOT NULL DEFAULT 0,
    last_recalled_at TEXT
);
CREATE INDEX traces_created_at ON traces(created_at);
CREATE INDEX traces_app ON traces(app_name);

-- Keyword index over traces, kept in step by triggers.
CREATE VIRTUAL TABLE traces_fts USING fts5(
    content, window_title,
    content='traces', content_rowid='rowid',
    tokenize='porter unicode61'
);
CREATE TRIGGER traces_ai AFTER INSERT ON traces BEGIN
    INSERT INTO traces_fts(rowid, content, window_title) VALUES (new.rowid, new.content, new.window_title);
END;
CREATE TRIGGER traces_ad AFTER DELETE ON traces BEGIN
    INSERT INTO traces_fts(traces_fts, rowid, content, window_title) VALUES ('delete', old.rowid, old.content, old.window_title);
END;
CREATE TRIGGER traces_au AFTER UPDATE OF content, window_title ON traces BEGIN
    INSERT INTO traces_fts(traces_fts, rowid, content, window_title) VALUES ('delete', old.rowid, old.content, old.window_title);
    INSERT INTO traces_fts(rowid, content, window_title) VALUES (new.rowid, new.content, new.window_title);
END;

-- Vectors, one per trace, keyed by the trace's rowid.
CREATE VIRTUAL TABLE trace_vectors USING vec0(embedding float[384] distance_metric=cosine);

-- Tiers 2 and 3: episodes and days, filled by consolidation in a later phase.
CREATE TABLE episodes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE episode_traces (
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    PRIMARY KEY (episode_id, trace_id)
);
CREATE TABLE days (
    date TEXT PRIMARY KEY,                   -- YYYY-MM-DD, local time
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE day_episodes (
    date TEXT NOT NULL REFERENCES days(date) ON DELETE CASCADE,
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    PRIMARY KEY (date, episode_id)
);

-- Activity as sessions: one row per stretch of time in one window.
CREATE TABLE activity_sessions (
    id TEXT PRIMARY KEY,
    app_name TEXT NOT NULL,
    window_title TEXT NOT NULL DEFAULT '',   -- redacted, or [excluded]
    started_at TEXT NOT NULL,
    ended_at TEXT,                           -- NULL while the session is open
    duration_seconds REAL,
    end_reason TEXT                          -- switch | idle | sleep | lock | quit
);
CREATE INDEX activity_sessions_started ON activity_sessions(started_at);

CREATE TABLE capture_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    app_name TEXT NOT NULL DEFAULT '',
    window_title TEXT NOT NULL DEFAULT '',
    trigger TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    memory_id TEXT
);
CREATE INDEX capture_log_created ON capture_log(created_at);

CREATE TABLE exclusion_rules (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('app', 'title')),
    pattern TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
