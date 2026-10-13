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
    assert "input double" not in src and "input int" not in src  # aucune limite exposée en input


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
