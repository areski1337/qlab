-- Portefeuilles et déploiements démo.
CREATE TABLE portfolios (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  method TEXT NOT NULL,
  config_json TEXT NOT NULL,
  report_artifact TEXT REFERENCES artifacts(sha256),
  version TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE portfolio_allocations (
  portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
  revision_id TEXT NOT NULL REFERENCES genome_revisions(id),
  weight REAL NOT NULL,
  rationale_json TEXT NOT NULL,
  PRIMARY KEY (portfolio_id, revision_id)
);

CREATE TABLE demo_deployments (
  id TEXT PRIMARY KEY,
  revision_id TEXT NOT NULL REFERENCES genome_revisions(id),
  ea_id TEXT NOT NULL REFERENCES ea_artifacts(id),
  magic INTEGER NOT NULL,
  server TEXT,
  account_masked TEXT,
  risk_stage REAL NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('registered','observing','suspended','retired')),
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE demo_observations (
  id TEXT PRIMARY KEY,
  deployment_id TEXT NOT NULL REFERENCES demo_deployments(id),
  observed_at TEXT NOT NULL,
  report_json TEXT NOT NULL
);
