"""Budget d'essais (avant campagne) et entonnoir de validation (après) : rendre les rejets DSR prévisibles et lisibles.

Le Deflated Sharpe Ratio compare le Sharpe retenu au maximum attendu par chance parmi N essais (sr0), qui croît
avec N. Avant une campagne, on estime N (essais déjà faits sur la série + essais prévus), sr0 et le Sharpe annualisé
à atteindre pour DSR >= seuil. La dispersion des Sharpe des essais est mesurée sur la série si au moins 30 essais
existent ; sinon elle est SUPPOSÉE (écart-type annualisé 1,0), ce qui est indiqué dans la réponse.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter

import numpy as np

from ..core.timeutil import ts_to_iso
from . import protocol as proto
from .robustness import EULER, trial_sharpes

ASSUMED_TRIAL_SR_SD_ANNUAL = 1.0


def required_sharpe(n_trials: int, sr_sd_annual: float, t_days: int, dsr_min: float = 0.90) -> dict:
    """sr0 (maximum attendu par chance) et Sharpe annualisé requis pour DSR >= dsr_min (rendements gaussiens)."""
    k = math.sqrt(252)
    nd = statistics.NormalDist()
    n = max(2, int(n_trials))
    sd = sr_sd_annual / k
    sr0 = sd * ((1 - EULER) * nd.inv_cdf(1 - 1 / n) + EULER * nd.inv_cdf(1 - 1 / (n * math.e)))
    req = sr0 + nd.inv_cdf(dsr_min) / math.sqrt(max(1, t_days - 1))
    return {"sr0_annual": sr0 * k, "required_sharpe_annual": req * k}


def estimate(lab, dataset_version_id: str, planned_trials: int, dsr_min: float = 0.90) -> dict:
    from ..data.dataset import load_bars
    from ..features.sessions import trading_day
    bars = load_bars(lab, dataset_version_id, verify=False)
    seg = proto.segments_for(lab, bars, proto.DEFAULT_PROTOCOL, freeze=False)  # une estimation ne fige rien
    a, b = seg["train"]
    days = trading_day(np.array([int(bars.ts[a]), int(bars.ts[b - 1])]))
    t_days = int(np.sum((np.arange(days[0], days[1] + 1) + 3) % 7 < 5))
    past = [s for s in trial_sharpes(lab, dataset_version_id) if s is not None and math.isfinite(s)]
    measured = len(past) >= 30
    sd = statistics.pstdev(past) if measured else ASSUMED_TRIAL_SR_SD_ANNUAL
    n = len(past) + max(0, int(planned_trials))
    out = {"planned_trials": int(planned_trials), "previous_trials_on_series": len(past), "n_trials_total": n,
           "train_days": t_days, "trial_sharpe_sd_annual": sd,
           "sd_source": "mesurée sur la série" if measured else "supposée (moins de 30 essais sur la série)",
           "dsr_min": dsr_min, **required_sharpe(n, sd, t_days, dsr_min)}
    frozen = lab.con.execute("SELECT 1 FROM segment_boundaries WHERE dataset_id=? AND protocol_sha256=?",
                             (proto.dataset_of(lab, dataset_version_id), proto.protocol_sha(proto.DEFAULT_PROTOCOL))).fetchone()
    out["segments"] = {"frozen": frozen is not None,
                       **{f"{k}_end": ts_to_iso(int(bars.ts[seg[k][1] - 1])) if seg[k][1] > seg[k][0] else None
                          for k in ("train", "validation", "oos", "final")}}
    out["note"] = ("Estimation : N réel plus faible si des candidats sont identiques (dédoublonnés). Chaque essai "
                   "supplémentaire sur cette série relève le seuil de toutes les campagnes futures.")
    return out


def funnel(lab, campaign_id: str) -> dict:
    """Révisions de la campagne par statut, causes de rejet et critère de robustesse le plus souvent en échec."""
    con = lab.con
    by_status = Counter(r[0] for r in con.execute("SELECT status FROM genome_revisions WHERE campaign_id=?", (campaign_id,)))
    reasons, failed_checks = Counter(), Counter()
    for crit, ev in con.execute(
            "SELECT t.criteria_json, t.evidence_json FROM status_transitions t JOIN genome_revisions g ON g.id=t.revision_id "
            "WHERE g.campaign_id=? AND t.to_status='rejected'", (campaign_id,)):
        reason = (json.loads(crit).get("reason") or "inconnue")
        reasons[reason.split(" :")[0].split(" (")[0]] += 1
        sha = json.loads(ev).get("robustness_report")
        if sha:
            rep = lab.store.get_json(sha)
            for k, c in rep.get("checks", {}).items():
                if c.get("pass") is False:
                    failed_checks[k] += 1
    ladder = ["unverified", "screened", "historically_tested", "robustness_tested", "oos_evaluated",
              "reference_matched", "mt5_validated", "demo_observed"]
    reached = {s: sum(n for st, n in by_status.items() if st in ladder[i:]) for i, s in enumerate(ladder)}
    dominant = failed_checks.most_common(1)[0][0] if failed_checks else (reasons.most_common(1)[0][0] if reasons else None)
    advice = {
        "deflated_sharpe": "trop d'essais pour l'avantage trouvé : réduire l'espace de recherche (bases, tribus) ou "
                           "allonger l'historique",
        "cost_stress_x1.5": "avantage trop mince face aux coûts : viser des horizons plus longs ou moins de transactions",
        "random_baseline": "les sorties expliquent le résultat plus que les entrées : revoir les conditions d'entrée",
        "sensitivity": "pic de paramètres fragile : préférer des règles plus simples",
        "walk_forward": "avantage concentré sur une période",
        "walk_forward_reopt": "les paramètres ne se transfèrent pas d'une période à la suivante",
        "mc_p95_max_dd": "drawdown trop élevé : réduire le risque par transaction",
        "min_trades": "trop peu de transactions : élargir les conditions ou l'historique",
    }
    return {"campaign_id": campaign_id, "by_status": dict(by_status), "reached": reached,
            "rejection_reasons": dict(reasons.most_common()), "failed_robustness_checks": dict(failed_checks.most_common()),
            "dominant_cause": dominant, "advice": advice.get(dominant)}
