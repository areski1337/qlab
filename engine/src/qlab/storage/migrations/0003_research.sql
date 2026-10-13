-- Recherche : génomes, révisions immuables, filiation, campagnes, évaluations, statuts.
CREATE TABLE genome_revisions (
  id TEXT PRIMARY KEY,
  genome_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  content_json TEXT NOT NULL,
  semantic_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unverified' CHECK (status IN ('unverified','screened','historically_tested',
    'robustness_tested','oos_evaluated','reference_matched','mt5_validated','demo_observed','rejected','quarantined')),
  campaign_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(genome_id, revision)
);
CREATE INDEX ix_rev_hash ON genome_revisions(semantic_hash);
CREATE INDEX ix_rev_campaign ON genome_revisions(campaign_id);

CREATE TABLE genealogy (
  child_id TEXT NOT NULL REFERENCES genome_revisions(id),
  parent_id TEXT NOT NULL REFERENCES genome_revisions(id),
  operator TEXT NOT NULL,
  operator_version TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (child_id, parent_id)
);

CREATE TABLE status_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  revision_id TEXT NOT NULL REFERENCES genome_revisions(id),
  from_status TEXT NOT NULL,
  to_status TEXT NOT NULL,
  criteria_json TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  ts TEXT NOT NULL
);

CREATE TABLE campaigns (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  config_json TEXT NOT NULL,
  config_sha256 TEXT NOT NULL,
  task_id TEXT REFERENCES tasks(id),
  state TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE evaluations (
  id TEXT PRIMARY KEY,
  cache_key TEXT NOT NULL UNIQUE,
  revision_id TEXT NOT NULL REFERENCES genome_revisions(id),
  campaign_id TEXT,
  dataset_version_id TEXT NOT NULL REFERENCES dataset_versions(id),
  context_versions_json TEXT NOT NULL,
  segment TEXT NOT NULL,
  window_json TEXT NOT NULL,
  cost_profile_sha256 TEXT NOT NULL,
  risk_limits_sha256 TEXT NOT NULL,
  protocol_json TEXT NOT NULL,
  seed INTEGER,
  versions_json TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  trades_artifact TEXT REFERENCES artifacts(sha256),
  created_at TEXT NOT NULL
);
CREATE INDEX ix_eval_rev ON evaluations(revision_id);
CREATE INDEX ix_eval_campaign ON evaluations(campaign_id);

-- Mémoire évolutive : efficacité des opérateurs par portée (global, campagne, tribu).
CREATE TABLE evolution_memory (
  scope TEXT NOT NULL,
  key TEXT NOT NULL,
  tries INTEGER NOT NULL DEFAULT 0,
  successes INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (scope, key)
);
