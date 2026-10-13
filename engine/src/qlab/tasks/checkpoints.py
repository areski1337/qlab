"""Checkpoints atomiques : un état sérialisé dans le stockage d'artefacts + une ligne SQLite."""
from __future__ import annotations

import sqlite3

from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..storage.artifacts import ArtifactStore


def save(con: sqlite3.Connection, store: ArtifactStore, task_id: str, state: dict) -> int:
    con.execute("BEGIN IMMEDIATE")
    try:
        sha = store.put_json(state, kind="checkpoint", meta={"task_id": task_id})
        seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM checkpoints WHERE task_id=?", (task_id,)).fetchone()[0]
        con.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?)", (new_id("ckpt"), task_id, seq, sha, utc_now_iso()))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return seq


def latest(con: sqlite3.Connection, store: ArtifactStore, task_id: str) -> dict | None:
    row = con.execute("SELECT artifact_sha256 FROM checkpoints WHERE task_id=? ORDER BY seq DESC LIMIT 1",
                      (task_id,)).fetchone()
    return store.get_json(row["artifact_sha256"]) if row else None
