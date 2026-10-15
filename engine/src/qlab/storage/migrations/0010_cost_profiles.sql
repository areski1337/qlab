-- Profils de coûts utilisés par les évaluations (jusqu'ici seule l'empreinte était conservée).
-- Table d'ajout pur : les évaluations antérieures restent valides, leur profil est simplement « non enregistré ».
CREATE TABLE cost_profiles (
  sha256 TEXT PRIMARY KEY,
  profile_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
