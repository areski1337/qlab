"""Planification : campagnes et imports MT5 récurrents (une fois, chaque jour, chaque semaine).

Le worker appelle `tick` à chaque tour : une planification échue soumet une tâche ordinaire (file, reprise,
journaux inchangés) puis avance à sa prochaine échéance. Un import planifié recharge l'historique depuis sa date
de début jusqu'à maintenant : une nouvelle version de dataset n'est créée que si le contenu a changé.
"""
from __future__ import annotations

import datetime as dt
import json

from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from . import queue

STEP = {"daily": dt.timedelta(days=1), "weekly": dt.timedelta(days=7)}


def _parse(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def add(con, name: str, kind: str, payload: dict, every: str, first_run_utc: str) -> dict:
    if kind not in ("campaign", "import_mt5"):
        raise ValueError(f"type de planification inconnu : {kind}")
    if every not in ("once", "daily", "weekly"):
        raise ValueError(f"récurrence inconnue : {every}")
    sid = new_id("sched")
    con.execute("INSERT INTO schedules (id, name, kind, payload_json, every, next_run_utc, created_at) VALUES (?,?,?,?,?,?,?)",
                (sid, name, kind, json.dumps(payload), every, _parse(first_run_utc).isoformat(), utc_now_iso()))
    return {"id": sid}


def tick(lab, now: dt.datetime | None = None) -> list[str]:
    """Soumet les planifications échues ; retourne les identifiants de tâches créées."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for r in lab.con.execute("SELECT * FROM schedules WHERE enabled=1 AND next_run_utc <= ?", (now.isoformat(),)).fetchall():
        p, err, tid = json.loads(r["payload_json"]), None, None
        try:
            if r["kind"] == "campaign":
                from ..evolution import campaign
                _, tid = campaign.create(lab, {**p, "name": f"{p.get('name', r['name'])} · {now:%Y-%m-%d %H:%M}"})
            else:
                tid = queue.submit(lab.con, "import_mt5", {**p, "to": now.replace(tzinfo=None).isoformat(timespec="seconds")},
                                   idempotency_key=f"sched:{r['id']}:{now:%Y%m%d%H%M}")
            out.append(tid)
        except Exception as e:  # une planification invalide est désactivée et l'erreur conservée, le worker continue
            err = f"{type(e).__name__}: {e}"
        nxt = _parse(r["next_run_utc"])
        while r["every"] in STEP and nxt <= now:
            nxt += STEP[r["every"]]
        lab.con.execute("UPDATE schedules SET last_run_utc=?, last_task_id=?, last_error=?, next_run_utc=?, enabled=? WHERE id=?",
                        (now.isoformat(), tid, err, nxt.isoformat(), int(r["every"] != "once" and err is None), r["id"]))
    return out
