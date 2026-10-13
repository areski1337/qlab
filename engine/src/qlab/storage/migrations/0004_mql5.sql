-- MQL5 : artefacts EA, compilations réelles, runs de parité.
CREATE TABLE ea_artifacts (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES genome_revisions(id),
  source_sha256 TEXT NOT NULL REFERENCES artifacts(sha256),
  generator_version TEXT NOT NULL,
  symbol TEXT NOT NULL,
  tz_profile TEXT NOT NULL,
  risk_limits_sha256 TEXT NOT NULL,
  meta_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(revision_id, source_sha256)
);

CREATE TABLE compilation_runs (
  id TEXT PRIMARY KEY,
  ea_id TEXT NOT NULL REFERENCES ea_artifacts(id),
  status TEXT NOT NULL CHECK (status IN ('succeeded','failed','blocked')),
  errors INTEGER,
  warnings INTEGER,
  exit_code INTEGER,
  metaeditor_path TEXT,
  log_artifact TEXT REFERENCES artifacts(sha256),
  ex5_artifact TEXT REFERENCES artifacts(sha256),
  diagnostic TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE parity_runs (
  id TEXT PRIMARY KEY,
  ea_id TEXT NOT NULL REFERENCES ea_artifacts(id),
  status TEXT NOT NULL CHECK (status IN ('completed','failed','blocked')),
  grade TEXT,
  critical INTEGER,
  tester_config_json TEXT NOT NULL,
  report_json TEXT,
  trace_artifact TEXT REFERENCES artifacts(sha256),
  diagnostic TEXT,
  created_at TEXT NOT NULL
);
