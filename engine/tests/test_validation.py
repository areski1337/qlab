import json
import math
from pathlib import Path

import numpy as np
import pytest

from qlab.backtest.costs import DEFAULT_COST_PROFILE
from qlab.data import dataset, synthetic
from qlab.features import FeatureCache
from qlab.genome import store as gstore
from qlab.lab import Lab
from qlab.risk.controller import DEFAULT_LIMITS, RiskController
from qlab.validation import pipeline, protocol as proto, robustness

EX = Path(__file__).resolve().parents[2] / "examples" / "genomes"
COSTS = {**DEFAULT_COST_PROFILE, "fixed_spread_points": 30}


@pytest.fixture
def env(tmp_path):
    lab = Lab.open(tmp_path / "d")
    v = dataset.import_bars(lab, source="synthetic", broker=None, source_symbol="SYNTH", canonical_symbol="SYNTH",
                            timeframe="M5", raw=synthetic.make_bars(30000, seed=8), spec=synthetic.SYNTHETIC_SPEC,
                            tz_profile="UTC", provenance={}, synthetic=True)
    bars = dataset.load_bars(lab, v["id"])
    g = json.loads((EX / "valid_ema_trend_rsi.json").read_text(encoding="utf-8"))
    g["market"] = {"symbol": "SYNTH", "timeframe": "M5"}
    g["management"]["max_trades_per_day"] = 10
    rev = gstore.create_revision(lab.con, g)
    yield lab, FeatureCache(bars), rev
    lab.close()


def test_segments_chronological_no_overlap():
    s = proto.segments(1000)
    assert s["train"] == (0, 500) and s["validation"] == (500, 700) and s["oos"] == (700, 850) and s["final"] == (850, 1000)
    for f in proto.walk_forward(1000):
        assert f["test"][1] <= 700  # jamais dans oos/final


def test_final_segment_guarded(env):
    lab, cache, rev = env
    risk = RiskController(DEFAULT_LIMITS)
    with pytest.raises(PermissionError):
        proto.evaluate(lab, rev, cache, COSTS, risk, "final")
    ev = proto.evaluate(lab, rev, cache, COSTS, risk, "final", allow_final=True)
    assert ev["trades_artifact"]  # résultat final toujours traçable
    w = proto.segments(len(cache.bars))["final"]
    assert proto.holdout_usage(lab, cache.bars.version_id, w) == {"revisions_evaluated": 1, "independent": True}


def test_evaluation_cache_and_invalidation(env):  # AT-005
    lab, cache, rev = env
    risk = RiskController(DEFAULT_LIMITS)
    a = proto.evaluate(lab, rev, cache, COSTS, risk, "train")
    b = proto.evaluate(lab, rev, cache, COSTS, risk, "train")
    assert b["cached"] and a["id"] == b["id"]
    c = proto.evaluate(lab, rev, cache, {**COSTS, "commission_per_lot_side": 1.0}, risk, "train")
    assert not c["cached"] and c["id"] != a["id"]
    d = proto.evaluate(lab, rev, cache, COSTS, RiskController({**DEFAULT_LIMITS, "max_daily_loss_pct": 3.0}), "train")
    assert not d["cached"]


def test_oos_result_traceable_to_source(env):  # AT-007
    lab, cache, rev = env
    ev = proto.evaluate(lab, rev, cache, COSTS, RiskController(DEFAULT_LIMITS), "oos", store_trades=True)
    row = lab.con.execute("SELECT e.*, v.content_sha256, v.raw_artifact_sha256, v.file_relpath FROM evaluations e "
                          "JOIN dataset_versions v ON v.id=e.dataset_version_id WHERE e.id=?", (ev["id"],)).fetchone()
    assert row["content_sha256"] == cache.bars.content_sha256
    assert lab.store.get_bytes(row["raw_artifact_sha256"])  # données brutes d'origine récupérables
    trades = lab.store.get_json(row["trades_artifact"])["trades"]
    w = json.loads(row["window_json"])
    assert all(w[0] <= t["entry_i"] < w[1] for t in trades)
    assert json.loads(row["versions_json"])["backtester_reference"]


def test_deflated_sharpe_penalizes_many_trials():
    few = robustness.deflated_sharpe(1.5, 500, 0.0, 3.0, [0.1, 1.5])
    many = robustness.deflated_sharpe(1.5, 500, 0.0, 3.0, list(np.random.default_rng(0).normal(0, 1, 5000)))
    assert few["dsr"] > many["dsr"]
    assert robustness.deflated_sharpe(None, 500, 0, 3, [1, 2])["available"] is False


def test_monte_carlo_reproducible():
    trades = [{"pnl": p} for p in np.random.default_rng(1).normal(5, 50, 100)]
    a, b = robustness.monte_carlo(trades, 10000, seed=3), robustness.monte_carlo(trades, 10000, seed=3)
    assert a == b and a["bootstrap_max_dd_pct"]["p5"] <= a["bootstrap_max_dd_pct"]["p95"]


def test_pipeline_records_evidence_or_rejects(env):
    lab, cache, rev = env
    out = pipeline.advance(lab, rev["id"], cache, COSTS, RiskController(DEFAULT_LIMITS))
    trs = gstore.transitions(lab.con, rev["id"])
    assert trs and all(t["evidence"] for t in trs)
    # Sur une marche aléatoire synthétique, aucune stratégie ne devrait atteindre oos_evaluated sans chance.
    assert out["status"] in ("rejected", "oos_evaluated")
    if out["status"] == "rejected":
        assert trs[-1]["to_status"] == "rejected" and trs[-1]["criteria"]["reason"]


def test_walk_forward_reopt(env):
    lab, cache, rev = env
    rep = robustness.walk_forward_reopt(rev["content"], cache, COSTS, RiskController(DEFAULT_LIMITS),
                                        proto.DEFAULT_PROTOCOL, n_trials=6, seed=1)
    assert len(rep["folds"]) == 4
    seg = proto.segments(len(cache.bars))
    for f in rep["folds"]:
        assert f["fit"][1] == f["test"][0] and f["test"][1] <= seg["validation"][1]  # jamais oos/final
        assert f["candidates"] >= 1
    again = robustness.walk_forward_reopt(rev["content"], cache, COSTS, RiskController(DEFAULT_LIMITS),
                                          proto.DEFAULT_PROTOCOL, n_trials=6, seed=1)
    assert again == rep  # reproductible à graine fixe
