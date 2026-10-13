"""Observation d'un EA en compte DÉMO (lecture seule) et détection de dégradation.

Le déploiement (attacher l'EA à un graphique et activer l'AutoTrading) reste
une action manuelle de l'utilisateur : ce module n'envoie aucun ordre et
refuse d'observer un compte réel. La suspension passe par un fichier drapeau
lu par l'EA (dossier commun MT5) : plus d'entrées, positions existantes
conservées.

Critères de dégradation (pré-déclarés, versionnés avec 'risk_controller') :
- expectancy (R) observée sous la borne basse à 5 % du bootstrap des trades
  de référence (min 10 trades observés) ;
- drawdown observé au-delà du p95 Monte Carlo de référence ;
- distribution des R différente (Kolmogorov–Smirnov à deux échantillons, p < 0,01) ;
- dérive des coûts : commission+swap moyens par lot > 1,5 × la référence.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..genome import store as gstore
from ..storage.db import audit

STAGES = (0.25, 0.5, 1.0)
PROMOTION = {"min_trades": 20, "no_alerts": True}


def ks_2samp(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Statistique D et p-valeur asymptotique (Smirnov), sans dépendance externe."""
    a, b = np.sort(a), np.sort(b)
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return float("nan"), float("nan")
    allv = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, allv, side="right") / n
    cdf_b = np.searchsorted(b, allv, side="right") / m
    d = float(np.abs(cdf_a - cdf_b).max())
    en = math.sqrt(n * m / (n + m))
    lam = (en + 0.12 + 0.11 / en) * d
    p = 2 * sum((-1) ** (k - 1) * math.exp(-2 * k * k * lam * lam) for k in range(1, 101))
    return d, float(min(max(p, 0.0), 1.0))


def degradation(ref_trades: list[dict], live: list[dict], ref_mc_dd_p95: float | None, eq0: float,
                seed: int = 0) -> dict:
    """ref_trades / live : dicts avec 'r', 'pnl', 'lots', 'costs'."""
    alerts, checks = [], {}
    r_ref = np.array([t["r"] for t in ref_trades])
    r_live = np.array([t["r"] for t in live])
    if len(r_live) >= 10 and len(r_ref) >= 10:
        rng = np.random.default_rng(seed)
        boot = [rng.choice(r_ref, len(r_live)).mean() for _ in range(2000)]
        lo = float(np.percentile(boot, 5))
        checks["expectancy_r"] = {"live": float(r_live.mean()), "ref_p5_bootstrap": lo}
        if r_live.mean() < lo:
            alerts.append("expectancy observée sous le 5e centile attendu")
        d, p = ks_2samp(r_ref, r_live)
        checks["ks"] = {"D": d, "p": p}
        if p < 0.01:
            alerts.append("distribution des R significativement différente (KS p < 0,01)")
    else:
        checks["expectancy_r"] = {"note": "moins de 10 trades observés : non évaluable"}
    if live:
        eq = eq0 + np.cumsum([t["pnl"] for t in live])
        peak = np.maximum.accumulate(np.concatenate([[eq0], eq]))[1:]
        dd = float(((peak - eq) / peak).max() * 100)
        checks["max_dd_pct"] = {"live": dd, "ref_mc_p95": ref_mc_dd_p95}
        if ref_mc_dd_p95 is not None and dd > ref_mc_dd_p95:
            alerts.append("drawdown observé au-delà du p95 Monte Carlo de référence")
        lots = sum(t["lots"] for t in live) or None
        ref_lots = sum(t["lots"] for t in ref_trades) or None
        if lots and ref_lots:
            c_live = sum(t["costs"] for t in live) / lots
            c_ref = sum(t["costs"] for t in ref_trades) / ref_lots
            checks["cost_per_lot"] = {"live": c_live, "ref": c_ref}
            if c_ref < 0 and c_live < 1.5 * c_ref:  # coûts négatifs (débits)
                alerts.append("dérive des coûts (> 1,5 × référence)")
    return {"alerts": alerts, "checks": checks, "n_live": len(live), "criteria_version": "1.0"}


def flag_path(lab, magic: int | None = None) -> Path:
    from ..mql5.toolchain import data_path
    dp = data_path(lab.settings)
    if dp is None:
        raise FileNotFoundError("répertoire de données MT5 introuvable")
    d = dp.parent / "Common" / "Files" / "QLab"
    d.mkdir(parents=True, exist_ok=True)
    return d / ("EMERGENCY_STOP" if magic is None else f"suspend_{magic}.flag")


def set_flag(lab, magic: int | None, on: bool, reason: str) -> dict:
    p = flag_path(lab, magic)
    if on:
        p.write_text(f"{utc_now_iso()} {reason}\n", encoding="utf-8")
    else:
        p.unlink(missing_ok=True)
    audit(lab.con, "demo.flag", str(magic) if magic else "ALL", on=on, reason=reason, path=str(p))
    return {"path": str(p), "active": p.exists()}


def register(lab, rev_id: str) -> dict:
    """Enregistre un déploiement démo pour la dernière version d'EA compilée de la révision."""
    rev = gstore.get(lab.con, rev_id)
    if rev["status"] not in ("mt5_validated", "demo_observed"):
        raise PermissionError(f"statut {rev['status']} : seule une stratégie mt5_validated peut aller en démo")
    ea = lab.con.execute("SELECT e.* FROM ea_artifacts e JOIN compilation_runs c ON c.ea_id=e.id AND c.status='succeeded' "
                         "WHERE e.revision_id=? ORDER BY c.created_at DESC LIMIT 1", (rev_id,)).fetchone()
    if ea is None:
        raise PermissionError("aucun EA compilé pour cette révision")
    did = new_id("demo")
    magic = json.loads(ea["meta_json"])["magic"]
    now = utc_now_iso()
    lab.con.execute("INSERT INTO demo_deployments VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (did, rev_id, ea["id"], magic, None, None, STAGES[0], "registered", now, now))
    audit(lab.con, "demo.registered", did, revision=rev_id, magic=magic)
    return dict(lab.con.execute("SELECT * FROM demo_deployments WHERE id=?", (did,)).fetchone())


def fetch_live_trades(lab, magic: int, since_utc: float) -> tuple[list[dict], dict]:
    """Lit l'historique de deals du compte connecté (lecture seule). Refuse un compte réel."""
    import datetime as dt
    from ..data.mt5_source import mt5_session
    with mt5_session(lab.settings["mt5"]["terminal_path"]) as mt5:
        ai = mt5.account_info()
        if ai is None:
            raise RuntimeError("aucun compte connecté")
        if ai.trade_mode == 2:
            raise PermissionError("compte RÉEL détecté : l'observation est réservée aux comptes démo")
        deals = mt5.history_deals_get(dt.datetime.fromtimestamp(since_utc, dt.timezone.utc),
                                      dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)) or []
        acc = {"server": ai.server, "account_masked": f"***{str(ai.login)[-3:]}", "mode": "demo"}
    by_pos: dict[int, dict] = {}
    out = []
    for d in sorted((d for d in deals if d.magic == magic), key=lambda d: d.time):
        if d.entry == 0:
            by_pos[d.position_id] = {"in": d}
        elif d.position_id in by_pos:
            i = by_pos.pop(d.position_id)["in"]
            costs = d.commission + i.commission + d.swap
            out.append({"entry_time": int(i.time), "exit_time": int(d.time), "dir": 1 if i.type == 0 else -1,
                        "lots": i.volume, "pnl": d.profit + costs, "costs": costs, "r": None, "entry": i.price,
                        "exit": d.price})
    return out, acc


def observe(lab, deployment_id: str, live: list[dict] | None = None, account: dict | None = None) -> dict:
    """Compare l'observé à la référence ; `live` injectable (tests). Enregistre l'observation."""
    dep = dict(lab.con.execute("SELECT * FROM demo_deployments WHERE id=?", (deployment_id,)).fetchone())
    ref_ev = lab.con.execute("SELECT trades_artifact, metrics_json FROM evaluations WHERE revision_id=? AND segment='oos' "
                             "AND trades_artifact IS NOT NULL ORDER BY created_at DESC LIMIT 1", (dep["revision_id"],)).fetchone()
    if ref_ev is None:
        raise ValueError("aucune référence hors échantillon avec transactions")
    ref = lab.store.get_json(ref_ev["trades_artifact"])["trades"]
    ref_t = [{"r": t["r"], "pnl": t["pnl"], "lots": t["lots"], "costs": -(t["commission"]) + t["swap"]} for t in ref]
    eq0 = json.loads(ref_ev["metrics_json"])["initial_equity"]
    trs = gstore.transitions(lab.con, dep["revision_id"])
    rob = next((t["evidence"]["robustness_report"] for t in trs if "robustness_report" in t["evidence"]), None)
    p95 = None
    if rob:
        mc = lab.store.get_json(rob)["monte_carlo"]
        p95 = mc["bootstrap_max_dd_pct"]["p95"] if mc.get("available") else None
    if live is None:
        from ..core.timeutil import iso_to_ts
        live, account = fetch_live_trades(lab, dep["magic"], iso_to_ts(dep["started_at"]))
    # R observé : PnL brut / risque de référence moyen par lot (approximation documentée)
    risk_per_lot = np.mean([t["risk_amount"] / t["lots"] for t in ref]) if ref else None
    for t in live:
        if t.get("r") is None and risk_per_lot:
            t["r"] = (t["pnl"] - t["costs"]) / (risk_per_lot * t["lots"])
    rep = degradation(ref_t, live, p95, eq0)
    rep["risk_stage"] = dep["risk_stage"]
    rep["account"] = account
    rep["r_approximation"] = "R observé = PnL brut / (risque moyen par lot de la référence OOS × lots)"
    nxt = None
    if not rep["alerts"] and rep["n_live"] >= PROMOTION["min_trades"] and dep["risk_stage"] < 1.0:
        nxt = STAGES[STAGES.index(dep["risk_stage"]) + 1]
    rep["next_risk_stage_allowed"] = nxt
    oid = new_id("obs")
    lab.con.execute("INSERT INTO demo_observations VALUES (?,?,?,?)", (oid, deployment_id, utc_now_iso(), json.dumps(rep, default=str)))
    state = "observing"
    if rep["alerts"]:
        state = "suspended"
        try:
            rep["suspension_flag"] = set_flag(lab, dep["magic"], True, "; ".join(rep["alerts"]))
        except FileNotFoundError as e:
            rep["suspension_flag"] = {"error": str(e)}
        rev = gstore.get(lab.con, dep["revision_id"])
        if rev["status"] not in ("rejected", "quarantined"):
            gstore.set_status(lab.con, dep["revision_id"], "quarantined", {"reason": "dégradation démo"},
                              {"observation": oid, "alerts": rep["alerts"]})
    elif rep["n_live"] >= PROMOTION["min_trades"]:
        rev = gstore.get(lab.con, dep["revision_id"])
        if rev["status"] == "mt5_validated":
            gstore.set_status(lab.con, dep["revision_id"], "demo_observed", PROMOTION, {"observation": oid})
    lab.con.execute("UPDATE demo_deployments SET state=?, updated_at=?, server=COALESCE(?, server), "
                    "account_masked=COALESCE(?, account_masked) WHERE id=?",
                    (state, utc_now_iso(), (account or {}).get("server"), (account or {}).get("account_masked"), deployment_id))
    audit(lab.con, "demo.observed", deployment_id, alerts=rep["alerts"], n=rep["n_live"])
    return {"id": oid, **rep}


def promote_stage(lab, deployment_id: str) -> dict:
    last = lab.con.execute("SELECT report_json FROM demo_observations WHERE deployment_id=? ORDER BY observed_at DESC LIMIT 1",
                           (deployment_id,)).fetchone()
    if last is None:
        raise PermissionError("aucune observation : promotion impossible")
    nxt = json.loads(last[0]).get("next_risk_stage_allowed")
    if not nxt:
        raise PermissionError("critères de montée du risque non remplis")
    lab.con.execute("UPDATE demo_deployments SET risk_stage=?, updated_at=? WHERE id=?", (nxt, utc_now_iso(), deployment_id))
    audit(lab.con, "demo.risk_stage", deployment_id, stage=nxt)
    return {"risk_stage": nxt, "instruction": f"régler InpRiskScale={nxt} dans les paramètres de l'EA (ne peut pas dépasser 1)"}
