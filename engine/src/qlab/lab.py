"""Contexte applicatif : chemins, base, artefacts, journaux."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .core.config import Paths, default_data_dir, load_settings
from .core.logging import JsonLogger
from .storage import db
from .storage.artifacts import ArtifactStore


@dataclass
class Lab:
    paths: Paths
    con: object
    store: ArtifactStore
    log: JsonLogger
    settings: dict
    versions_sha: str

    @classmethod
    def open(cls, root: Path | str | None = None) -> "Lab":
        paths = Paths(Path(root) if root else default_data_dir()).ensure()
        settings = load_settings(paths)
        con = db.connect(paths.db)
        applied = db.migrate(con, paths.db, paths.backups, settings["disk"]["min_free_mb"] // 40)
        log = JsonLogger(paths.logs)
        if applied:
            log.info("db.migrated", migrations=applied)
        lab = cls(paths, con, ArtifactStore(paths.artifacts, con), log, settings, db.record_versions(con))
        return lab

    @classmethod
    def attach(cls, root: Path | str) -> "Lab":
        """Nouvelle connexion sur une base déjà migrée (une par thread : sqlite3 n'est pas partageable)."""
        paths = Paths(Path(root))
        con = db.connect(paths.db)
        return cls(paths, con, ArtifactStore(paths.artifacts, con), JsonLogger(paths.logs), load_settings(paths), "")

    def close(self) -> None:
        self.con.close()
