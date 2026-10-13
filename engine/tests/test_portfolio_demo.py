import json
import random

import numpy as np
import pandas as pd
import pytest

from qlab.demo import monitor
from qlab.portfolio import engine as pe


def test_bounded_weights():
    w = pe.bounded(np.array([10.0, 1.0, 1.0, 0.0]), 0.05, 0.5)
    assert abs(w.sum() - 1) < 1e-9 and w.max() <= 0.5 + 1e-12 and w.min() >= 0.05 - 1e-12
    with pytest.raises(ValueError):
        pe.bounded(np.ones(3), 0.4, 0.5)  # 3 × 0,4 > 1 : infaisable


def test_adaptive_never_exceeds_cap():
    rng = np.random.default_rng(0)
    R = pd.DataFrame({"a": rng.normal(0.01, 0.001, 50), "b": rng.normal(-0.01, 0.001, 50), "c": rng.normal(0, 0.001, 50)})
    w = np.array([0.4, 0.3, 0.3])
    for _ in range(100):  # « a » surperforme indéfiniment : son poids reste borné
        w = pe.adaptive(w, R, band=0.25, w_min=0.1, w_max=0.5)
        assert w.max() <= 0.5 + 1e-12
    assert w[0] == pytest.approx(0.5)


def test_min_corr_prefers_complementary():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 0.01, 300)
    R = pd.DataFrame({"a": x, "b": x + rng.normal(0, 0.001, 300), "c": rng.normal(0, 0.01, 300)})
    w, _ = pe.allocate(R, "min_corr", 0.05, 0.9)
    assert w[2] > w[0] and w[2] > w[1]  # la stratégie décorrélée reçoit plus de poids


def test_analyze_outputs():
    rng = np.random.default_rng(2)
    R = pd.DataFrame({"a": rng.normal(0.001, 0.01, 200), "b": rng.normal(0.001, 0.01, 200)})
    meta = {k: {"symbol": "XAUUSD", "currency_base": "XAU", "currency_profit": "USD", "long_share": 1.0,
                "entry_days": {1, 2, 3}, "costs": {"commission": -10}} for k in "ab"}
    rep = pe.analyze(R, np.array([0.5, 0.5]), meta)
    assert rep["exposure_by_instrument"] == {"XAUUSD": 1.0}
    assert rep["net_exposure_by_currency"]["XAU"] == pytest.approx(1.0)
    assert rep["signal_overlap_jaccard"]["a|b"] == 1.0
    assert sum(rep["marginal_risk_contribution"].values()) == pytest.approx(1.0)


def test_ks_detects_shift():
    rng = np.random.default_rng(3)
    _, p_same = monitor.ks_2samp(rng.normal(0, 1, 300), rng.normal(0, 1, 300))
    _, p_diff = monitor.ks_2samp(rng.normal(0, 1, 300), rng.normal(1, 1, 300))
    assert p_same > 0.01 and p_diff < 1e-6


def test_degradation_alerts():
    rng = np.random.default_rng(4)
    ref = [{"r": r, "pnl": r * 100, "lots": 0.1, "costs": -0.6} for r in rng.normal(0.3, 1, 300)]
    good = [{"r": r, "pnl": r * 100, "lots": 0.1, "costs": -0.6} for r in rng.normal(0.3, 1, 30)]
    bad = [{"r": r, "pnl": r * 100, "lots": 0.1, "costs": -2.0} for r in rng.normal(-1.0, 1, 30)]
    assert monitor.degradation(ref, good, 20.0, 10_000)["alerts"] == []
    al = monitor.degradation(ref, bad, 5.0, 10_000)["alerts"]
    assert any("expectancy" in a for a in al) and any("coûts" in a for a in al)
    few = monitor.degradation(ref, good[:5], 20.0, 10_000)
    assert "non évaluable" in few["checks"]["expectancy_r"]["note"]


def test_demo_cycle(tmp_path, monkeypatch):
    from pathlib import Path
    from qlab.backtest.costs import DEFAULT_COST_PROFILE
    from qlab.core.ids import new_id
    from qlab.data import dataset, synthetic
    from qlab.features import FeatureCache
    from qlab.genome import store as gstore
    from qlab.lab import Lab
    from qlab.mql5 import toolchain
    from qlab.risk.controller import DEFAULT_LIMITS, RiskController
    from qlab.validation import protocol as proto
    lab = Lab.open(tmp_path / "d")
    v = dataset.import_bars(lab, source="synthetic", broker=None, source_symbol="S", canonical_symbol="S", timeframe="M5",
                            raw=synthetic.make_bars(20000, seed=6), spec=synthetic.SYNTHETIC_SPEC, tz_profile="UTC",
                            provenance={}, synthetic=True)
    ex = Path(__file__).resolve().parents[2] / "examples" / "genomes" / "valid_ema_trend_rsi.json"
    g = json.loads(ex.read_text(encoding="utf-8"))
    g["market"] = {"symbol": "S", "timeframe": "M5"}
    g["management"]["max_trades_per_day"] = 10
    rev = gstore.create_revision(lab.con, g)
    risk = RiskController(DEFAULT_LIMITS)
    proto.evaluate(lab, rev, FeatureCache(dataset.load_bars(lab, v["id"])),
                   {**DEFAULT_COST_PROFILE, "fixed_spread_points": 30}, risk, "oos", store_trades=True)
    with pytest.raises(PermissionError):
        monitor.register(lab, rev["id"])  # statut insuffisant
    for s in gstore.LADDER[1:7]:  # échelle franchie avec des preuves de test (fixture, pas une validation réelle)
        gstore.set_status(lab.con, rev["id"], s, {"fixture": True}, {"test": s})
    ea = toolchain.save_ea(lab, gstore.get(lab.con, rev["id"]), "S", "UTC", DEFAULT_LIMITS, risk.limits_sha256)
    lab.con.execute("INSERT INTO compilation_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id("comp"), ea["id"], "succeeded", 0, 0, 0, "fixture", None, None, "fixture de test", "2026"))
    dep = monitor.register(lab, rev["id"])
    assert dep["risk_stage"] == 0.25
    flags = tmp_path / "flags"
    flags.mkdir()
    monkeypatch.setattr(monitor, "flag_path", lambda lab, magic=None: flags / f"suspend_{magic}.flag")
    rng = np.random.default_rng(1)
    bad = [{"pnl": -100.0, "costs": -1.0, "lots": 0.1, "r": float(r)} for r in rng.normal(-2, 0.3, 25)]
    obs = monitor.observe(lab, dep["id"], live=bad, account={"server": "Test-Demo", "account_masked": "***123"})
    assert obs["alerts"] and (flags / f"suspend_{dep['magic']}.flag").exists()
    assert gstore.get(lab.con, rev["id"])["status"] == "quarantined"
    with pytest.raises(PermissionError):
        monitor.promote_stage(lab, dep["id"])
    lab.close()
