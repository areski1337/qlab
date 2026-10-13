import json
import os
from pathlib import Path

import numpy as np
import pytest

from qlab.data import synthetic
from qlab.data.dataset import Bars
from qlab.features import REGISTRY
from qlab.genome import model
from qlab.mql5 import generator, parity
from qlab.mql5.window import feature_window
from qlab.risk.controller import DEFAULT_LIMITS, RiskController

EX = Path(__file__).resolve().parents[2] / "examples" / "genomes"
LIM_SHA = RiskController(DEFAULT_LIMITS).limits_sha256


def rev_of(name):
    g = json.loads((EX / name).read_text(encoding="utf-8"))
    return {"id": "rev_test", "content": g, "semantic_hash": model.semantic_hash(g)}


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_window_convergence(name):
    """Le calcul sur W barres (EA) reproduit le calcul sur historique complet (référence)."""
    b = Bars.from_frame(synthetic.make_bars(12000, seed=21), "S", "M5", content_sha256="x")
    spec = REGISTRY[name]
    p = {k: (v.choices[0] if v.kind == "choice" else v.default) for k, v in spec.params.items()}
    W = feature_window(name, p, "M5")
    full = spec.compute(b, **p)
    for end in (W + 50, len(b) - 1):
        part = spec.compute(b.slice(end - W, end), **p)
        for o in spec.outputs:
            np.testing.assert_allclose(part[o][-1], full[o][end - 1], rtol=1e-9, atol=1e-12, equal_nan=True,
                                       err_msg=f"{name}.{o}")


def test_generation_deterministic_and_traceable():  # AT-014
    rev = rev_of("valid_ict_fvg_killzone.json")
    a = generator.generate(rev, "XAUUSD", "NY+7", DEFAULT_LIMITS, LIM_SHA)
    b = generator.generate(rev, "XAUUSD", "NY+7", DEFAULT_LIMITS, LIM_SHA)
    assert a["sha256"] == b["sha256"]
    src = a["source"]
    assert rev["semantic_hash"] in src and "rev_test" in src and LIM_SHA in src
    assert f"qlab.mql5_generator {generator.GENERATOR_VERSION}" in src
    assert "ACCOUNT_TRADE_MODE_REAL" in src  # refus du compte réel codé en dur
    # aucune limite exposée en input ; le seul input numérique ne peut que réduire le risque (borné à [0,1])
    inputs = [l for l in src.splitlines() if l.startswith("input ")]
    assert [l.split("=")[0].split()[-1] for l in inputs] == ["InpTrace", "InpRunId", "InpRiskScale"]
    assert "MathMax(0.0, MathMin(1.0, InpRiskScale))" in src


def test_unsupported_feature_blocks_export():
    rev = rev_of("valid_ema_trend_rsi.json")
    rev["content"]["entry"]["long"]["children"].append(
        {"id": "n99", "op": "event", "ref": {"feature": "regime", "params": {"trend_period": 50, "confirm": 3},
                                             "output": "bull_trend"}})
    with pytest.raises(generator.UnsupportedForExport, match="regime"):
        generator.generate(rev, "XAUUSD", "NY+7", DEFAULT_LIMITS, LIM_SHA)
    with pytest.raises(generator.UnsupportedForExport, match="fuseau"):
        generator.generate(rev_of("valid_ema_trend_rsi.json"), "XAUUSD", "Europe/Athens", DEFAULT_LIMITS, LIM_SHA)


def test_parse_trace_pairs_deals():
    text = "\n".join([
        "HDR;h;r;100", "FIRST;1000", "SIG;1300;1;0", "ENTRY;1300;1;10.5;9.5;12.5;0.10",
        "DEAL;1;1000;0;0;10.5;0.1;0;-0.3;0;3;77", "DEAL;2;1600;1;1;9.5;0.1;-10;-0.3;0;4;77", "LASTBAR;2000",
    ])
    tr = parity.parse_trace(text, "UTC")
    assert tr["first"] == 1000 and tr["signals"] == {1300: (True, False)}
    assert len(tr["trades"]) == 1 and tr["trades"][0]["out"]["reason"] == 4


@pytest.mark.skipif(os.environ.get("QLAB_MT5_TESTS") != "1", reason="QLAB_MT5_TESTS=1 requis (MetaEditor réel)")
def test_real_metaeditor_compiles_examples(tmp_path):
    from qlab.lab import Lab
    from qlab.genome import store as gstore
    from qlab.mql5 import toolchain
    lab = Lab.open(tmp_path / "d")
    for f in ("valid_ema_trend_rsi.json", "valid_ict_fvg_killzone.json"):
        rev = gstore.create_revision(lab.con, json.loads((EX / f).read_text(encoding="utf-8")))
        ea = toolchain.save_ea(lab, rev, "XAUUSD", "NY+7", DEFAULT_LIMITS, LIM_SHA)
        comp = toolchain.compile_ea(lab, ea)
        assert comp["status"] == "succeeded" and comp["errors"] == 0, comp["diagnostic"]
    lab.close()


def _trace_from_reference(res, bars, sig, i0, drop_trades=0, flip_signals=0):
    """Fabrique une trace au format EA à partir d'un run de référence (fixture de test, pas un run MT5)."""
    tf = bars.tf_s
    lines = [f"FIRST;{int(bars.ts[i0] + tf)}"]
    lg, sh = sig
    flipped = 0
    for i in range(i0, len(bars)):
        l, s = bool(lg[i]), bool(sh[i])
        if (l or s) and flipped < flip_signals:
            l, s, flipped = not l, not s, flipped + 1
        if l or s:
            lines.append(f"SIG;{int(bars.ts[i] + tf)};{int(l)};{int(s)}")
    reason = {"stop": 4, "stop_gap": 4, "target": 5, "target_gap": 5}
    for k, t in enumerate(res["trades"][drop_trades:]):
        comm = -t["commission"] / 2
        lines.append(f"DEAL;{2*k};{t['entry_ts'] + 1};{0 if t['dir'] == 1 else 1};0;{t['entry']};{t['lots']};0;{comm};0;3;{k}")
        lines.append(f"DEAL;{2*k+1};{t['exit_ts'] + 1};{1 if t['dir'] == 1 else 0};1;{t['exit']};{t['lots']};"
                     f"{t['gross']};{comm};{t['swap']};{reason.get(t['reason'], 3)};{k}")
    lines.append(f"LASTBAR;{int(bars.ts[-1])}")
    return "\n".join(lines)


def test_parity_comparator_grades_and_blocks():  # AT-008 (logique de blocage)
    from qlab.backtest import engine
    from qlab.backtest.costs import DEFAULT_COST_PROFILE
    from qlab.data.dataset import Bars
    from qlab.features import FeatureCache
    from qlab.genome.model import signals
    df = synthetic.make_bars(6000, seed=12)
    bars = Bars.from_frame(df, "SYNTH", "M5", spec=synthetic.SYNTHETIC_SPEC, content_sha256="p")
    rev = rev_of("valid_ema_trend_rsi.json")
    rev["content"]["market"] = {"symbol": "SYNTH", "timeframe": "M5"}
    rev["content"]["management"]["max_trades_per_day"] = 10
    cache = FeatureCache(bars)
    risk = RiskController(DEFAULT_LIMITS)
    costs = {**DEFAULT_COST_PROFILE, "commission_per_lot_side": 3.0}
    i0 = 1000
    res = engine.run(rev["content"], cache, {**costs, "spread_mode": "max", "fixed_spread_points": 0}, risk, start=i0)
    assert len(res["trades"]) >= 10
    sig = signals(rev["content"], cache)
    good = parity.compare(parity.parse_trace(_trace_from_reference(res, bars, sig, i0), "UTC"), rev, cache, risk, 10_000, costs)
    assert good["grade"] == "A" and not good["critical"] and good["signals"]["agreement"] == 1.0
    assert good["trades"]["match_ratio"] == 1.0 and good["aggregate"]["net_rel_diff"] < 1e-6
    bad = parity.compare(parity.parse_trace(_trace_from_reference(res, bars, sig, i0, drop_trades=3, flip_signals=5), "UTC"),
                         rev, cache, risk, 10_000, costs)
    assert bad["critical"] and bad["grade"] != "A" and not bad["reference_matched"]
