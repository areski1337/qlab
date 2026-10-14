-- Frontières de segments datées, figées au premier usage d'une série (dataset) : un ré-import plus long
-- ne fait jamais glisser d'anciennes barres oos/final vers train/validation ; les barres nouvelles forment
-- le segment « forward ».
CREATE TABLE segment_boundaries (
  dataset_id TEXT NOT NULL REFERENCES datasets(id),
  protocol_sha256 TEXT NOT NULL,
  train_end_ts INTEGER NOT NULL,
  validation_end_ts INTEGER NOT NULL,
  oos_end_ts INTEGER NOT NULL,
  final_end_ts INTEGER NOT NULL,
  first_version_id TEXT NOT NULL REFERENCES dataset_versions(id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (dataset_id, protocol_sha256)
);

-- Paliers de risque démo : nombre de transactions observées au début du palier courant ; une montée exige
-- de nouvelles transactions depuis ce point (jamais les mêmes pour deux paliers).
ALTER TABLE demo_deployments ADD COLUMN stage_base_trades INTEGER NOT NULL DEFAULT 0;
