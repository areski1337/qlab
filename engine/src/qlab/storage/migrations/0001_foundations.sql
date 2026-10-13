-- Fondations : artefacts, audit, tâches, checkpoints, configurations, versions.
CREATE TABLE artifacts (
  sha256 TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  media_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  correlation_id TEXT,
  subject_id TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_audit_subject ON audit_events(subject_id);

CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('queued','validating','running','paused','completed','failed','cancelled','quarantined')),
  priority INTEGER NOT NULL DEFAULT 0,
  idempotency_key TEXT UNIQUE,
  payload_json TEXT NOT NULL,
  result_json TEXT,
  error TEXT,
  progress REAL NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX ix_tasks_state ON tasks(state, priority DESC, created_at);

CREATE TABLE checkpoints (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  seq INTEGER NOT NULL,
  artifact_sha256 TEXT NOT NULL REFERENCES artifacts(sha256),
  created_at TEXT NOT NULL,
  UNIQUE(task_id, seq)
);

CREATE TABLE configuration_snapshots (
  sha256 TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE engine_versions (
  sha256 TEXT PRIMARY KEY,
  versions_json TEXT NOT NULL,
  first_seen_at TEXT NOT NULL
);
