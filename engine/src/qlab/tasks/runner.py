"""Exécution des tâches : validation, exécution, résultat ou échec diagnostiqué."""
from __future__ import annotations

import traceback

from . import queue

HANDLERS: dict = {}


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


def execute(lab, task: dict) -> dict:
    """Exécute une tâche déjà réclamée (état 'validating')."""
    tid = task["id"]
    fn = HANDLERS.get(task["kind"])
    if fn is None:
        queue.transition(lab.con, tid, "quarantined", error=f"type de tâche inconnu : {task['kind']}")
        return queue.get(lab.con, tid)
    queue.transition(lab.con, tid, "running")
    try:
        result = fn(lab, task)
    except Exception as e:  # diagnostic conservé ; la tâche n'est jamais marquée réussie
        lab.log.error("task.failed", correlation_id=tid, kind=task["kind"], error=repr(e),
                      trace=traceback.format_exc()[-4000:])
        if queue.get(lab.con, tid)["state"] == "running":
            queue.transition(lab.con, tid, "failed", error=f"{type(e).__name__}: {e}")
        return queue.get(lab.con, tid)
    if queue.get(lab.con, tid)["state"] == "running":  # pause/annulation demandée entre-temps : on la respecte
        queue.transition(lab.con, tid, "completed", result=result)
    return queue.get(lab.con, tid)


def run_next(lab) -> dict | None:
    t = queue.claim_next(lab.con)
    return execute(lab, t) if t else None


def resume(lab, tid: str) -> None:
    """Remet une tâche en pause dans la file : elle repartira de son dernier checkpoint."""
    queue.transition(lab.con, tid, "queued")


@handler("campaign")
def _campaign(lab, task):
    from ..evolution.campaign import run_task
    return run_task(lab, task)
