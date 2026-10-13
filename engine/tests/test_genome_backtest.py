import copy
import json
from pathlib import Path

import numpy as np
import pytest

from qlab.backtest import engine
from qlab.backtest.costs import DEFAULT_COST_PROFILE, CostError
from qlab.data import synthetic
from qlab.data.dataset import Bars
from qlab.features import FeatureCache
from qlab.genome import model
from qlab.metrics.core import compute
from qlab.risk.controller import DEFAULT_LIMITS, RiskController

EX = Path(__file__).resolve().parents[2] / "examples" / "genomes"
SPEC = synthetic.SYNTHETIC_SPEC
COSTS = {**DEFAULT_COST_PROFILE, "fixed_spread_points": 0}


def load(name):
    return json.loads((EX / name).read_text(encoding="utf-8"))


def mk_bars(df, tf="M5"):
    return Bars.from_frame(df, "SYNTH", tf, spec=SPEC, content_sha256="t")


def jump_genome(threshold=1.0, **exit_kw):
    """Long quand la variation sur 1 barre dépasse `threshold` % (déclencheur contrôlable)."""
    ex = {"stop": {"type": "points", "points": 100}, "target": {"type": "rr", "rr": 2.0}, "break_even": None,
          "trailing": None, "time_stop_bars": None, "exit_on_opposite": False}
    ex.update(exit_kw)
    return {"schema": "qlab.genome/1.0", "market": {"symbol": "SYNTH", "timeframe": "M5"},
            "entry": {"long": {"id": "n1", "op": "compare",
                               "left": {"feature": "momentum", "params": {"period": 1}, "output": "roc"},
                               "cmp": "gt", "right": {"const": threshold}}, "short": None},
            "exit": ex, "sizing": {"risk_pct": 1.0}, "management": {"max_trades_per_day": 10, "cooldown_bars": 0}}


def run(g, df, costs=COSTS, limits=DEFAULT_LIMITS, **kw):
    return engine.run(g, FeatureCache(mk_bars(df)), costs, RiskController(limits), **kw)


# ---------- génome ----------

def test_examples_valid():
    for f in ("valid_ema_trend_rsi.json", "valid_ict_fvg_killzone.json"):
        assert model.validate(load(f)) == [], f


def test_invalid_genomes_rejected_with_diagnostic():  # AT-002
    errs = model.validate(load("invalid_type_mismatch.json"))
    assert any("types incompatibles osc100 vs price" in e for e in errs)
    errs = model.validate(load("invalid_code_injection.json"))
    assert errs and any("mql5" in e or "Additional properties" in e for e in errs)


@pytest.mark.parametrize("mutate,expect", [
    (lambda g: g["entry"].update(long=None, short=None), "aucune règle d'entrée"),
    (lambda g: g["entry"]["long"]["children"][1]["right"].update(const=150), "hors de 0..100"),
    (lambda g: g["entry"]["long"]["children"][0]["left"]["params"].update(period=1), "period"),
    (lambda g: g["entry"]["long"]["children"][2].update(id="n2"), "dupliqués"),
    (lambda g: g["entry"]["long"]["children"][0]["left"].update(output="nope"), "sortie « nope »"),
    (lambda g: g["entry"]["long"]["children"][2]["ref"].update(feature="rsi", params={"period": 14}, output="value"),
     "exige une sortie bool"),
])
def test_semantic_errors(mutate, expect):
    g = load("valid_ema_trend_rsi.json")
    mutate(g)
    errs = model.validate(g)
    assert any(expect in e for e in errs), errs


def test_semantic_hash_ignores_node_ids():
    g = load("valid_ema_trend_rsi.json")
    h = copy.deepcopy(g)
    h["entry"]["long"]["id"] = "n99"
    assert model.semantic_hash(g) == model.semantic_hash(h)
    h["sizing"]["risk_pct"] = 0.6
    assert model.semantic_hash(g) != model.semantic_hash(h)


def test_describe_is_readable():
    d = model.describe(load("valid_ict_fvg_killzone.json"))
    assert "fvg(min_atr=0.3,expiry=60).bull_retest" in d["entrée long"]
    assert "[H1]" in d["entrée long"]


# ---------- moteur ----------

def flat_with_jump(n=60, jump_at=10, after=None):
    c = np.full(n, 100.0)
    c[jump_at:] = 102.0
    if after:
        for i, v in after.items():
            c[i] = v
    return synthetic.from_closes(c, highs=c + 0.1, lows=c - 0.1, opens=np.concatenate([[100.0], c[:-1]]))


def test_entry_at_next_open_after_signal():  # AT-001 (exécution)
    df = flat_with_jump()
    res = run(jump_genome(time_stop_bars=5), df)
    t = res["trades"][0]
    assert t["signal_i"] == 10 and t["entry_i"] == 11 and t["entry"] == df["open"][11]


def test_stop_and_target_same_bar_takes_stop():
    df = flat_with_jump()
    # barre 13 : low touche le stop (102-1.0) et high touche l'objectif (102+2.0)
    df.loc[13, "high"], df.loc[13, "low"] = 104.5, 100.5
    t = run(jump_genome(), df)["trades"][0]
    assert t["reason"] == "stop" and t["ambiguous"] and t["exit"] == pytest.approx(101.0)


def test_gap_through_stop_fills_at_open():
    df = flat_with_jump()
    df.loc[14, ["open", "high", "low", "close"]] = [99.0, 99.2, 98.8, 99.0]
    t = run(jump_genome(), df)["trades"][0]
    assert t["reason"] == "stop_gap" and t["exit"] == 99.0  # pire que le stop à 101


def test_commission_and_spread_reduce_pnl():  # AT-006
    df = flat_with_jump()
    base = run(jump_genome(time_stop_bars=5), df)["trades"][0]
    costly = run(jump_genome(time_stop_bars=5), df,
                 costs={**COSTS, "fixed_spread_points": 20, "commission_per_lot_side": 3.0})["trades"][0]
    assert costly["commission"] == pytest.approx(6.0 * costly["lots"])
    assert costly["entry"] == pytest.approx(base["entry"] + 20 * SPEC["point"])
    assert costly["pnl"] < base["pnl"]


def test_unknown_spread_is_refused():
    df = flat_with_jump()
    with pytest.raises(CostError):
        run(jump_genome(), df, costs={**DEFAULT_COST_PROFILE, "fixed_spread_points": None})


def test_genome_cannot_exceed_absolute_risk():  # AT-009
    g = jump_genome(time_stop_bars=5)
    g["sizing"]["risk_pct"] = 50.0
    res = run(g, flat_with_jump())
    assert res["risk_pct_effective"] == DEFAULT_LIMITS["max_risk_per_trade_pct"]
    t = res["trades"][0]
    assert t["risk_amount"] <= 10_000 * 0.01 + 1e-9


def test_lots_never_forced_to_minimum():
    g = jump_genome(time_stop_bars=5)
    g["sizing"]["risk_pct"] = 0.0001  # 0.01 $ de risque : en dessous du lot minimum
    res = run(g, flat_with_jump())
    assert res["trades"] == [] and res["skipped"]["lots_below_min"] >= 1


def test_daily_loss_limit_blocks_entries():
    n = 80
    c = np.full(n, 100.0)
    for k in range(5, 75, 6):  # sauts répétés puis retour à 100 : chaque entrée touche son stop (-1 R) ; 3 pertes composées = 2,97 % >= 2 %
        c[k] = 102.0
    df = synthetic.from_closes(c, highs=c + 0.05, lows=c - 0.05, opens=np.concatenate([[100.0], c[:-1]]))
    lim = {**DEFAULT_LIMITS, "max_daily_loss_pct": 2.0}
    res = run(jump_genome(), df, limits=lim)
    assert res["skipped"].get("risk:daily_loss_limit", 0) >= 1
    assert len(res["trades"]) == 3 and all(t["reason"] == "stop" for t in res["trades"])


def test_deterministic_and_metrics_sane():
    df = synthetic.make_bars(6000, seed=3)
    g = load("valid_ema_trend_rsi.json")
    g["market"] = {"symbol": "SYNTH", "timeframe": "M5"}
    a, b = run(g, df, costs={**COSTS, "fixed_spread_points": 30}), run(g, df, costs={**COSTS, "fixed_spread_points": 30})
    assert a["trades"] == b["trades"]
    m = compute(a)
    assert m["n_trades"] == len(a["trades"]) > 0
    assert m["net_profit"] == pytest.approx(a["final_equity"] - a["initial_equity"])
    assert m["profit_factor"] is None or m["profit_factor"] >= 0


def test_metrics_no_trades_are_none():
    m = compute({"trades": [], "initial_equity": 1000, "final_equity": 1000, "skipped": {}, "halted": None})
    assert m["profit_factor"] is None and m["sharpe"] is None
