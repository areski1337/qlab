"""Chaîne complète de vérification MT5 d'une révision.

Transitions de statut (uniquement si la révision est déjà `oos_evaluated`) :
- reference_matched : signaux EA ≡ référence (≥ 98 %) dans le Strategy Tester ;
- mt5_validated     : note A ou B ET aucune divergence critique.
Une compilation réussie seule ne change aucun statut.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core.hashing import canonical_json
from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..genome import store as gstore
from ..storage.db import audit
from . import parity, toolchain


def verify(lab, rev_id: str, cache, risk, limits: dict, tz_profile: str, from_date: str, to_date: str,
           costs_base: dict, deposit: float = 10_000.0, model: int = 1) -> dict:
    rev = gstore.get(lab.con, rev_id)
    symbol = rev["content"]["market"]["symbol"]
    ea = toolchain.save_ea(lab, rev, symbol, tz_profile, limits, risk.limits_sha256)
    comp = toolchain.compile_ea(lab, ea)
    out = {"ea": ea, "compilation": comp}
    pid = new_id("par")

    def record(status, cfg, report=None, trace_sha=None, diag=None):
        report = json.loads(canonical_json(report)) if report else None  # scalaires numpy → JSON
        lab.con.execute("INSERT INTO parity_runs VALUES (?,?,?,?,?,?,?,?,?,?)", (
            pid, ea["id"], status, report.get("grade") if report else None,
            int(report["critical"]) if report else None, json.dumps(cfg), json.dumps(report) if report else None,
            trace_sha, diag, utc_now_iso()))
        audit(lab.con, "parity.run", ea["id"], status=status, grade=report.get("grade") if report else None,
              diagnostic=diag)

    if comp["status"] != "succeeded":
        record("blocked", {}, diag=f"compilation {comp['status']} : {comp['diagnostic']}")
        out["parity"] = {"status": "blocked", "diagnostic": comp["diagnostic"]}
        return out
    if getattr(cache, "news", None) is not None:  # le testeur lit le même fichier d'annonces que l'EA en démo
        from ..calendar.store import write_ea_file
        dp = toolchain.data_path(lab.settings)
        if dp is not None:
            write_ea_file(dp.parent / "Common" / "Files" / "QLab" / f"news_{symbol}.csv", cache.news, True)
    t = toolchain.run_tester(lab, ea, pid, symbol, rev["content"]["market"]["timeframe"], from_date, to_date,
                             deposit, model=model)
    if t["status"] != "completed":
        record(t["status"], t["config"], diag=t["diagnostic"])
        out["parity"] = t
        return out
    text = Path(t["trace_path"]).read_text(encoding="cp1252", errors="replace")
    trace_sha = lab.store.put_bytes(text.encode("utf-8"), kind="mt5_trace", media_type="text/csv")
    report = parity.compare(parity.parse_trace(text, tz_profile), rev, cache, risk, deposit, costs_base)
    report["tester"] = {k: t[k] for k in ("config", "elapsed_s")}
    report = json.loads(canonical_json(report))
    record("completed", t["config"], report, trace_sha)
    out["parity"] = {"status": "completed", "id": pid, "report": report}

    ev = {"parity_run": pid, "trace_artifact": trace_sha, "compilation": comp["id"]}
    if rev["status"] == "oos_evaluated" and report.get("reference_matched"):
        gstore.set_status(lab.con, rev_id, "reference_matched", {"signal_agreement_min": 0.98}, ev)
        rev["status"] = "reference_matched"
    if rev["status"] == "reference_matched" and report["grade"] in ("A", "B") and not report["critical"]:
        gstore.set_status(lab.con, rev_id, "mt5_validated", {"grade": "A|B", "critical": False}, ev)
    out["status"] = gstore.get(lab.con, rev_id)["status"]
    return out
