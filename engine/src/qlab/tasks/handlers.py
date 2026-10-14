"""Handlers des tâches longues (exécutées par le worker, jamais dans la requête HTTP)."""
from __future__ import annotations

import datetime as dt

from ..backtest.costs import DEFAULT_COST_PROFILE
from ..data import dataset, mt5_source, synthetic, tz
from ..features import FeatureCache
from ..genome import store as gstore
from ..risk.controller import RiskController, load_limits
from ..validation import pipeline, protocol as proto
from .runner import handler


def cache_for(lab, dsv: str, context: dict | None) -> FeatureCache:
    from ..calendar.store import windows_for
    c = FeatureCache(dataset.load_bars(lab, dsv), {tf: dataset.load_bars(lab, v) for tf, v in (context or {}).items()})
    c.news = windows_for(lab, c.bars.spec, load_limits(lab.paths.risk_limits))
    return c


def _risk(lab):
    lim = load_limits(lab.paths.risk_limits)
    return lim, RiskController(lim)


@handler("import_mt5")
def import_mt5(lab, task):
    p = task["payload"]
    out = []
    for tf in p["timeframes"]:
        raw, spec, ctx = mt5_source.fetch_rates(p["symbol"], tf, dt.datetime.fromisoformat(p["from"]),
                                                dt.datetime.fromisoformat(p["to"]), lab.settings["mt5"]["terminal_path"])
        chk = tz.check_profile(p["tz_profile"], ctx["last_tick_server_ts"], ctx["observed_at_utc"]) \
            if ctx["last_tick_server_ts"] else {"consistent": None, "note": "aucun tick récent : profil non vérifiable"}
        if chk["consistent"] is False:
            raise ValueError(f"profil de fuseau {p['tz_profile']} incohérent avec l'heure serveur observée : {chk}")
        v = dataset.import_bars(lab, source="mt5", broker=ctx["server"], source_symbol=p["symbol"],
                                canonical_symbol=p.get("canonical_symbol", p["symbol"]), timeframe=tf, raw=raw, spec=spec,
                                tz_profile=p["tz_profile"], provenance={**ctx, "tz_check": chk})
        out.append({"timeframe": tf, "version_id": v["id"], "n_bars": v["n_bars"], "tz_check": chk})
    return {"versions": out}


@handler("import_synthetic")
def import_synthetic(lab, task):
    p = task["payload"]
    v = dataset.import_bars(lab, source="synthetic", broker=None, source_symbol=p.get("symbol", "SYNTH_XAU"),
                            canonical_symbol=p.get("symbol", "SYNTH_XAU"), timeframe=p.get("timeframe", "M5"),
                            raw=synthetic.make_bars(int(p["n"]), p.get("timeframe", "M5"), int(p["seed"])),
                            spec=synthetic.SYNTHETIC_SPEC, tz_profile="UTC",
                            provenance={"generator": "qlab.data.synthetic.make_bars", "seed": p["seed"]}, synthetic=True)
    return {"version_id": v["id"], "n_bars": v["n_bars"]}


@handler("backtest")
def backtest(lab, task):
    p = task["payload"]
    rev = gstore.get(lab.con, p["revision_id"])
    cache = cache_for(lab, p["dataset_version_id"], p.get("context"))
    _, risk = _risk(lab)
    costs = p.get("cost_profile") or DEFAULT_COST_PROFILE
    seg = p.get("segment", "research")
    window = None
    if seg == "research":
        s = proto.segments_for(lab, cache.bars)
        window = (s["train"][0], s["validation"][1])
    ev = proto.evaluate(lab, rev, cache, costs, risk, seg, window=window, store_trades=True)
    return {"evaluation_id": ev["id"], "metrics": ev["metrics"], "trades_artifact": ev["trades_artifact"]}


@handler("advance")
def advance(lab, task):
    p = task["payload"]
    cache = cache_for(lab, p["dataset_version_id"], p.get("context"))
    _, risk = _risk(lab)
    transfer = {sym: cache_for(lab, v, {}) for sym, v in (p.get("transfer_datasets") or {}).items()}
    return pipeline.advance(lab, p["revision_id"], cache, p.get("cost_profile") or DEFAULT_COST_PROFILE, risk,
                            campaign_id=p.get("campaign_id"), stop_at=p.get("stop_at", "oos_evaluated"),
                            transfer_caches=transfer)


@handler("final_test")
def final_test(lab, task):
    p = task["payload"]
    rev = gstore.get(lab.con, p["revision_id"])
    cache = cache_for(lab, p["dataset_version_id"], p.get("context"))
    _, risk = _risk(lab)
    ev = proto.evaluate(lab, rev, cache, p.get("cost_profile") or DEFAULT_COST_PROFILE, risk, "final", allow_final=True)
    w = proto.segments_for(lab, cache.bars)["final"]
    return {"evaluation_id": ev["id"], "metrics": ev["metrics"], "holdout": proto.holdout_usage(lab, cache.bars.version_id, w)}


@handler("mt5_verify")
def mt5_verify(lab, task):
    from ..mql5 import verify
    p = task["payload"]
    cache = cache_for(lab, p["dataset_version_id"], p.get("context"))
    lim, risk = _risk(lab)
    tzp = lab.con.execute("SELECT source_timezone FROM dataset_versions WHERE id=?", (p["dataset_version_id"],)).fetchone()[0]
    out = verify.verify(lab, p["revision_id"], cache, risk, lim, tzp, p["from"], p["to"],
                        p.get("cost_profile") or DEFAULT_COST_PROFILE, model=int(p.get("model", 1)))
    rep = (out.get("parity") or {}).get("report") or {}
    return {"compilation": {k: out["compilation"][k] for k in ("id", "status", "errors", "warnings", "diagnostic")},
            "parity": {k: v for k, v in (out.get("parity") or {}).items() if k != "report"},
            "grade": rep.get("grade"), "critical": rep.get("critical"), "status": out.get("status")}


@handler("export")
def export(lab, task):
    from ..passport.build import export_bundle
    return export_bundle(lab, task["payload"]["revision_id"])


@handler("calendar_refresh")
def calendar_refresh(lab, task):
    from ..calendar import store
    from ..demo.monitor import publish_news_files
    p = task["payload"]
    out = store.refresh(lab, int(p["start"]), int(p["end"]))
    out["news_files"] = publish_news_files(lab)
    return out


@handler("backup")
def backup(lab, task):
    from ..storage.backup import create_backup
    return {"path": str(create_backup(lab.con, lab.paths))}


@handler("demo_observe")
def demo_observe(lab, task):
    from ..demo import monitor
    return monitor.observe(lab, task["payload"]["deployment_id"])


@handler("engine_experiment")
def engine_experiment(lab, task):
    from ..evolution.meta import run_task
    return run_task(lab, task)
