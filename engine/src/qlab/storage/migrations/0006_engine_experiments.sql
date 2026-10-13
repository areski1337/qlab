-- Expériences sur les méthodes de recherche (évolution du moteur, distincte de l'évolution des stratégies).
CREATE TABLE engine_experiments (
  id TEXT PRIMARY KEY,
  hypothesis TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  spec_sha256 TEXT NOT NULL,
  task_id TEXT REFERENCES tasks(id),
  results_json TEXT,
  verdict TEXT CHECK (verdict IN ('promote_candidate','reject','inconclusive')),
  created_at TEXT NOT NULL
);

CREATE TABLE engine_promotions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT REFERENCES engine_experiments(id),
  channel TEXT NOT NULL CHECK (channel IN ('experimental')),
  overrides_json TEXT NOT NULL,
  previous_json TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('promote','rollback')),
  ts TEXT NOT NULL
);
