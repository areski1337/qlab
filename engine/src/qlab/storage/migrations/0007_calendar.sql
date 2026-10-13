-- Calendrier économique (source : API officielle FXStreet, usage personnel ; non redistribué dans les exports).
CREATE TABLE economic_events (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  event_id TEXT,
  date_ts INTEGER NOT NULL,
  currency TEXT,
  country TEXT,
  name TEXT,
  volatility TEXT,
  is_tentative INTEGER NOT NULL DEFAULT 0,
  is_all_day INTEGER NOT NULL DEFAULT 0,
  actual REAL,
  consensus REAL,
  previous REAL,
  last_updated TEXT,
  fetched_at TEXT NOT NULL
);
CREATE INDEX ix_events_date ON economic_events(date_ts);

CREATE TABLE calendar_coverage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  start_ts INTEGER NOT NULL,
  end_ts INTEGER NOT NULL,
  n_events INTEGER NOT NULL,
  raw_artifact TEXT REFERENCES artifacts(sha256),
  fetched_at TEXT NOT NULL
);
