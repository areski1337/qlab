"""Tests de robustesse sur la fenêtre de recherche (train + validation).

Aucun de ces tests n'est une preuve suffisante de robustesse ; ils sont
complémentaires et leurs hypothèses sont rappelées dans le rapport.

- walk_forward : stabilité sur des fenêtres successives, paramètres FIGÉS
  (pas de ré-optimisation par fenêtre : c'est un test de stabilité, pas un
  walk-forward d'optimisation).
- sensitivity : voisins paramétriques (±1 pas entier, ×0,8/×1,2 réel).
- cost_stress : spread ×1,5 et ×2, glissement et commission ajoutés.
- monte_carlo : bootstrap des PnL de trades (i.i.d. supposé : ignore
  l'autocorrélation) et permutations d'ordre (drawdown seulement).
- random_baseline : entrées aléatoires de même fréquence et même part long,
  mêmes sorties/risque ; p-valeur empirique de l'expectancy.
- deflated_sharpe : Bailey & López de Prado (2014), N essais = nombre de
  candidats évalués dans la campagne ; suppose des essais indépendants
  (approximation optimiste quand les candidats sont corrélés).
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


def walk_forward(g, cache, costs, risk, protocol) -> dict:
    folds = []
    for f in proto.walk_forward(len(cache.bars), protocol):
        _, m = _run(g, cache, costs, risk, f["test"])
        folds.append({"fold": f["fold"], "window": f["test"], **_summ(m)})
    pos = [f for f in folds if (f["expectancy"] or 0) > 0]
    return {"folds": folds, "positive_ratio": len(pos) / len(folds) if folds else None}


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
    base = costs.get("fixed_spread_points") or 0
    pt = float(cache.bars.spec["point"])
    scen = {
        "spread_x1.5": {**costs, "spread_mode": "max", "fixed_spread_points": max(base, 1) * 1.5},
        "spread_x2": {**costs, "spread_mode": "max", "fixed_spread_points": max(base, 1) * 2},
        "slippage+": {**costs, "slippage_points": costs.get("slippage_points", 0) + max(1, int(base * 0.25))},
        "commission+": {**costs, "commission_per_lot_side": costs.get("commission_per_lot_side", 0) + 3.5},
    }
    out = {}
    for k, c in scen.items():
        _, m = _run(g, cache, c, risk, window)
        out[k] = _summ(m)
    out["_note"] = f"spread de base {base} points (point = {pt}) ; mode max(barres, fixe)"
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


def run_suite(lab, rev: dict, cache, costs: dict, risk, protocol: dict, campaign_id: str | None = None,
              criteria: dict = DEFAULT_CRITERIA, seed: int = 0) -> dict:
    g = rev["content"]
    seg = proto.segments(len(cache.bars), protocol)
    window = (seg["train"][0], seg["validation"][1])
    res, m = _run(g, cache, costs, risk, window)
    wts = (int(cache.bars.ts[window[0]]), int(cache.bars.ts[window[1] - 1]))
    trials = []
    if campaign_id:
        import json
        trials = [json.loads(r[0]).get("sharpe") for r in lab.con.execute(
            "SELECT metrics_json FROM evaluations WHERE campaign_id=? AND segment='train'", (campaign_id,))]
    t_obs, skew, kurt = daily_moments(res, wts)
    rep = {
        "window": window, "base": _summ(m),
        "walk_forward": walk_forward(g, cache, costs, risk, protocol),
        "sensitivity": sensitivity(g, cache, costs, risk, window),
        "cost_stress": cost_stress(g, cache, costs, risk, window),
        "monte_carlo": monte_carlo(res["trades"], res["initial_equity"], seed=seed),
        "random_baseline": random_baseline(g, cache, costs, risk, window, res["trades"], seed=seed),
        "deflated_sharpe": deflated_sharpe(m["sharpe"], t_obs, skew, kurt, trials or [m["sharpe"]]),
        "criteria": criteria,
    }
    rep["checks"] = checks(rep, criteria)
    rep["passed"] = all(c["pass"] for c in rep["checks"].values() if c["pass"] is not None) and \
        all(c["pass"] is not None for c in rep["checks"].values())
    return rep


def checks(rep: dict, c: dict) -> dict:
    def chk(value, ok):
        return {"value": value, "pass": None if value is None else bool(ok(value))}
    mc = rep["monte_carlo"]
    rb = rep["random_baseline"]
    ds = rep["deflated_sharpe"]
    return {
        "min_trades": chk(rep["base"]["n_trades"], lambda v: v >= c["min_trades"]),
        "walk_forward": chk(rep["walk_forward"]["positive_ratio"], lambda v: v >= c["wf_positive_folds_ratio"]),
        "sensitivity": chk(rep["sensitivity"]["positive_ratio"], lambda v: v >= c["sensitivity_positive_ratio"]),
        "cost_stress_x1.5": chk(rep["cost_stress"]["spread_x1.5"]["expectancy"], lambda v: v > 0),
        "mc_p95_max_dd": chk(mc["bootstrap_max_dd_pct"]["p95"] if mc.get("available") else None,
                             lambda v: v <= c["mc_p95_max_dd_pct"]),
        "random_baseline": chk(rb["p_value"] if rb.get("available") else None, lambda v: v <= c["random_baseline_p_max"]),
        "deflated_sharpe": chk(ds["dsr"] if ds.get("available") else None, lambda v: v >= c["dsr_min"]),
    }
