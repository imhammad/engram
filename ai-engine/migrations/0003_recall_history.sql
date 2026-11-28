-- Phase 5: questions asked in Recall and the answers given, kept in the
-- encrypted store so the user can look back; cleared from the Recall page.
CREATE TABLE recall_history (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    route TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX recall_history_created ON recall_history(created_at);
