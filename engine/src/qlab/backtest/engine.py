"""Moteur de backtest de référence (interprète le génome canonique, indépendant du MQL5).

Sémantique d'exécution (identique dans le générateur MQL5) :
1. Les conditions sont évaluées à la CLÔTURE de la barre i.
2. L'ordre est exécuté au marché à l'OUVERTURE de la barre i+1 :
   long au prix Ask (= Bid open + spread), short au Bid ; ± glissement.
3. Le stop et l'objectif sont calculés depuis le prix d'entrée effectif et des
   valeurs connues à la clôture de i (ATR, swing).
4. Dans chaque barre suivante : gap d'ouverture au-delà du stop → sortie à
   l'ouverture (pire prix) ; sinon stop si Bid low <= SL (long) / Ask high >= SL
   (short) ; objectif si Bid high >= TP / Ask low <= TP.
   Stop ET objectif atteints dans la même barre OHLC → le STOP est retenu
   (convention conservatrice, signalée `ambiguous`).
5. Break-even / trailing / sortie sur signal opposé / time stop sont décidés à
   la clôture et effectifs à partir de la barre suivante.
6. Une seule position à la fois par stratégie ; un signal long ET short
   simultané est ignoré (conflit enregistré).
Les données d'une même entrée (données, génome, coûts, limites) donnent un
résultat identique (aucun aléa).
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from ..core.hashing import sha256_json
from ..core.versions import COMPONENT_VERSIONS
from ..features import FeatureCache
from ..features.classic import atr_arr
from ..features.ict import pivots
from ..features.sessions import minutes_to_weekly_close, trading_day
from ..genome.model import semantic_hash, signals
from ..risk.controller import RiskController, RiskState
from .costs import spread_series, value_per_price_unit


# Profil d'exécution (inclus dans les clés de cache). Recherche : prudent. Parité : conditions du testeur.
DEFAULT_EXECUTION = {
    "intrabar": "m1_if_available",  # barres ambiguës résolues par les M1 du contexte si présentes
    "m1_path": "conservative",       # ambiguïté résiduelle dans une M1 : stop | "mt5_ohlc" (O-L-H-C / O-H-L-C)
    "gap_fill": "open",              # stop franchi par un gap : ouverture (prudent) | "stop_price" (testeur MT5)
}
TESTER_EXECUTION = {"intrabar": "m1_if_available", "m1_path": "mt5_ohlc", "gap_fill": "stop_price"}


def _resolve_m1(m1, t0: int, t1: int, d: int, sl: float, tp: float | None, sp_fallback: float, pt: float,
                path_mode: str, gap_fill: str, slip: float):
    """Parcourt les M1 de [t0, t1) pour départager stop/objectif. Retourne (prix, motif, ambigu) ou None."""
    a, z = int(np.searchsorted(m1.ts, t0)), int(np.searchsorted(m1.ts, t1))
    for q in range(a, z):
        sp = (m1.spread[q] if m1.spread[q] > 0 else sp_fallback) * pt if d == -1 else 0.0
        o, h, l, c = m1.open[q] + sp, m1.high[q] + sp, m1.low[q] + sp, m1.close[q] + sp
        if q > a:
            if (o - sl) * d <= 0:
                return (sl if gap_fill == "stop_price" else o) - d * slip, "stop_gap", False
            if tp is not None and (o - tp) * d >= 0:
                return o, "target_gap", False
        adverse, favorable = (l, h) if d == 1 else (h, l)
        hs = (adverse - sl) * d <= 0
        ht = tp is not None and (favorable - tp) * d >= 0
        if hs and ht:
            if path_mode != "mt5_ohlc":
                return sl - d * slip, "stop", True
            for p in ((l, h, c) if m1.close[q] > m1.open[q] else (h, l, c)):
                if (p - sl) * d <= 0:
                    return sl - d * slip, "stop", False
                if (p - tp) * d >= 0:
                    return tp, "target", False
            return sl - d * slip, "stop", True
        if hs:
            return sl - d * slip, "stop", False
        if ht:
            return tp, "target", False
    return None


def run(genome: dict, cache: FeatureCache, cost_profile: dict, risk: RiskController,
        initial_equity: float = 10_000.0, start: int = 0, stop: int | None = None,
        signals_override: tuple[np.ndarray, np.ndarray] | None = None,
        execution: dict | None = None, news=None) -> dict:
    """Backtest sur les barres [start, stop). Les features sont calculées sur toute la série
    disponible jusqu'à `stop` exclusivement côté décision (les entrées n'ont lieu que dans la fenêtre)."""
    b = cache.bars
    n = len(b) if stop is None else stop
    spec = b.spec
    pt = float(spec["point"])
    spread = spread_series(b, cost_profile)
    slip = float(cost_profile.get("slippage_points", 0)) * pt
    comm = float(cost_profile.get("commission_per_lot_side", 0.0))
    ex = genome["exit"]
    mg = genome["management"]
    # signals_override : entrées imposées (baselines aléatoires), mêmes règles de sortie et de risque.
    long_sig, short_sig = signals_override if signals_override is not None else signals(genome, cache)
    days = trading_day(b.ts)
    exe = {**DEFAULT_EXECUTION, **(execution or {})}
    news = news if news is not None else getattr(cache, "news", None)
    m1 = cache.context.get("M1") if exe["intrabar"] == "m1_if_available" and b.timeframe != "M1" else None
    wk_min = risk.limits.get("close_before_weekend_minutes")
    mtc_open = minutes_to_weekly_close(b.ts) if wk_min else None
    mtc_close = minutes_to_weekly_close(b.ts + b.tf_s) if wk_min else None
    nf = risk.limits.get("news_filter") or {}
    resolved_m1 = 0

    st_cfg = ex["stop"]
    if st_cfg["type"] == "atr":
        stop_atr = atr_arr(b, st_cfg["period"])
    elif st_cfg["type"] == "swing":
        sw_hi, sw_lo, _, _ = pivots(b, st_cfg["left"], st_cfg["right"])
        stop_atr = atr_arr(b, 14)
    tg = ex["target"]
    tg_atr = atr_arr(b, tg["period"]) if tg and tg["type"] == "atr" else None
    tr = ex["trailing"]
    tr_atr = atr_arr(b, tr["period"]) if tr else None
    swap_ok = cost_profile.get("apply_swap", True) and spec.get("swap_mode") == 1

    req_risk = risk.effective_risk_pct(genome["sizing"]["risk_pct"])
    rs = RiskState(equity=initial_equity, peak_equity=initial_equity)
    trades: list[dict] = []
    skipped: Counter = Counter()
    day_count: Counter = Counter()
    vol_min, vol_step = float(spec["volume_min"]), float(spec["volume_step"])
    vol_max = min(float(spec["volume_max"]), risk.limits["max_lots"])

    either = long_sig | short_sig
    sig_idx = np.flatnonzero(either[:n])
    k = 0
    ptr = start
    last_exit = -10**9
    O, H, L, C = b.open, b.high, b.low, b.close
    while True:
        while k < len(sig_idx) and sig_idx[k] < ptr:
            k += 1
        if k >= len(sig_idx):
            break
        i = int(sig_idx[k])
        k += 1
        e = i + 1
        if e >= n:
            break
        if long_sig[i] and short_sig[i]:
            skipped["conflict_long_short"] += 1
            continue
        d = 1 if long_sig[i] else -1
        if i - last_exit < mg["cooldown_bars"]:
            skipped["cooldown"] += 1
            continue
        if day_count[days[e]] >= mg["max_trades_per_day"]:
            skipped["max_trades_per_day"] += 1
            continue
        if wk_min and mtc_open[e] <= wk_min:
            skipped["risk:weekend_window"] += 1
            continue
        if nf.get("enabled"):
            if news is None or not news.covered(int(b.ts[e])):
                skipped["risk:news_data_unavailable"] += 1  # filtre actif mais non vérifiable : refus
                continue
            if news.blocked_at(int(b.ts[e])):
                skipped["risk:news_window"] += 1
                continue

        entry = O[e] + (spread[e] * pt if d == 1 else 0.0) + d * slip
        if st_cfg["type"] == "atr":
            dist = st_cfg["mult"] * stop_atr[i]
        elif st_cfg["type"] == "points":
            dist = st_cfg["points"] * pt
        else:
            lvl = (sw_lo[i] - st_cfg["buffer_atr"] * stop_atr[i]) if d == 1 else (sw_hi[i] + st_cfg["buffer_atr"] * stop_atr[i])
            dist = (entry - lvl) * d
        if not math.isfinite(dist) or dist <= 0:
            skipped["stop_not_computable"] += 1
            continue
        sl = entry - d * dist
        if tg is None:
            tp = None
        elif tg["type"] == "rr":
            tp = entry + d * tg["rr"] * dist
        else:
            if not math.isfinite(tg_atr[i]):
                skipped["target_not_computable"] += 1
                continue
            tp = entry + d * tg["mult"] * tg_atr[i]

        vpu, approx = value_per_price_unit(spec, entry)
        risk_amount = rs.equity * req_risk / 100
        raw_lots = risk_amount / (dist * vpu)
        lots = math.floor(raw_lots / vol_step + 1e-9) * vol_step
        lots = min(round(lots, 8), vol_max)
        if lots < vol_min:
            skipped["lots_below_min"] += 1  # jamais forcé au lot minimum : cela dépasserait le risque
            continue
        reason = risk.check_entry(rs, day=int(days[e]), spread_points=float(spread[e]), lots=lots)
        if reason:
            skipped[f"risk:{reason}"] += 1
            if reason == "max_drawdown_halt":
                break
            continue
        risk.on_entry(rs)
        day_count[days[e]] += 1

        # ---- gestion de la position ----
        exit_px = exit_reason = None
        ambiguous = False
        j = e
        mae = mfe = 0.0
        be_done = False
        while True:
            if j >= n:
                j = n - 1
                exit_px = C[j] + (spread[j] * pt if d == -1 else 0.0)
                exit_reason = "end_of_data"
                break
            sp = spread[j] * pt
            lo_px, hi_px, op_px = (L[j], H[j], O[j]) if d == 1 else (L[j] + sp, H[j] + sp, O[j] + sp)
            if j > e:
                if ex["time_stop_bars"] and j - e >= ex["time_stop_bars"]:
                    exit_px, exit_reason = op_px - d * slip, "time_stop"
                    break
                if (op_px - sl) * d <= 0:
                    exit_px = (sl if exe["gap_fill"] == "stop_price" else op_px) - d * slip
                    exit_reason = "stop_gap"
                    break
                if tp is not None and (op_px - tp) * d >= 0:
                    exit_px, exit_reason = op_px, "target_gap"
                    break
            adverse, favorable = (lo_px, hi_px) if d == 1 else (hi_px, lo_px)
            mae = min(mae, (adverse - entry) * d / dist)
            mfe = max(mfe, (favorable - entry) * d / dist)
            hit_sl = (adverse - sl) * d <= 0
            hit_tp = tp is not None and (favorable - tp) * d >= 0
            if hit_sl and hit_tp and m1 is not None:
                r = _resolve_m1(m1, int(b.ts[j]), int(b.ts[j]) + b.tf_s, d, sl, tp, float(spread[j]), pt,
                                exe["m1_path"], exe["gap_fill"], slip)
                if r is not None:
                    exit_px, exit_reason, ambiguous = r
                    resolved_m1 += 1
                    break
            if hit_sl:
                ambiguous = hit_tp
                exit_px, exit_reason = sl - d * slip, "stop"
                break
            if hit_tp:
                exit_px, exit_reason = tp, "target"
                break
            # décisions à la clôture de j, effectives en j+1
            close_px = C[j] if d == 1 else C[j] + sp
            r_now = (close_px - entry) * d / dist
            if ex["break_even"] and not be_done and r_now >= ex["break_even"]["at_r"]:
                sl = entry if (entry - sl) * d > 0 else sl
                be_done = True
            if tr and r_now >= tr["activate_r"] and math.isfinite(tr_atr[j]):
                cand = close_px - d * tr["mult"] * tr_atr[j]
                if (cand - sl) * d > 0:
                    sl = cand
            weekend = bool(wk_min) and mtc_close[j] <= wk_min
            if weekend or (ex["exit_on_opposite"] and ((d == 1 and short_sig[j]) or (d == -1 and long_sig[j]))):
                if j + 1 >= n:
                    j += 1
                    continue
                j += 1
                sp1 = spread[j] * pt
                exit_px = (O[j] if d == 1 else O[j] + sp1) - d * slip
                exit_reason = "weekend_close" if weekend else "opposite_signal"
                break
            j += 1

        vpu_x, approx_x = value_per_price_unit(spec, exit_px)
        gross = (exit_px - entry) * d * vpu_x * lots
        commission = 2 * comm * lots
        swap = 0.0
        if swap_ok:
            swap = _swap(spec, days[e], days[j], d, lots, pt, vpu_x)
        pnl = gross - commission + swap
        risk.on_exit(rs, pnl)
        trades.append({
            "signal_i": i, "entry_i": e, "exit_i": j, "entry_ts": int(b.ts[e]), "exit_ts": int(b.ts[j]),
            "day": int(days[e]), "dir": d, "lots": lots, "entry": entry, "exit": exit_px, "sl_init": entry - d * dist,
            "sl_final": sl, "tp": tp, "reason": exit_reason, "ambiguous": ambiguous, "gross": gross,
            "commission": commission, "swap": swap, "pnl": pnl, "risk_amount": dist * vpu * lots,
            "r": gross / (dist * vpu * lots), "mae_r": mae, "mfe_r": mfe, "bars_held": j - e + 1,
            "spread_cost": spread[e] * pt * vpu * lots, "value_approx": approx or approx_x,
            "equity_after": rs.equity,
        })
        last_exit = j
        ptr = j  # un signal à la clôture de la barre de sortie peut ouvrir la position suivante
    return {
        "trades": trades, "skipped": dict(skipped), "initial_equity": initial_equity, "final_equity": rs.equity,
        "halted": rs.halted, "risk_pct_effective": req_risk, "execution": exe, "m1_resolved": resolved_m1,
        "news_windows_sha256": news.sha() if news is not None else None, "risk_limits_sha256": risk.limits_sha256,
        "n_bars": n - start, "window": [int(b.ts[start]), int(b.ts[n - 1])] if n > start else None,
        "genome_hash": semantic_hash(genome), "dataset_sha256": b.content_sha256,
        "cost_profile_sha256": sha256_json(cost_profile),
        "versions": {k: COMPONENT_VERSIONS[k] for k in ("backtester_reference", "cost_model", "feature_engine",
                                                         "genome_schema", "risk_controller")},
    }


def _swap(spec, d_entry: int, d_exit: int, direction: int, lots: float, pt: float, vpu: float) -> float:
    """Swap en mode points (swap_mode=1) : une nuit par bascule de journée de trading dont la veille est un
    jour ouvré ; triple la nuit `swap_rollover3days` (énumération MT5 : 0=dimanche)."""
    pts = float(spec["swap_long"] if direction == 1 else spec["swap_short"])
    total = 0.0
    for dd in range(int(d_entry) + 1, int(d_exit) + 1):
        prev_mon0 = (dd - 1 + 3) % 7  # 0 = lundi
        if prev_mon0 >= 5:
            continue
        mult = 3 if (prev_mon0 + 1) % 7 == int(spec.get("swap_rollover3days", 3)) else 1
        total += pts * pt * vpu * lots * mult
    return total
