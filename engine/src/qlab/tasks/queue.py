"""File de tâches persistante avec machine d'états contrôlée."""
from __future__ import annotations

import json
import sqlite3

from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..storage.db import audit

TRANSITIONS: dict[str, set[str]] = {
    "queued": {"validating", "cancelled", "paused"},
    "validating": {"running", "failed", "quarantined", "cancelled"},
    "running": {"completed", "failed", "paused", "cancelled", "quarantined"},
    "paused": {"queued", "cancelled"},
    "failed": {"queued"},  # nouvelle tentative explicite
    "completed": set(),
    "cancelled": set(),
    "quarantined": set(),
}


class IllegalTransition(ValueError):
    pass


def submit(con: sqlite3.Connection, kind: str, payload: dict, priority: int = 0,
           idempotency_key: str | None = None) -> str:
    """Crée une tâche. Une clé d'idempotence déjà connue renvoie la tâche existante."""
    if idempotency_key:
        row = con.execute("SELECT id FROM tasks WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row:
            return row["id"]
    tid = new_id("task")
    now = utc_now_iso()
    con.execute("INSERT INTO tasks (id, kind, state, priority, idempotency_key, payload_json, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)", (tid, kind, "queued", priority, idempotency_key, json.dumps(payload), now, now))
    audit(con, "task.submitted", tid, kind=kind)
    return tid


def get(con: sqlite3.Connection, tid: str) -> dict:
    row = con.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    if row is None:
        raise KeyError(tid)
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json"))
    d["result"] = json.loads(d.pop("result_json")) if d["result_json"] else None
    return d


def transition(con: sqlite3.Connection, tid: str, new_state: str, *, result: dict | None = None,
               error: str | None = None) -> None:
    cur = get(con, tid)["state"]
    if new_state not in TRANSITIONS[cur]:
        raise IllegalTransition(f"transition interdite {cur} → {new_state} pour {tid}")
    # Compare-and-set : protège d'une transition concurrente.
    n = con.execute("UPDATE tasks SET state=?, updated_at=?, result_json=COALESCE(?, result_json), error=COALESCE(?, error), "
                    "attempts=attempts + (CASE WHEN ?='validating' THEN 1 ELSE 0 END) WHERE id=? AND state=?",
                    (new_state, utc_now_iso(), json.dumps(result) if result is not None else None, error,
                     new_state, tid, cur)).rowcount
    if n != 1:
        raise IllegalTransition(f"état de {tid} modifié concurremment")
    audit(con, "task.transition", tid, frm=cur, to=new_state, error=error)


def set_progress(con: sqlite3.Connection, tid: str, progress: float) -> None:
    con.execute("UPDATE tasks SET progress=?, updated_at=? WHERE id=?", (max(0.0, min(1.0, progress)), utc_now_iso(), tid))


def claim_next(con: sqlite3.Connection) -> dict | None:
    row = con.execute("SELECT id FROM tasks WHERE state='queued' ORDER BY priority DESC, created_at LIMIT 1").fetchone()
    if row is None:
        return None
    try:
        transition(con, row["id"], "validating")
    except IllegalTransition:
        return None
    return get(con, row["id"])


def recover_interrupted(con: sqlite3.Connection) -> list[str]:
    """Au démarrage : les tâches 'running'/'validating' d'un processus mort repassent en pause.

    Elles reprennent depuis leur dernier checkpoint lorsqu'elles sont remises en file.
    """
    ids = [r["id"] for r in con.execute("SELECT id FROM tasks WHERE state IN ('running','validating')")]
    for tid in ids:
        con.execute("UPDATE tasks SET state='paused', updated_at=? WHERE id=?", (utc_now_iso(), tid))
        audit(con, "task.recovered_as_paused", tid)
    return ids


def list_tasks(con: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = con.execute("SELECT id, kind, state, priority, progress, attempts, error, created_at, updated_at "
                       "FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]
