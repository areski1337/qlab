-- Données de marché : datasets, versions, profils de courtier.
CREATE TABLE broker_profiles (
  id TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  name TEXT NOT NULL,
  profile_json TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(name, version)
);

CREATE TABLE datasets (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  broker TEXT,
  source_symbol TEXT NOT NULL,
  canonical_symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  synthetic INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(source, broker, source_symbol, timeframe)
);

CREATE TABLE dataset_versions (
  id TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL REFERENCES datasets(id),
  version INTEGER NOT NULL,
  parent_version_id TEXT REFERENCES dataset_versions(id),
  file_relpath TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  raw_artifact_sha256 TEXT REFERENCES artifacts(sha256),
  start_utc TEXT,
  end_utc TEXT,
  n_bars INTEGER NOT NULL,
  source_timezone TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  symbol_spec_json TEXT NOT NULL,
  spec_sha256 TEXT NOT NULL,
  qc_json TEXT NOT NULL,
  corrections_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  UNIQUE(dataset_id, version)
);
