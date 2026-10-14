"""Tests de robustesse sur la fenêtre de recherche (train + validation).

Aucun de ces tests n'est une preuve suffisante de robustesse ; ils sont
complémentaires et leurs hypothèses sont rappelées dans le rapport.

- walk_forward : stabilité sur des fenêtres successives, paramètres FIGÉS
  (pas de ré-optimisation par fenêtre : c'est un test de stabilité, pas un
  walk-forward d'optimisation).
- walk_forward_reopt : paramètres ré-optimisés par pli, structure figée.
  Les deux walk-forward s'exécutent DANS la fenêtre train+validation où la
  structure a été découverte et sélectionnée : ce sont des tests de stabilité
  in-sample (rapportés `in_sample: True`), jamais une preuve hors échantillon.
- sensitivity : voisins paramétriques (±1 pas entier, ×0,8/×1,2 réel).
- cost_stress : spread effectif (barres, plancher ou fixe) multiplié par 1,5
  et 2, glissement (+25 % du spread médian) et commission ajoutés.
- monte_carlo : bootstrap des PnL de trades (i.i.d. supposé : ignore
  l'autocorrélation) et permutations d'ordre (drawdown seulement).
- random_baseline : entrées aléatoires de même fréquence et même part long,
  mêmes sorties/risque ; p-valeur empirique de l'expectancy.
- deflated_sharpe : Bailey & López de Prado (2014), sur la fenêtre train ;
  N essais = toutes les révisions évaluées en train sur la même série
  (toutes campagnes, relances et versions du dataset confondues) ; suppose des
  essais indépendants (N effectif surestimé quand les candidats sont corrélés).
Ordre d'exécution : du moins coûteux au plus coûteux ; dès qu'un critère
éliminatoire échoue, les tests coûteux restants sont marqués `skipped`.
"""
from __future__ import annotations

import copy
import math
import statistics

import numpy as np

from ..backtest import engine
from ..features import REGISTRY
from ..genome import model
from ..metrics.core import compute
from . import protocol as proto

DEFAULT_CRITERIA = {
    "min_trades": 30,
    "wf_positive_folds_ratio": 0.5,
    "wfo_positive_folds_ratio": 0.5,
    "sensitivity_positive_ratio": 0.6,
    "cost_stress_x15_expectancy_positive": True,
    "mc_p95_max_dd_pct": 35.0,
    "random_baseline_p_max": 0.05,
    "dsr_min": 0.90,
}
EULER = 0.5772156649


def _run(genome, cache, costs, risk, window, sig=None):
    res = engine.run(genome, cache, costs, risk, start=window[0], stop=window[1], signals_override=sig)
    return res, compute(res, (int(cache.bars.ts[window[0]]), int(cache.bars.ts[window[1] - 1])))


def _summ(m):
    return {k: m.get(k) for k in ("n_trades", "net_profit", "expectancy", "expectancy_r", "profit_factor",
                                  "sharpe", "max_dd_pct", "win_rate")}


def _wf_end(cache, protocol, seg):
    return (seg or proto.segments(len(cache.bars), protocol))["validation"][1]


def walk_forward(g, cache, costs, risk, protocol, seg: dict | None = None) -> dict:
    folds = []
    for f in proto.walk_forward(len(cache.bars), protocol, _wf_end(cache, protocol, seg)):
        _, m = _run(g, cache, costs, risk, f["test"])
        folds.append({"fold": f["fold"], "window": f["test"], **_summ(m)})
    pos = [f for f in folds if (f["expectancy"] or 0) > 0]
    return {"folds": folds, "positive_ratio": len(pos) / len(folds) if folds else None, "in_sample": True}


def walk_forward_reopt(g, cache, costs, risk, protocol, n_trials: int = 24, seed: int = 0,
                       seg: dict | None = None) -> dict:
    """Walk-forward d'optimisation : structure figée ; paramètres/constantes/sorties ré-optimisés sur la fenêtre
    d'apprentissage (ancrée) de chaque pli, jeu retenu = meilleur Sharpe avec >= 10 trades, évalué sur le pli suivant.
    WFE = Sharpe moyen hors pli / Sharpe moyen d'apprentissage des jeux retenus (None si non calculable)."""
    import random
    from ..evolution import operators as ops
    rng = random.Random(seed)
    htfs = tuple(sorted(cache.context))
    folds = []
    for f in proto.walk_forward(len(cache.bars), protocol, _wf_end(cache, protocol, seg)):
        cands = [g]
        tries = 0
        while len(cands) < n_trials and tries < n_trials * 4:
            tries += 1
            r = ops.mutate(rng, rng.choice(cands), rng.choice(["param", "const", "exit"]), htfs)
            if r:
                cands.append(r[0])
        best, best_m = g, None
        for c in cands:
            _, m = _run(c, cache, costs, risk, f["fit"])
            if m["n_trades"] >= 10 and m["sharpe"] is not None and (best_m is None or m["sharpe"] > best_m["sharpe"]):
                best, best_m = c, m
        _, mt = _run(best, cache, costs, risk, f["test"])
        folds.append({"fold": f["fold"], "fit": f["fit"], "test": f["test"], "candidates": len(cands),
                      "chosen_is_original": model.semantic_hash(best) == model.semantic_hash(g),
                      "fit_sharpe": best_m["sharpe"] if best_m else None, **_summ(mt)})
    pos = [x for x in folds if (x["expectancy"] or 0) > 0]
    fs = [x["fit_sharpe"] for x in folds if x["fit_sharpe"] is not None]
    ts = [x["sharpe"] for x in folds if x["sharpe"] is not None]
    wfe = (float(np.mean(ts)) / float(np.mean(fs))) if fs and ts and np.mean(fs) > 0 else None
    return {"folds": folds, "positive_ratio": len(pos) / len(folds) if folds else None, "wfe": wfe,
            "oos_net_total": float(sum(x["net_profit"] or 0 for x in folds)), "trials_per_fold": n_trials, "seed": seed,
            "in_sample": True,
            "note": "plis dans train+validation, où la structure a été découverte : stabilité in-sample, pas une preuve OOS"}


def neighbors(g: dict) -> list[tuple[str, dict]]:
    out = []
    for side in ("long", "short"):
        for n in model.iter_nodes(g["entry"][side]):
            rs = [n["left"], n["right"]] if n["op"] == "compare" else [n["ref"]] if n["op"] == "event" else []
            for ri, r in enumerate(rs):
                if "feature" not in r:
                    if n["op"] == "compare" and "const" in r:
                        for f in (0.9, 1.1):
                            h = copy.deepcopy(g)
                            node = next(x for x in model.iter_nodes(h["entry"][side]) if x["id"] == n["id"])
                            node["right"]["const"] = round(r["const"] * f, 6) if r["const"] else (0.1 if f > 1 else -0.1)
                            out.append((f"{n['id']}.const×{f}", h))
                    continue
                for k, p in REGISTRY[r["feature"]].params.items():
                    if p.kind == "choice":
                        continue
                    steps = [-1, 1] if p.kind == "int" else [0.8, 1.2]
                    for s in steps:
                        h = copy.deepcopy(g)
                        node = next(x for x in model.iter_nodes(h["entry"][side]) if x["id"] == n["id"])
                        tgt = ([node["left"], node["right"]] if node["op"] == "compare" else [node["ref"]])[ri]
                        v = tgt["params"][k]
                        tgt["params"][k] = v + s if p.kind == "int" else round(v * s, 6)
                        out.append((f"{n['id']}.{r['feature']}.{k}{'+' if s in (1, 1.2) else '-'}", h))
    ex = g["exit"]
    for path, f in (("stop.mult", (0.8, 1.2)), ("target.rr", (0.8, 1.2))):
        a, b = path.split(".")
        if ex.get(a) and b in ex[a]:
            for s in f:
                h = copy.deepcopy(g)
                h["exit"][a][b] = round(ex[a][b] * s, 6)
                out.append((f"exit.{path}×{s}", h))
    return [(name, h) for name, h in out if not model.validate(h)]


def sensitivity(g, cache, costs, risk, window) -> dict:
    rows = []
    for name, h in neighbors(g):
        _, m = _run(h, cache, costs, risk, window)
        rows.append({"variant": name, **_summ(m)})
    pos = [r for r in rows if (r["expectancy"] or 0) > 0]
    return {"neighbors": rows, "n": len(rows), "positive_ratio": len(pos) / len(rows) if rows else None}


def cost_stress(g, cache, costs, risk, window) -> dict:
    """Le spread effectif (barres, plancher ou fixe selon le profil) est MULTIPLIÉ : chaque scénario coûte plus que la base."""
    from ..backtest.costs import spread_series
    pt = float(cache.bars.spec["point"])
    scale = float(costs.get("spread_scale", 1.0) or 1.0)
    med = float(np.median(spread_series(cache.bars, costs)[window[0]:window[1]]))
    scen = {
        "spread_x1.5": {**costs, "spread_scale": scale * 1.5},
        "spread_x2": {**costs, "spread_scale": scale * 2},
        "slippage+": {**costs, "slippage_points": costs.get("slippage_points", 0) + max(1, int(round(med * 0.25)))},
        "commission+": {**costs, "commission_per_lot_side": costs.get("commission_per_lot_side", 0) + 3.5},
    }
    out = {}
    for k, c in scen.items():
        _, m = _run(g, cache, c, risk, window)
        out[k] = _summ(m)
    out["_note"] = f"spread effectif médian {med:g} points (point = {pt}) multiplié ×1,5 / ×2"
    return out


def _max_dd(eq0: float, pnl: np.ndarray) -> float:
    eq = eq0 + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[eq0], eq]))[1:]
    return float(((peak - eq) / peak).max() * 100)


def monte_carlo(trades: list[dict], eq0: float, n: int = 1000, seed: int = 0) -> dict:
    pnl = np.array([t["pnl"] for t in trades])
    if len(pnl) < 5:
        return {"available": False, "reason": "moins de 5 trades"}
    rng = np.random.default_rng(seed)
    boot_net, boot_dd, perm_dd = [], [], []
    for _ in range(n):
        s = rng.choice(pnl, len(pnl), replace=True)
        boot_net.append(s.sum())
        boot_dd.append(_max_dd(eq0, s))
        perm_dd.append(_max_dd(eq0, rng.permutation(pnl)))
    q = lambda a: {f"p{p}": float(np.percentile(a, p)) for p in (5, 50, 95)}
    return {"available": True, "iterations": n, "seed": seed, "bootstrap_net": q(boot_net),
            "bootstrap_max_dd_pct": q(boot_dd), "permutation_max_dd_pct": q(perm_dd),
            "prob_net_negative": float(np.mean(np.array(boot_net) < 0)),
            "assumption": "trades i.i.d. (autocorrélation ignorée)"}


def random_baseline(g, cache, costs, risk, window, res_trades, n: int = 100, seed: int = 0) -> dict:
    nt = len(res_trades)
    if nt < 5:
        return {"available": False, "reason": "moins de 5 trades"}
    rng = np.random.default_rng(seed)
    N = len(cache.bars)
    long_share = np.mean([t["dir"] == 1 for t in res_trades])
    a, b = window
    exps = []
    for _ in range(n):
        idx = rng.choice(np.arange(a, b - 1), size=min(nt * 3, b - a - 1), replace=False)
        lg, sh = np.zeros(N, bool), np.zeros(N, bool)
        isl = rng.random(len(idx)) < long_share
        lg[idx[isl]] = True
        sh[idx[~isl]] = True
        res, m = _run(g, cache, costs, risk, window, (lg, sh))
        if m["n_trades"]:
            exps.append(m["expectancy"])
    actual = float(np.mean([t["pnl"] for t in res_trades]))
    exps = np.array(exps)
    p = float((np.sum(exps >= actual) + 1) / (len(exps) + 1))
    return {"available": True, "n": len(exps), "seed": seed, "strategy_expectancy": actual,
            "random_expectancy_p50": float(np.median(exps)), "random_expectancy_p95": float(np.percentile(exps, 95)),
            "p_value": p, "note": "entrées aléatoires (3× le nombre de trades proposés), mêmes sorties et risque"}


def deflated_sharpe(daily_returns_sr_annual: float | None, t_obs: int, skew: float, kurt: float,
                    trial_srs_annual: list[float]) -> dict:
    """DSR sur Sharpe journalier. trial_srs_annual : Sharpe annualisés de tous les essais."""
    trials = [s for s in trial_srs_annual if s is not None and math.isfinite(s)]
    if daily_returns_sr_annual is None or t_obs < 10 or len(trials) < 2:
        return {"available": False, "reason": "données insuffisantes", "n_trials": len(trials)}
    k = math.sqrt(252)
    sr = daily_returns_sr_annual / k
    var = statistics.pvariance([s / k for s in trials])
    N = len(trials)
    nd = statistics.NormalDist()
    sr0 = math.sqrt(var) * ((1 - EULER) * nd.inv_cdf(1 - 1 / N) + EULER * nd.inv_cdf(1 - 1 / (N * math.e)))
    den = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if den <= 0:
        return {"available": False, "reason": "dénominateur non positif (moments extrêmes)"}
    z = (sr - sr0) * math.sqrt(t_obs - 1) / math.sqrt(den)
    return {"available": True, "dsr": nd.cdf(z), "sr_daily": sr, "sr0_daily": sr0, "n_trials": N,
            "t_obs": t_obs, "skew": skew, "kurtosis": kurt,
            "assumption": "essais indépendants : N effectif surestimé si candidats corrélés (DSR alors optimiste "
                          "sur la variance, pessimiste sur N)"}


def daily_moments(res: dict, window_ts) -> tuple[int, float, float]:
    from ..features.sessions import trading_day
    import pandas as pd
    trades = res["trades"]
    d0, d1 = trading_day(np.array([window_ts[0]]))[0], trading_day(np.array([window_ts[1]]))[0]
    days = np.arange(d0, d1 + 1)
    days = days[(days + 3) % 7 < 5]
    if not trades:
        return len(days), 0.0, 3.0
    ex = trading_day(np.array([t["exit_ts"] for t in trades]))
    r = pd.Series([t["pnl"] for t in trades]).groupby(ex).sum().reindex(days, fill_value=0.0).to_numpy()
    r = r / res["initial_equity"]
    sd = r.std()
    if sd == 0:
        return len(r), 0.0, 3.0
    z = (r - r.mean()) / sd
    return len(r), float((z ** 3).mean()), float((z ** 4).mean())


def trial_sharpes(lab, version_id: str | None) -> list[float]:
    """Sharpe en train de toutes les révisions évaluées sur la série (toutes campagnes et versions du dataset),
    une valeur par révision (évaluation la plus récente)."""
    if lab is None or version_id is None:
        return []
    import json
    by_rev: dict[str, float | None] = {}
    for rid, mj in lab.con.execute(
            "SELECT e.revision_id, e.metrics_json FROM evaluations e JOIN dataset_versions v ON v.id=e.dataset_version_id "
            "WHERE e.segment='train' AND v.dataset_id=(SELECT dataset_id FROM dataset_versions WHERE id=?) "
            "ORDER BY e.created_at", (version_id,)):
        by_rev[rid] = json.loads(mj).get("sharpe")
    return list(by_rev.values())


def transfer(g, caches: dict, costs: dict, risk, protocol, lab=None) -> dict:
    """Mêmes règles sur d'autres instruments (fenêtre train+validation de chacun). Informatif, non bloquant :
    l'absence de transfert n'invalide pas une stratégie spécialisée, mais elle est rapportée."""
    out = {}
    for sym, c in caches.items():
        seg = proto.segments_for(lab, c.bars, protocol, freeze=False)  # frontières datées de cette série si figées
        try:
            _, m = _run(g, c, costs, risk, (seg["train"][0], seg["validation"][1]))
            out[sym] = _summ(m)
        except Exception as e:  # coûts inconnus, feature indisponible… : rapporté, jamais masqué
            out[sym] = {"error": f"{type(e).__name__}: {e}"}
    return out


def run_suite(lab, rev: dict, cache, costs: dict, risk, protocol: dict, campaign_id: str | None = None,
              criteria: dict = DEFAULT_CRITERIA, seed: int = 0, transfer_caches: dict | None = None) -> dict:
    g = rev["content"]
    seg = proto.segments_for(lab, cache.bars, protocol)
    window = (seg["train"][0], seg["validation"][1])
    res, m = _run(g, cache, costs, risk, window)
    # DSR sur la fenêtre train : celle sur laquelle tous les essais de la série sont mesurés
    tw = seg["train"]
    res_t, m_t = _run(g, cache, costs, risk, tw)
    t_obs, skew, kurt = daily_moments(res_t, (int(cache.bars.ts[tw[0]]), int(cache.bars.ts[tw[1] - 1])))
    trials = trial_sharpes(lab, cache.bars.version_id) or ([m_t["sharpe"]] if m_t["sharpe"] is not None else [])
    rep = {"window": window, "segments": {k: list(v) for k, v in seg.items()}, "base": _summ(m), "criteria": criteria}
    skipped = {"skipped": True, "reason": "critère éliminatoire déjà en échec : test coûteux non exécuté"}
    # du moins coûteux au plus coûteux ; arrêt des tests restants au premier échec certain ou critère non calculable
    steps = [
        ("cost_stress", lambda: cost_stress(g, cache, costs, risk, window)),
        ("monte_carlo", lambda: monte_carlo(res["trades"], res["initial_equity"], seed=seed)),
        ("deflated_sharpe", lambda: {**deflated_sharpe(m_t["sharpe"], t_obs, skew, kurt, trials), "window": "train",
                                     "trials_scope": "série : toutes campagnes, relances et versions du dataset"}),
        ("walk_forward", lambda: walk_forward(g, cache, costs, risk, protocol, seg)),
        ("sensitivity", lambda: sensitivity(g, cache, costs, risk, window)),
        ("random_baseline", lambda: random_baseline(g, cache, costs, risk, window, res["trades"], seed=seed)),
        ("walk_forward_reopt", lambda: walk_forward_reopt(g, cache, costs, risk, protocol, seed=seed, seg=seg)),
    ]
    failed = (rep["base"]["n_trades"] or 0) < criteria["min_trades"]
    for name, fn in steps:
        rep[name] = dict(skipped) if failed else fn()
        if not failed:
            # non calculable (None) = échec final aussi (`passed` exige True) : inutile de poursuivre
            failed = any(c["pass"] is not True for c in checks(rep, criteria, partial=True).values())
    rep["transfer"] = transfer(g, transfer_caches or {}, costs, risk, protocol, lab)
    rep["checks"] = checks(rep, criteria)
    rep["passed"] = all(c["pass"] is True for c in rep["checks"].values())
    return rep


def checks(rep: dict, c: dict, partial: bool = False) -> dict:
    """Verdict par critère ; un test non exécuté (`skipped`) vaut None. `partial` : seulement les tests déjà exécutés."""
    def chk(value, ok):
        return {"value": value, "pass": None if value is None else bool(ok(value))}

    def has(k):
        return not partial or (k in rep and not rep[k].get("skipped"))

    out = {"min_trades": chk(rep["base"]["n_trades"], lambda v: v >= c["min_trades"])}
    if has("walk_forward"):
        out["walk_forward"] = chk(rep.get("walk_forward", {}).get("positive_ratio"),
                                  lambda v: v >= c["wf_positive_folds_ratio"])
    if has("walk_forward_reopt"):
        wo = rep.get("walk_forward_reopt", {})
        out["walk_forward_reopt"] = chk(wo.get("positive_ratio"),
                                        lambda v: v >= c["wfo_positive_folds_ratio"] and wo["oos_net_total"] > 0)
    if has("sensitivity"):
        out["sensitivity"] = chk(rep.get("sensitivity", {}).get("positive_ratio"),
                                 lambda v: v >= c["sensitivity_positive_ratio"])
    if has("cost_stress"):
        out["cost_stress_x1.5"] = chk((rep.get("cost_stress", {}).get("spread_x1.5") or {}).get("expectancy"),
                                      lambda v: v > 0)
    if has("monte_carlo"):
        mc = rep.get("monte_carlo", {})
        out["mc_p95_max_dd"] = chk(mc["bootstrap_max_dd_pct"]["p95"] if mc.get("available") else None,
                                   lambda v: v <= c["mc_p95_max_dd_pct"])
    if has("random_baseline"):
        rb = rep.get("random_baseline", {})
        out["random_baseline"] = chk(rb["p_value"] if rb.get("available") else None,
                                     lambda v: v <= c["random_baseline_p_max"])
    if has("deflated_sharpe"):
        ds = rep.get("deflated_sharpe", {})
        out["deflated_sharpe"] = chk(ds["dsr"] if ds.get("available") else None, lambda v: v >= c["dsr_min"])
    return out
