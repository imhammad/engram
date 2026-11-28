-- Phase 6: consolidation (episodes and days), forgetting and open loops.

ALTER TABLE episodes ADD COLUMN day TEXT NOT NULL DEFAULT '';           -- local YYYY-MM-DD
ALTER TABLE episodes ADD COLUMN apps TEXT NOT NULL DEFAULT '[]';        -- [{"app_name", "seconds"}]
ALTER TABLE episodes ADD COLUMN focused_seconds REAL NOT NULL DEFAULT 0;
CREATE INDEX episodes_day ON episodes(day);
CREATE INDEX episodes_started ON episodes(started_at);

-- What an episode was built from. Unlike episode_traces this is a snapshot
-- that outlives its trace: when a trace fades, its row stays, marked faded,
-- so the episode can still say what it drew on.
CREATE TABLE episode_sources (
    episode_id TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    trace_id TEXT NOT NULL,
    app_name TEXT NOT NULL DEFAULT '',
    window_title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    faded INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (episode_id, n)
);
CREATE INDEX episode_sources_trace ON episode_sources(trace_id);

ALTER TABLE days ADD COLUMN stats TEXT NOT NULL DEFAULT '{}';            -- focused time, top apps
ALTER TABLE day_episodes ADD COLUMN n INTEGER NOT NULL DEFAULT 0;

CREATE VIRTUAL TABLE episode_vectors USING vec0(embedding float[384] distance_metric=cosine);

-- Things the user said they would do, found in their memories.
CREATE TABLE open_loops (
    id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL UNIQUE,
    app_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'dismissed')),
    updated_at TEXT NOT NULL
);
CREATE INDEX open_loops_status ON open_loops(status);
