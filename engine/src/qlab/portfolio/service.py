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


def _load(lab, revision_ids: list[str], segment: str, required: bool = True):
    series, eq0, meta = {}, {}, {}
    for rid in revision_ids:
        row = lab.con.execute("SELECT e.trades_artifact, e.metrics_json, v.symbol_spec_json FROM evaluations e "
                              "JOIN dataset_versions v ON v.id=e.dataset_version_id WHERE e.revision_id=? AND e.segment=? "
                              "AND e.trades_artifact IS NOT NULL ORDER BY e.created_at DESC LIMIT 1", (rid, segment)).fetchone()
        if row is None:
            if required:
                raise ValueError(f"{rid} : aucune évaluation « {segment} » avec transactions conservées")
            return None
        trades = lab.store.get_json(row["trades_artifact"])["trades"]
        m = json.loads(row["metrics_json"])
        spec = json.loads(row["symbol_spec_json"])
        series[rid], eq0[rid] = trades, m["initial_equity"]
        meta[rid] = {"symbol": spec.get("symbol"), "currency_base": spec.get("currency_base"),
                     "currency_profit": spec.get("currency_profit"),
                     "long_share": float(np.mean([t["dir"] == 1 for t in trades])) if trades else 0.5,
                     "entry_days": set(trading_day(np.array([t["entry_ts"] for t in trades])).tolist()) if trades else set(),
                     "costs": m.get("costs", {})}
    return series, eq0, meta


def build(lab, name: str, revision_ids: list[str], method: str = "min_corr", segment: str = "research",
          w_min: float = 0.05, w_max: float = 0.5, report_segment: str | None = "oos") -> dict:
    """Poids calculés sur `segment` ; performance et corrélations rapportées aussi sur `report_segment` (hors
    échantillon par défaut) avec les mêmes poids : l'écart recherche/OOS est affiché, jamais masqué."""
    if len(revision_ids) < 2:
        raise ValueError("au moins deux stratégies requises")
    series, eq0, meta = _load(lab, revision_ids, segment)
    R = pe.daily_matrix(series, eq0)
    w, why = pe.allocate(R, method, w_min, w_max)
    rep = pe.analyze(R, w, meta)
    rep.update({"method": method, "bounds": [w_min, w_max], "segment": segment, "allocation_detail": why,
                "version": COMPONENT_VERSIONS["portfolio"]})
    if report_segment and report_segment != segment:
        other = _load(lab, revision_ids, report_segment, required=False)
        if other is None:
            rep[report_segment] = {"available": False,
                                   "reason": f"au moins une stratégie sans évaluation « {report_segment} » conservée"}
        else:
            Ro = pe.daily_matrix(other[0], other[1]).reindex(columns=R.columns, fill_value=0.0).fillna(0.0)
            rep[report_segment] = {"available": True, **pe.analyze(Ro, w, other[2])}
    pid = new_id("pf")
    sha = lab.store.put_json(rep, kind="portfolio_report")
    lab.con.execute("INSERT INTO portfolios VALUES (?,?,?,?,?,?,?)", (pid, name, method, json.dumps(
        {"revisions": revision_ids, "segment": segment, "report_segment": report_segment, "w_min": w_min,
         "w_max": w_max}), sha, COMPONENT_VERSIONS["portfolio"], utc_now_iso()))
    for rid, wi in zip(R.columns, w):
        lab.con.execute("INSERT INTO portfolio_allocations VALUES (?,?,?,?)",
                        (pid, rid, float(wi), json.dumps({"method": method})))
    audit(lab.con, "portfolio.created", pid, method=method, n=len(revision_ids))
    return {"id": pid, "report": rep}
