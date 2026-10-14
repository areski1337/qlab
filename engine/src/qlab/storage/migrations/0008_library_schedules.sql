-- Bibliothèque de stratégies (favoris, étiquettes, notes) et planification de tâches récurrentes.
CREATE TABLE strategy_notes (
  revision_id TEXT PRIMARY KEY REFERENCES genome_revisions(id),
  favorite INTEGER NOT NULL DEFAULT 0,
  tags_json TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE TABLE schedules (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('campaign', 'import_mt5')),
  payload_json TEXT NOT NULL,
  every TEXT NOT NULL CHECK (every IN ('once', 'daily', 'weekly')),
  next_run_utc TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run_utc TEXT,
  last_task_id TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX ix_schedules_due ON schedules(enabled, next_run_utc);
