"""Avancement contrôlé des statuts de validation (preuves + critères enregistrés).

unverified → screened → historically_tested → robustness_tested → oos_evaluated
Un échec à une étape fait passer la révision en `rejected` (preuve conservée).
Les étapes MT5 (reference_matched, mt5_validated) et démo sont gérées par les
modules mql5/ et demo/ : jamais ici.
"""
from __future__ import annotations

from ..genome import store as gstore
from . import protocol as proto, robustness

OOS_CRITERIA = {"min_trades": 15, "expectancy_positive": True, "profit_factor_min": 1.0}


def advance(lab, rev_id: str, cache, costs: dict, risk, protocol: dict = proto.DEFAULT_PROTOCOL,
            campaign_id: str | None = None, criteria: dict = robustness.DEFAULT_CRITERIA,
            stop_at: str = "oos_evaluated", seed: int = 0) -> dict:
    con = lab.con
    log = []

    def status():
        return gstore.get(con, rev_id)["status"]

    def reject(reason, evidence):
        gstore.set_status(con, rev_id, "rejected", {"reason": reason}, evidence)
        log.append({"to": "rejected", "reason": reason})

    rev = gstore.get(con, rev_id)
    if rev["status"] == "unverified":
        ev = proto.evaluate(lab, rev, cache, costs, risk, "train", protocol, campaign_id)
        n = ev["metrics"]["n_trades"]
        if n >= max(5, criteria["min_trades"] // 2):
            gstore.set_status(con, rev_id, "screened", {"min_trades_train": criteria["min_trades"] // 2},
                              {"train_evaluation": ev["id"]})
            log.append({"to": "screened"})
        else:
            reject(f"trop peu de trades en train ({n})", {"train_evaluation": ev["id"]})
            return {"status": status(), "log": log}
    if stop_at == "screened":
        return {"status": status(), "log": log}

    if status() == "screened":
        seg = proto.segments(len(cache.bars), protocol)
        w = (seg["train"][0], seg["validation"][1])
        ev = proto.evaluate(lab, rev, cache, costs, risk, "research", protocol, campaign_id, window=w, store_trades=True)
        n = ev["metrics"]["n_trades"]
        if n >= criteria["min_trades"]:
            gstore.set_status(con, rev_id, "historically_tested", {"min_trades": criteria["min_trades"],
                                                                   "window": "train+validation"},
                              {"evaluation": ev["id"], "trades_artifact": ev["trades_artifact"]})
            log.append({"to": "historically_tested"})
        else:
            reject(f"trop peu de trades train+validation ({n})", {"evaluation": ev["id"]})
            return {"status": status(), "log": log}
    if stop_at == "historically_tested":
        return {"status": status(), "log": log}

    if status() == "historically_tested":
        rep = robustness.run_suite(lab, rev, cache, costs, risk, protocol, campaign_id, criteria, seed)
        sha = lab.store.put_json(rep, kind="robustness_report", meta={"revision": rev_id})
        failed = [k for k, c in rep["checks"].items() if c["pass"] is not True]
        if rep["passed"]:
            gstore.set_status(con, rev_id, "robustness_tested", criteria, {"robustness_report": sha})
            log.append({"to": "robustness_tested", "report": sha})
        else:
            reject(f"robustesse insuffisante : {failed}", {"robustness_report": sha})
            return {"status": status(), "log": log, "robustness_report": sha}
    if stop_at == "robustness_tested":
        return {"status": status(), "log": log}

    if status() == "robustness_tested":
        ev = proto.evaluate(lab, rev, cache, costs, risk, "oos", protocol, campaign_id, store_trades=True)
        m = ev["metrics"]
        n_oos = con.execute("SELECT COUNT(DISTINCT revision_id) FROM evaluations WHERE segment='oos' AND "
                            "dataset_version_id=?", (cache.bars.version_id,)).fetchone()[0]
        ok = (m["n_trades"] >= OOS_CRITERIA["min_trades"] and (m["expectancy"] or 0) > 0
              and (m["profit_factor"] is None or m["profit_factor"] > OOS_CRITERIA["profit_factor_min"]))
        evidence = {"oos_evaluation": ev["id"], "oos_trades_artifact": ev["trades_artifact"],
                    "oos_multiplicity": n_oos}
        if ok:
            gstore.set_status(con, rev_id, "oos_evaluated", OOS_CRITERIA, evidence)
            log.append({"to": "oos_evaluated", "oos_multiplicity": n_oos})
        else:
            reject("échec hors échantillon", evidence)
    return {"status": status(), "log": log}
