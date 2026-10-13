import numpy as np
import pandas as pd
import pytest

from qlab.backtest import engine
from qlab.backtest.costs import DEFAULT_COST_PROFILE
from qlab.calendar.windows import NewsWindows, build
from qlab.core.timeutil import iso_to_ts
from qlab.data import synthetic
from qlab.data.dataset import Bars
from qlab.features import FeatureCache
from qlab.risk.controller import DEFAULT_LIMITS, RiskController, load_limits
from test_genome_backtest import SPEC, flat_with_jump, jump_genome

COSTS = {**DEFAULT_COST_PROFILE, "fixed_spread_points": 0}


def bars(df, tf="M5", sym="SYNTH"):
    return Bars.from_frame(df, sym, tf, spec=SPEC, content_sha256="t" + tf)


def m1_from(m5: pd.DataFrame, paths: dict[int, list[tuple]]) -> pd.DataFrame:
    """M1 synthétiques cohérentes avec les M5 ; `paths[i]` remplace les 5 M1 de la barre M5 i par (o,h,l,c)."""
    rows = []
    for i, r in m5.iterrows():
        sub = paths.get(i) or [(r.open, r.high, r.low, r.close)] + [(r.close, r.close, r.close, r.close)] * 4
        for k, (o, h, l, c) in enumerate(sub):
            rows.append({"ts": r.ts + 60 * k, "open": o, "high": h, "low": l, "close": c, "tick_volume": 10,
                         "spread": 0, "real_volume": 0})
    return pd.DataFrame(rows)


def run(g, m5, m1=None, limits=DEFAULT_LIMITS, **kw):
    ctx = {"M1": bars(m1, "M1")} if m1 is not None else {}
    return engine.run(g, FeatureCache(bars(m5), ctx), COSTS, RiskController(limits), **kw)


def ambiguous_df():
    df = flat_with_jump()
    df.loc[13, "high"], df.loc[13, "low"] = 104.5, 100.5  # stop 101 et objectif 104 dans la même M5
    return df


def test_m1_resolves_ambiguous_bar_to_target():
    df = ambiguous_df()
    # dans la barre 13, l'objectif est atteint dès la 1re M1, le stop seulement à la 3e
    m1 = m1_from(df, {13: [(102, 104.5, 101.8, 104.2), (104.2, 104.3, 103, 103), (103, 103, 100.5, 101),
                           (101, 101, 101, 101), (101, 101, 101, 101)]})
    t = run(jump_genome(), df, m1)["trades"][0]
    assert t["reason"] == "target" and not t["ambiguous"]
    t0 = run(jump_genome(), df)["trades"][0]  # sans M1 : convention prudente
    assert t0["reason"] == "stop" and t0["ambiguous"]


def test_residual_ambiguity_inside_m1_conservative_vs_mt5_path():
    df = ambiguous_df()
    m1 = m1_from(df, {13: [(102, 104.5, 100.5, 104.0)] + [(104, 104, 104, 104)] * 4})  # M1 haussière : O-L-H-C
    assert run(jump_genome(), df, m1)["trades"][0]["reason"] == "stop"
    t = run(jump_genome(), df, m1, execution=engine.TESTER_EXECUTION)["trades"][0]
    assert t["reason"] == "stop"  # chemin O-L-H : le bas (stop) avant le haut
    m1b = m1_from(df, {13: [(102, 104.5, 100.5, 101.0)] + [(101, 101, 101, 101)] * 4})  # baissière : O-H-L-C
    assert run(jump_genome(), df, m1b, execution=engine.TESTER_EXECUTION)["trades"][0]["reason"] == "target"


def test_gap_fill_modes():
    df = flat_with_jump()
    df.loc[14, ["open", "high", "low", "close"]] = [99.0, 99.2, 98.8, 99.0]
    assert run(jump_genome(), df)["trades"][0]["exit"] == 99.0
    t = run(jump_genome(), df, execution={"gap_fill": "stop_price"})["trades"][0]
    assert t["exit"] == pytest.approx(101.0) and t["reason"] == "stop_gap"


def test_weekend_close_and_block():
    # 2024-01-05 est un vendredi ; 17:00 NY = 22:00 UTC (hiver)
    start = "2024-01-05T19:00:00Z"
    n = 60
    c = np.full(n, 100.0)
    c[3:] = 102.0  # le prix reste au-dessus du stop jusqu au week-end
    df = synthetic.from_closes(c, start=start, highs=c + 0.1, lows=c - 0.1, opens=np.concatenate([[100.0], c[:-1]]))
    lim = {**DEFAULT_LIMITS, "close_before_weekend_minutes": 60}
    t = run(jump_genome(), df, limits=lim)["trades"][0]
    assert t["reason"] == "weekend_close"
    assert iso_to_ts("2024-01-05T21:00:00Z") <= t["exit_ts"] <= iso_to_ts("2024-01-05T21:05:00Z")
    # signal dans la dernière heure : entrée refusée
    c2 = np.full(n, 100.0)
    c2[30] = 102.0  # 21:30 UTC
    df2 = synthetic.from_closes(c2, start=start, highs=c2 + 0.1, lows=c2 - 0.1, opens=np.concatenate([[100.0], c2[:-1]]))
    res = run(jump_genome(), df2, limits=lim)
    assert res["trades"] == [] and res["skipped"]["risk:weekend_window"] == 1


def test_daily_profit_target_blocks_new_entries():
    n = 80
    c = np.full(n, 100.0)
    for k in (5, 20, 35):
        c[k], c[k + 1:k + 6] = 102.0, 105.0  # chaque entrée touche l'objectif (+2 R)
    df = synthetic.from_closes(c, highs=c + 0.05, lows=c - 0.05, opens=np.concatenate([[100.0], c[:-1]]))
    lim = {**DEFAULT_LIMITS, "daily_profit_target_pct": 1.5}
    res = run(jump_genome(), df, limits=lim)
    assert len(res["trades"]) == 1 and res["skipped"].get("risk:daily_profit_target", 0) >= 1


def test_news_filter_blocks_and_refuses_without_coverage():
    df = flat_with_jump()
    t_entry = int(df["ts"][11])
    lim = {**DEFAULT_LIMITS, "news_filter": {"enabled": True, "before_min": 30, "after_min": 30, "min_volatility": "HIGH"}}
    assert run(jump_genome(), df, limits=lim)["skipped"]["risk:news_data_unavailable"] == 1
    cov = [(int(df["ts"][0]), int(df["ts"].iloc[-1]) + 300)]
    hit = build([{"date_ts": t_entry + 600, "currency": "USD", "volatility": "HIGH"}], cov, {"USD", "XAU"}, 30, 30, "HIGH", "test")
    assert run(jump_genome(), df, limits=lim, news=hit)["skipped"]["risk:news_window"] == 1
    low = build([{"date_ts": t_entry + 600, "currency": "USD", "volatility": "MEDIUM"}], cov, {"USD"}, 30, 30, "HIGH", "test")
    other = build([{"date_ts": t_entry + 600, "currency": "JPY", "volatility": "HIGH"}], cov, {"USD"}, 30, 30, "HIGH", "test")
    assert len(run(jump_genome(), df, limits=lim, news=low)["trades"]) == 1
    assert len(run(jump_genome(), df, limits=lim, news=other)["trades"]) == 1


def test_tentative_event_blocks_whole_day():
    w = build([{"date_ts": iso_to_ts("2024-03-01T15:00:00Z"), "currency": "USD", "volatility": "HIGH", "is_tentative": True}],
              [(0, 2**40)], {"USD"}, 30, 30, "HIGH", "t")
    assert w.blocked_at(iso_to_ts("2024-03-01T01:00:00Z")) and not w.blocked_at(iso_to_ts("2024-03-02T01:00:00Z"))


def test_limits_validation():
    import json
    from pathlib import Path
    import tempfile
    p = Path(tempfile.mkdtemp()) / "l.json"
    p.write_text(json.dumps({"news_filter": {"min_volatility": "EXTREME"}}))
    with pytest.raises(ValueError):
        load_limits(p)
    p.write_text(json.dumps({"news_filter": {"enabled": True}}))
    assert load_limits(p)["news_filter"]["before_min"] == 30  # valeurs par défaut complétées
