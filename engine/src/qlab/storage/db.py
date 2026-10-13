"""SQLite : connexion, migrations versionnées avec sauvegarde préalable."""
from __future__ import annotations

import json
import shutil
import sqlite3
from importlib import resources
from pathlib import Path

from ..core.hashing import sha256_bytes, sha256_json
from ..core.logging import redact
from ..core.timeutil import utc_now, utc_now_iso
from ..core.versions import versions_snapshot


class MigrationError(RuntimeError):
    pass


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def available_migrations() -> list[tuple[int, str, str]]:
    files = resources.files("qlab.storage") / "migrations"
    out = []
    for f in sorted(files.iterdir(), key=lambda p: p.name):
        if f.name.endswith(".sql"):
            out.append((int(f.name.split("_", 1)[0]), f.name, f.read_text(encoding="utf-8")))
    return out


def applied_migrations(con: sqlite3.Connection) -> dict[int, str]:
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                "checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
    return {r["version"]: r["checksum"] for r in con.execute("SELECT version, checksum FROM schema_migrations")}


def backup_db(con: sqlite3.Connection, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = sqlite3.connect(dest)
    try:
        con.backup(out)
    finally:
        out.close()
    return dest


def migrate(con: sqlite3.Connection, db_path: Path, backup_dir: Path, min_free_mb: int = 50,
            migrations: list[tuple[int, str, str]] | None = None) -> list[str]:
    """Applique les migrations manquantes. Sauvegarde cohérente avant toute modification."""
    applied = applied_migrations(con)
    todo = []
    for version, name, sql in migrations if migrations is not None else available_migrations():
        checksum = sha256_bytes(sql.encode())
        if version in applied:
            if applied[version] != checksum:
                raise MigrationError(f"migration {name} modifiée après application (checksum différent)")
            continue
        todo.append((version, name, sql, checksum))
    if not todo:
        return []

    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise MigrationError("intégrité SQLite invalide : migration refusée")
    if shutil.disk_usage(Path(db_path).parent).free < min_free_mb * 1024 * 1024:
        raise MigrationError("espace disque insuffisant pour migrer")
    if applied:  # une base vide n'a rien à sauvegarder
        backup_db(con, Path(backup_dir) / f"pre-migration-v{max(applied)}-{utc_now():%Y%m%dT%H%M%S%f}.sqlite")

    done = []
    for version, name, sql, checksum in todo:
        try:
            con.execute("BEGIN")
            # executescript ferait un COMMIT implicite : on exécute instruction par instruction.
            for stmt in _split_sql(sql):
                con.execute(stmt)
            con.execute("INSERT INTO schema_migrations VALUES (?,?,?,?)", (version, name, checksum, utc_now_iso()))
            con.execute("COMMIT")
        except Exception as e:
            con.execute("ROLLBACK")
            raise MigrationError(f"échec de la migration {name} (annulée, base inchangée) : {e}") from e
        done.append(name)
    return done


def _split_sql(sql: str) -> list[str]:
    # shortcut: découpe naïve sur ';' — interdit les ';' dans les littéraux et les triggers des migrations.
    lines = [l for l in sql.splitlines() if not l.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def record_versions(con: sqlite3.Connection) -> str:
    v = versions_snapshot()
    h = sha256_json(v)
    con.execute("INSERT OR IGNORE INTO engine_versions VALUES (?,?,?)", (h, json.dumps(v), utc_now_iso()))
    return h


def snapshot_config(con: sqlite3.Connection, kind: str, config: dict) -> str:
    h = sha256_json(config)
    con.execute("INSERT OR IGNORE INTO configuration_snapshots VALUES (?,?,?,?)",
                (h, kind, json.dumps(config, sort_keys=True), utc_now_iso()))
    return h


def audit(con: sqlite3.Connection, event: str, subject_id: str | None = None,
          correlation_id: str | None = None, **payload) -> None:
    con.execute("INSERT INTO audit_events (ts, kind, correlation_id, subject_id, payload_json) VALUES (?,?,?,?,?)",
                (utc_now_iso(), event, correlation_id, subject_id, json.dumps(redact(payload), default=str)))
