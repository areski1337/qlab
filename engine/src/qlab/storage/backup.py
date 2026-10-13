"""Sauvegarde et restauration cohérentes (base + artefacts + datasets).

Format : archive ZIP contenant `qlab.sqlite` (copie via l'API backup de SQLite,
donc cohérente même pendant l'écriture), `artifacts/`, `datasets/` et
`manifest.json` listant l'empreinte SHA-256 de chaque fichier.

La restauration n'écrase jamais un répertoire existant non vide : elle restaure
dans un répertoire cible, vérifie les empreintes et la cohérence des références,
puis l'utilisateur bascule dessus (voir docs/operations/backup-restore.md).
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from ..core.config import Paths
from ..core.hashing import sha256_file
from ..core.timeutil import utc_now, utc_now_iso
from ..core.versions import versions_snapshot
from .artifacts import ArtifactStore
from .db import backup_db, connect

MANIFEST = "manifest.json"


def create_backup(con: sqlite3.Connection, paths: Paths, dest: Path | None = None) -> Path:
    dest = Path(dest) if dest else paths.backups / f"qlab-backup-{utc_now():%Y%m%dT%H%M%S%f}.zip"
    files: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        snap = backup_db(con, Path(tmp) / "qlab.sqlite")
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "qlab.sqlite")
            files["qlab.sqlite"] = sha256_file(snap)
            for sub in ("artifacts", "datasets"):
                base = paths.root / sub
                for f in sorted(base.rglob("*")) if base.exists() else []:
                    if f.is_file() and not f.name.endswith(".tmp"):
                        rel = f.relative_to(paths.root).as_posix()
                        z.write(f, rel)
                        files[rel] = sha256_file(f)
            manifest = {"created_at": utc_now_iso(), "versions": versions_snapshot(), "files": files}
            z.writestr(MANIFEST, json.dumps(manifest, indent=1))
    return dest


def restore_backup(archive: Path, target_root: Path) -> dict:
    """Restaure dans `target_root` (vide ou inexistant) et vérifie l'intégrité. Retourne un rapport."""
    target_root = Path(target_root)
    if target_root.exists() and any(target_root.iterdir()):
        raise FileExistsError(f"le répertoire cible n'est pas vide : {target_root}")
    target_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read(MANIFEST))
        for name in z.namelist():
            # Protection contre les chemins sortant du répertoire cible (zip slip).
            if (target_root / name).resolve().is_relative_to(target_root.resolve()) is False:
                raise ValueError(f"chemin d'archive refusé : {name}")
        z.extractall(target_root)
    return verify_restored(target_root, manifest)


def verify_restored(root: Path, manifest: dict) -> dict:
    paths = Paths(root)
    mismatched = [rel for rel, sha in manifest["files"].items()
                  if not (root / rel).exists() or sha256_file(root / rel) != sha]
    con = connect(paths.db)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = [tuple(r) for r in con.execute("PRAGMA foreign_key_check")]
        missing_artifacts = ArtifactStore(paths.artifacts, con).verify_all()
        dangling = _dangling_refs(con, paths)
    finally:
        con.close()
    ok = not mismatched and integrity == "ok" and not fk and not missing_artifacts and not dangling
    return {"ok": ok, "files_checked": len(manifest["files"]), "hash_mismatches": mismatched,
            "sqlite_integrity": integrity, "foreign_key_violations": fk,
            "missing_artifacts": missing_artifacts, "dangling_references": dangling,
            "backup_versions": manifest["versions"]}


def _dangling_refs(con: sqlite3.Connection, paths: Paths) -> list[str]:
    """Références vers des fichiers de datasets absents (les artefacts sont couverts par verify_all)."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out = []
    if "dataset_versions" in tables:
        for r in con.execute("SELECT id, file_relpath FROM dataset_versions"):
            if not (paths.root / r[1]).exists():
                out.append(f"dataset_versions:{r[0]}")
    return out
