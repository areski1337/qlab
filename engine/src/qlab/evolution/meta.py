"""Amélioration contrôlée des méthodes de recherche (section 18).

Une expérience compare une configuration de campagne de base et une variante
sur plusieurs graines, avec hypothèse et critères déclarés AVANT exécution.
Seuls des paramètres de MÉTHODE peuvent varier (liste blanche) : contraintes,
coûts, protocole et limites de risque sont exclus. Une variante gagnante n'est
jamais appliquée automatiquement : elle peut être promue dans le canal
« experimental » (utilisé seulement par les campagnes qui le demandent), avec
historique et retour arrière.
"""
from __future__ import annotations

import json
import math
import time

from ..core.hashing import sha256_json
from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..storage.db import audit
from ..tasks import queue
from . import campaign as camp

METHOD_KEYS = {"population", "generations_per_tribe", "merge_generations", "crossover_rate", "tribes",
               "stagnation_generations", "specialization_session", "sides"}
METRICS = {
    "best_validation_sharpe": lambda r: max((f["validation"].get("sharpe") or -1e9 for f in r["front"]), default=None),
    "front_size": lambda r: len(r["front"]),
    "final_behavioral_diversity": lambda r: (r["history"][-1]["diversity"]["behavioral"] if r["history"] else None),
    "evaluations": lambda r: r["evaluations"],
}


def validate_spec(spec: dict) -> None:
    for side in ("baseline", "variant"):
        bad = set(spec[side]) - METHOD_KEYS
        if bad:
            raise ValueError(f"{side} : clés hors méthode interdites {sorted(bad)} (garde-fous non modifiables)")
    if spec["metric"] not in METRICS:
        raise ValueError(f"métrique inconnue {spec['metric']} ({sorted(METRICS)})")
    if len(spec["seeds"]) < 3:
        raise ValueError("au moins 3 graines")
    if spec["direction"] not in ("higher", "lower"):
        raise ValueError("direction : higher | lower")


def sign_test_p(wins: int, losses: int) -> float:
    """p-valeur unilatérale du test des signes (H0 : P(gain)=0,5), égalités exclues."""
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / 2 ** n


def create(lab, hypothesis: str, spec: dict) -> tuple[str, str]:
    """spec = {base: cfg commune (dataset, coûts…), baseline: {...}, variant: {...}, seeds: [...],
    metric, direction, min_win_ratio, max_p}"""
    spec = {"min_win_ratio": 0.7, "max_p": 0.1, **spec}
    validate_spec(spec)
    # la méthode ne se choisit pas sur la série qu'elle servira à explorer (validation lue, N du DSR gonflé)
    from ..validation.protocol import dataset_of
    used = lab.con.execute(
        "SELECT 1 FROM campaigns c JOIN dataset_versions v ON v.id=json_extract(c.config_json, '$.dataset_version_id') "
        "WHERE v.dataset_id=? AND json_extract(c.config_json, '$.parent_task_id') IS NULL LIMIT 1",
        (dataset_of(lab, spec["base"].get("dataset_version_id")),)).fetchone()
    if used:
        raise ValueError("série déjà utilisée par une campagne de recherche : utiliser une série dédiée aux expériences "
                         "(autre instrument ou données synthétiques)")
    eid = new_id("exp")
    tid = queue.submit(lab.con, "engine_experiment", {"experiment_id": eid})
    lab.con.execute("INSERT INTO engine_experiments (id, hypothesis, spec_json, spec_sha256, task_id, created_at) "
                    "VALUES (?,?,?,?,?,?)", (eid, hypothesis, json.dumps(spec), sha256_json(spec), tid, utc_now_iso()))
    audit(lab.con, "engine_experiment.created", eid, hypothesis=hypothesis, spec_sha256=sha256_json(spec))
    return eid, tid


def run_task(lab, task: dict) -> dict:
    eid = task["payload"]["experiment_id"]
    row = lab.con.execute("SELECT * FROM engine_experiments WHERE id=?", (eid,)).fetchone()
    spec = json.loads(row["spec_json"])
    rows = []
    for seed in spec["seeds"]:
        pair = {}
        for arm in ("baseline", "variant"):
            cfg = {**spec["base"], **spec[arm], "seed": seed, "name": f"{eid}:{arm}:{seed}", "parent_task_id": task["id"]}
            t0 = time.time()
            cid, res = _run_campaign_inline(lab, cfg)
            pair[arm] = {"campaign": cid, "value": METRICS[spec["metric"]](res), "seconds": round(time.time() - t0, 1)}
        rows.append({"seed": seed, **pair})
    sgn = 1 if spec["direction"] == "higher" else -1
    wins = sum(1 for r in rows if r["variant"]["value"] is not None and r["baseline"]["value"] is not None
               and sgn * (r["variant"]["value"] - r["baseline"]["value"]) > 0)
    losses = sum(1 for r in rows if r["variant"]["value"] is not None and r["baseline"]["value"] is not None
                 and sgn * (r["variant"]["value"] - r["baseline"]["value"]) < 0)
    p = sign_test_p(wins, losses)
    ratio = wins / len(rows)
    verdict = ("promote_candidate" if ratio >= spec["min_win_ratio"] and p <= spec["max_p"] else
               "reject" if wins <= losses else "inconclusive")
    out = {"rows": rows, "wins": wins, "losses": losses, "win_ratio": ratio, "sign_test_p": p, "verdict": verdict,
           "note": "verdict = candidat à promotion uniquement ; aucune modification n'est appliquée automatiquement"}
    lab.con.execute("UPDATE engine_experiments SET results_json=?, verdict=? WHERE id=?", (json.dumps(out), verdict, eid))
    audit(lab.con, "engine_experiment.completed", eid, verdict=verdict, p=p)
    return out


def _run_campaign_inline(lab, cfg: dict) -> tuple[str, dict]:
    cid, tid = camp.create(lab, cfg)
    queue.transition(lab.con, tid, "validating")
    queue.transition(lab.con, tid, "running")
    res = camp.run_task(lab, queue.get(lab.con, tid))
    if "stopped" in res:
        queue.transition(lab.con, tid, "cancelled")  # sous-campagne abandonnée : l'expérience repartira de zéro
        raise RuntimeError(f"sous-campagne {cid} interrompue ({res['stopped']}) : expérience invalide")
    queue.transition(lab.con, tid, "completed", result=res)
    return cid, res


def experimental_overrides(lab) -> dict:
    r = lab.con.execute("SELECT overrides_json FROM engine_promotions ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(r[0]) if r else {}


def promote(lab, eid: str) -> dict:
    row = lab.con.execute("SELECT * FROM engine_experiments WHERE id=?", (eid,)).fetchone()
    if row is None or row["verdict"] != "promote_candidate":
        raise PermissionError("seule une expérience au verdict « promote_candidate » peut être promue")
    variant = json.loads(row["spec_json"])["variant"]
    prev = experimental_overrides(lab)
    new = {**prev, **variant}
    lab.con.execute("INSERT INTO engine_promotions (experiment_id, channel, overrides_json, previous_json, action, ts) "
                    "VALUES (?,?,?,?,?,?)", (eid, "experimental", json.dumps(new), json.dumps(prev), "promote", utc_now_iso()))
    audit(lab.con, "engine.promoted_experimental", eid, overrides=new)
    return new


def rollback(lab) -> dict:
    r = lab.con.execute("SELECT * FROM engine_promotions ORDER BY id DESC LIMIT 1").fetchone()
    if r is None:
        return {}
    prev = json.loads(r["previous_json"])
    lab.con.execute("INSERT INTO engine_promotions (experiment_id, channel, overrides_json, previous_json, action, ts) "
                    "VALUES (?,?,?,?,?,?)", (r["experiment_id"], "experimental", json.dumps(prev), r["overrides_json"],
                                             "rollback", utc_now_iso()))
    audit(lab.con, "engine.rollback_experimental", r["experiment_id"], overrides=prev)
    return prev
