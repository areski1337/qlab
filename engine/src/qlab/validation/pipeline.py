"""Avancement contrôlé des statuts de validation (preuves + critères enregistrés).

unverified → screened → historically_tested → robustness_tested → oos_evaluated
Un échec à une étape fait passer la révision en `rejected` (preuve conservée).
Les étapes MT5 (reference_matched, mt5_validated) et démo sont gérées par les
modules mql5/ et demo/ : jamais ici.
"""
from __future__ import annotations

import math
import statistics

from ..genome import store as gstore
from . import protocol as proto, robustness

# alpha : risque de faux positif visé pour la décision OOS, corrigé (Šidák) par le nombre de révisions déjà
# évaluées sur le segment oos de la série : alpha_eff = 1 - (1 - alpha)^(1/m).
OOS_CRITERIA = {"min_trades": 15, "expectancy_positive": True, "profit_factor_min": 1.0, "alpha": 0.05,
                "multiplicity": "sidak"}


def mean_r_pvalue(r: list[float]) -> tuple[float | None, float | None]:
    """Test t unilatéral (moyenne des R > 0). p via l'approximation normale de Student (Abramowitz-Stegun 26.7.8)."""
    n = len(r)
    if n < 3:
        return None, None
    sd = statistics.stdev(r)
    if sd == 0:
        return (None, 0.0) if statistics.fmean(r) > 0 else (None, 1.0)
    t = statistics.fmean(r) / sd * math.sqrt(n)
    df = n - 1
    z = t * (1 - 1 / (4 * df)) / math.sqrt(1 + t * t / (2 * df))
    return t, 1 - statistics.NormalDist().cdf(z)


def oos_decision(metrics: dict, r: list[float], m: int, c: dict = OOS_CRITERIA) -> dict:
    """Critère OOS : seuils de base + test de la moyenne des R au seuil corrigé de la multiplicité m >= 1."""
    t, p = mean_r_pvalue(r)
    m = max(1, int(m))
    alpha_eff = 1 - (1 - c["alpha"]) ** (1 / m)
    base = (metrics["n_trades"] >= c["min_trades"] and (metrics["expectancy"] or 0) > 0
            and (metrics["profit_factor"] is None or metrics["profit_factor"] > c["profit_factor_min"]))
    return {"pass": bool(base and p is not None and p <= alpha_eff), "base_pass": bool(base), "t": t, "p_value": p,
            "multiplicity": m, "alpha": c["alpha"], "alpha_effective": alpha_eff}


def advance(lab, rev_id: str, cache, costs: dict, risk, protocol: dict = proto.DEFAULT_PROTOCOL,
            campaign_id: str | None = None, criteria: dict = robustness.DEFAULT_CRITERIA,
            stop_at: str = "oos_evaluated", seed: int = 0, transfer_caches: dict | None = None) -> dict:
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
        seg = proto.segments_for(lab, cache.bars, protocol)
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
        rep = robustness.run_suite(lab, rev, cache, costs, risk, protocol, campaign_id, criteria, seed, transfer_caches)
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
        trades = (ev.get("result") or lab.store.get_json(ev["trades_artifact"]))["trades"]
        n_oos = proto.segment_usage(lab, cache.bars.version_id, "oos")
        dec = oos_decision(m, [t["pnl"] / t["risk_amount"] for t in trades], n_oos)  # R net : commission et swap compris
        evidence = {"oos_evaluation": ev["id"], "oos_trades_artifact": ev["trades_artifact"],
                    "oos_multiplicity": n_oos, "oos_test": dec}
        if dec["pass"]:
            gstore.set_status(con, rev_id, "oos_evaluated", OOS_CRITERIA, evidence)
            log.append({"to": "oos_evaluated", "oos_multiplicity": n_oos, "p_value": dec["p_value"]})
        else:
            why = ("échec hors échantillon" if not dec["base_pass"] else
                   f"hors échantillon non significatif (p={dec['p_value']:.3g} > seuil corrigé "
                   f"{dec['alpha_effective']:.3g} pour {n_oos} révision(s) évaluée(s) sur ce segment)"
                   if dec["p_value"] is not None else "hors échantillon : test non calculable")
            reject(why, evidence)
    return {"status": status(), "log": log}
