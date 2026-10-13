"""Comparaison différentielle moteur de référence ↔ Strategy Tester MT5.

Entrées : trace CSV de l'EA (SIG / ENTRY / DEAL / FIRST / LASTBAR) et les
mêmes barres côté référence. Sorties : chiffres bruts, écarts, tolérances,
diagnostics, note A–F et drapeau de divergence critique.

Note : les coûts du testeur (commission, swap, spread réel des ticks) sont
OBSERVÉS dans les deals ; la référence est rejouée avec la commission observée
et le spread des barres, et l'écart résiduel est rapporté, pas masqué.
"""
from __future__ import annotations

import numpy as np

from ..backtest import engine
from ..data.tz import server_to_utc
from ..metrics.core import compute

REASON = {3: "expert", 4: "stop", 5: "target"}
GRADES = [("A", 0.98, 0.03, 0.95), ("B", 0.95, 0.07, 0.90), ("C", 0.90, 0.15, 0.80), ("D", 0.75, 0.30, 0.0)]


def parse_trace(text: str, tz_profile: str) -> dict:
    sig, deals, entries, skips, fails, nohist = {}, [], [], {}, 0, 0
    first = last = None
    for line in text.splitlines():
        p = line.strip().split(";")
        if not p or not p[0]:
            continue
        k = p[0]
        if k == "SIG":
            sig[int(p[1])] = (p[2] == "1", p[3] == "1")
        elif k == "FIRST":
            first = int(p[1])
        elif k == "LASTBAR":
            last = int(p[1])
        elif k == "ENTRY":
            entries.append({"close_utc": int(p[1]), "dir": int(p[2]), "price": float(p[3]), "sl": float(p[4]),
                            "tp": float(p[5]), "lots": float(p[6])})
        elif k == "DEAL":
            deals.append({"ticket": int(p[1]), "time_server": int(p[2]), "type": int(p[3]), "entry": int(p[4]),
                          "price": float(p[5]), "volume": float(p[6]), "profit": float(p[7]),
                          "commission": float(p[8]), "swap": float(p[9]), "reason": int(p[10]), "position": int(p[11])})
        elif k == "SKIP":
            skips[p[1]] = skips.get(p[1], 0) + 1
        elif k == "ORDERFAIL":
            fails += 1
        elif k == "NOHIST":
            nohist += 1
    if deals:
        utc, _ = server_to_utc(np.array([d["time_server"] for d in deals]), tz_profile)
        for d, u in zip(deals, utc):
            d["time_utc"] = int(u)
    trades = []
    by_pos: dict[int, dict] = {}
    for d in sorted(deals, key=lambda x: (x["time_server"], x["ticket"])):
        if d["entry"] == 0:  # DEAL_ENTRY_IN
            by_pos[d["position"]] = {"in": d}
        elif d["entry"] in (1, 3) and d["position"] in by_pos:  # OUT / OUT_BY
            t = by_pos.pop(d["position"])
            t["out"] = d
            trades.append(t)
    return {"signals": sig, "first": first, "last": last, "entries": entries, "trades": trades,
            "open_at_end": len(by_pos), "skips": skips, "order_failures": fails, "nohist": nohist}


def compare(tr: dict, rev: dict, cache, risk, deposit: float, costs_base: dict) -> dict:
    b = cache.bars
    tf = b.tf_s
    if tr["first"] is None:
        return {"error": "trace sans barre évaluée (historique insuffisant ?)", "critical": True, "grade": "F"}
    close = b.ts + tf
    i0 = int(np.searchsorted(close, tr["first"]))
    i1 = int(np.searchsorted(close, tr["last"] if tr["last"] else close[-1], side="right"))
    if i0 >= len(b) or close[i0] != tr["first"]:
        return {"error": "barre FIRST absente des données de référence", "critical": True, "grade": "F"}

    # coûts observés dans le testeur
    lots_total = sum(t["in"]["volume"] for t in tr["trades"]) or None
    comm = sum(t["in"]["commission"] + t["out"]["commission"] for t in tr["trades"])
    comm_side = abs(comm) / (2 * lots_total) if lots_total else 0.0
    # spread des barres ; 0 hors fenêtre sans effet. Si la fenêtre contient des spreads nuls : médiane (signalé).
    win_sp = b.spread[i0:i1 + 1]
    floor = 0.0 if (win_sp > 0).all() else float(np.median(win_sp[win_sp > 0]))
    costs = {**costs_base, "spread_mode": "max", "fixed_spread_points": floor, "commission_per_lot_side": comm_side,
             "provenance": {**costs_base.get("provenance", {}), "commission": "observed_mt5_tester",
                            "spread": "bars" if floor == 0 else "bars+median_floor"}}
    res = engine.run(rev["content"], cache, costs, risk, initial_equity=deposit, start=i0, stop=min(i1 + 1, len(b)))
    from ..genome.model import signals
    lg, sh = signals(rev["content"], cache)

    # 1) signaux
    ref_sig = {int(close[i]): (bool(lg[i]), bool(sh[i])) for i in range(i0, min(i1, len(b))) if lg[i] or sh[i]}
    ea_sig = {k: v for k, v in tr["signals"].items() if tr["first"] <= k <= close[min(i1, len(b)) - 1]}
    keys = set(ref_sig) | set(ea_sig)
    agree = sum(1 for k in keys if ref_sig.get(k) == ea_sig.get(k))
    sig_jacc = agree / len(keys) if keys else 1.0
    sig_diff = sorted(k for k in keys if ref_sig.get(k) != ea_sig.get(k))[:20]

    # 2) trades : appariement par barre d'entrée et direction
    pt = float(b.spec["point"])
    ea_tr = {}
    for t in tr["trades"]:
        bar = (t["in"]["time_utc"] // tf) * tf
        ea_tr[(bar, 1 if t["in"]["type"] == 0 else -1)] = t
    ref_tr = {(t["entry_ts"], t["dir"]): t for t in res["trades"]}
    matched = [(ref_tr[k], ea_tr[k]) for k in ref_tr if k in ea_tr]
    n_max = max(len(ref_tr), len(ea_tr))
    trade_match = len(matched) / n_max if n_max else 1.0
    rows = []
    for r, e in matched:
        e_reason = REASON.get(e["out"]["reason"], f"other:{e['out']['reason']}")
        r_reason = {"stop": "stop", "stop_gap": "stop", "target": "target", "target_gap": "target"}.get(r["reason"], "expert")
        rows.append({
            "entry_ts": r["entry_ts"], "dir": r["dir"],
            "entry_diff_pts": (e["in"]["price"] - r["entry"]) / pt,
            "exit_diff_pts": (e["out"]["price"] - r["exit"]) / pt,
            "exit_bar_diff": int(((e["out"]["time_utc"] // tf) * tf - r["exit_ts"]) // tf),
            "lots_ref": r["lots"], "lots_mt5": e["in"]["volume"],
            "reason_ref": r_reason, "reason_mt5": e_reason, "ambiguous_ref": r["ambiguous"],
            "pnl_ref": r["pnl"], "pnl_mt5": e["out"]["profit"] + e["in"]["commission"] + e["out"]["commission"]
                                           + e["out"]["swap"],
        })
    reason_agree = np.mean([r["reason_ref"] == r["reason_mt5"] for r in rows]) if rows else 1.0
    step = float(b.spec["volume_step"])
    lots_bad = np.mean([abs(r["lots_ref"] - r["lots_mt5"]) > step + 1e-9 for r in rows]) if rows else 0.0
    net_ref = sum(t["pnl"] for t in res["trades"])
    net_mt5 = sum(t["out"]["profit"] + t["in"]["commission"] + t["out"]["commission"] + t["out"]["swap"]
                  for t in tr["trades"])
    net_diff = abs(net_ref - net_mt5) / max(abs(net_mt5), abs(net_ref), deposit * 0.01)

    grade = "F"
    for g, tm, nd, ra in GRADES:
        if trade_match >= tm and net_diff <= nd and reason_agree >= ra:
            grade = g
            break
    critical_reasons = []
    if sig_jacc < 0.95:
        critical_reasons.append(f"signaux concordants {sig_jacc:.1%} < 95 %")
    if trade_match < 0.90:
        critical_reasons.append(f"trades appariés {trade_match:.1%} < 90 %")
    if lots_bad > 0.05:
        critical_reasons.append(f"tailles divergentes sur {lots_bad:.1%} des trades")
    if tr["order_failures"]:
        critical_reasons.append(f"{tr['order_failures']} ordre(s) refusé(s) par le testeur")
    abs_med = lambda k: float(np.median(np.abs([r[k] for r in rows]))) if rows else None
    unmatched_ref = sorted(k[0] for k in ref_tr if k not in ea_tr)[:20]
    unmatched_mt5 = sorted(k[0] for k in ea_tr if k not in ref_tr)[:20]
    return {
        "window": {"first_close_utc": tr["first"], "last_bar_utc": tr["last"], "bars": i1 - i0},
        "signals": {"ref": len(ref_sig), "mt5": len(ea_sig), "agreement": sig_jacc, "first_diffs_close_utc": sig_diff},
        "trades": {"ref": len(ref_tr), "mt5": len(ea_tr), "matched": len(matched), "match_ratio": trade_match,
                   "unmatched_ref_entry_ts": unmatched_ref, "unmatched_mt5_entry_ts": unmatched_mt5,
                   "open_at_end_mt5": tr["open_at_end"]},
        "prices": {"median_abs_entry_diff_pts": abs_med("entry_diff_pts"),
                   "median_abs_exit_diff_pts": abs_med("exit_diff_pts"),
                   "exit_reason_agreement": float(reason_agree), "lots_mismatch_ratio": float(lots_bad)},
        "aggregate": {"net_ref": net_ref, "net_mt5": net_mt5, "net_rel_diff": net_diff,
                      "ref_metrics": {k: v for k, v in compute(res).items() if k in ("n_trades", "profit_factor",
                                                                                      "max_dd_pct", "sharpe")}},
        "costs_observed": {"commission_per_lot_side": comm_side, "commission_total": comm,
                           "swap_total": sum(t["out"]["swap"] for t in tr["trades"])},
        "ea_skips": tr["skips"], "nohist_bars": tr["nohist"],
        "matched_sample": rows[:50],
        "tolerances": {"grades": GRADES, "critical": "signaux < 95 %, trades < 90 %, lots > 5 %, ordres refusés"},
        "grade": grade, "critical": bool(critical_reasons), "critical_reasons": critical_reasons,
        "reference_matched": sig_jacc >= 0.98,
    }
