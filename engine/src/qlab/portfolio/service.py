"""Construction d'un portefeuille à partir d'évaluations conservées."""
from __future__ import annotations

import json

import numpy as np

from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..core.versions import COMPONENT_VERSIONS
from ..features.sessions import trading_day
from ..storage.db import audit
from . import engine as pe


def build(lab, name: str, revision_ids: list[str], method: str = "min_corr", segment: str = "research",
          w_min: float = 0.05, w_max: float = 0.5) -> dict:
    if len(revision_ids) < 2:
        raise ValueError("au moins deux stratégies requises")
    series, eq0, meta = {}, {}, {}
    for rid in revision_ids:
        row = lab.con.execute("SELECT e.trades_artifact, e.metrics_json, v.symbol_spec_json FROM evaluations e "
                              "JOIN dataset_versions v ON v.id=e.dataset_version_id WHERE e.revision_id=? AND e.segment=? "
                              "AND e.trades_artifact IS NOT NULL ORDER BY e.created_at DESC LIMIT 1", (rid, segment)).fetchone()
        if row is None:
            raise ValueError(f"{rid} : aucune évaluation « {segment} » avec transactions conservées")
        trades = lab.store.get_json(row["trades_artifact"])["trades"]
        m = json.loads(row["metrics_json"])
        spec = json.loads(row["symbol_spec_json"])
        series[rid], eq0[rid] = trades, m["initial_equity"]
        meta[rid] = {"symbol": spec.get("symbol"), "currency_base": spec.get("currency_base"),
                     "currency_profit": spec.get("currency_profit"),
                     "long_share": float(np.mean([t["dir"] == 1 for t in trades])) if trades else 0.5,
                     "entry_days": set(trading_day(np.array([t["entry_ts"] for t in trades])).tolist()) if trades else set(),
                     "costs": m.get("costs", {})}
    R = pe.daily_matrix(series, eq0)
    w, why = pe.allocate(R, method, w_min, w_max)
    rep = pe.analyze(R, w, meta)
    rep.update({"method": method, "bounds": [w_min, w_max], "segment": segment, "allocation_detail": why,
                "version": COMPONENT_VERSIONS["portfolio"]})
    pid = new_id("pf")
    sha = lab.store.put_json(rep, kind="portfolio_report")
    lab.con.execute("INSERT INTO portfolios VALUES (?,?,?,?,?,?,?)", (pid, name, method, json.dumps(
        {"revisions": revision_ids, "segment": segment, "w_min": w_min, "w_max": w_max}), sha,
        COMPONENT_VERSIONS["portfolio"], utc_now_iso()))
    for rid, wi in zip(R.columns, w):
        lab.con.execute("INSERT INTO portfolio_allocations VALUES (?,?,?,?)",
                        (pid, rid, float(wi), json.dumps({"method": method})))
    audit(lab.con, "portfolio.created", pid, method=method, n=len(revision_ids))
    return {"id": pid, "report": rep}
