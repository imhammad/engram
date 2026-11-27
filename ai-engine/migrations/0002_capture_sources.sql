-- Phase 4: record where captured text came from, and the URL in the ledger.
ALTER TABLE traces ADD COLUMN text_source TEXT NOT NULL DEFAULT '';   -- accessibility | ocr | typed | audio
ALTER TABLE capture_log ADD COLUMN text_source TEXT NOT NULL DEFAULT '';
ALTER TABLE capture_log ADD COLUMN url TEXT NOT NULL DEFAULT '';
CREATE INDEX traces_app_title ON traces(app_name, window_title);
CREATE INDEX traces_url ON traces(url);
