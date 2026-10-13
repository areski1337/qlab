import numpy as np
import pytest

from qlab.data import synthetic
from qlab.data.dataset import Bars
from qlab.features import REGISTRY, FeatureCache
from qlab.features.sessions import in_session, trading_day
from qlab.core.timeutil import iso_to_ts


def bars_from(df, tf="M5"):
    return Bars.from_frame(df, "SYNTH", tf, content_sha256="test")


def default_params(spec):
    return {k: (p.choices[0] if p.kind == "choice" else p.default) for k, p in spec.params.items()}


@pytest.fixture(scope="module")
def bars():
    return bars_from(synthetic.make_bars(3000, seed=11))


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_no_lookahead_by_truncation(bars, name):  # AT-001
    spec = REGISTRY[name]
    params = default_params(spec)
    full = spec.compute(bars, **params)
    for cut in (400, 1234, 2999):
        part = spec.compute(bars.slice(0, cut), **params)
        for out, arr in part.items():
            np.testing.assert_array_equal(arr, full[out][:cut], err_msg=f"{name}.{out} dépend du futur (cut={cut})")


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_outputs_declared(bars, name):
    spec = REGISTRY[name]
    out = spec.compute(bars, **default_params(spec))
    assert set(out) == set(spec.outputs)
    assert all(len(v) == len(bars) for v in out.values())


def test_fvg_reference():
    # A(i=1) high 10.5 ; C(i=3) low 11 > 10.5 → FVG haussier créé à i=3 ; retest à i=5 (low 10.8 dans [10.5, 11]).
    highs = [10.2, 10.5, 12.0, 12.5, 12.3, 12.0, 12.4]
    lows = [9.8, 10.0, 10.6, 11.0, 11.5, 10.8, 11.6]
    closes = [10.0, 10.3, 11.8, 12.2, 11.9, 11.5, 12.3]
    b = bars_from(synthetic.from_closes(closes, highs=highs, lows=lows))
    out = REGISTRY["fvg"].compute(b, min_atr=0.0, expiry=50)
    assert np.flatnonzero(out["new_bull"]).tolist() == [2, 3]  # i=2 : low 10.6 > high(0)=10.2 aussi
    assert out["bull_retest"][5] == 1 and out["bull_retest"][:5].sum() == 0


def test_pivot_confirmed_only_after_right_bars():
    highs = [1, 2, 3, 9, 3, 2, 1, 1, 1]
    b = bars_from(synthetic.from_closes([h - 0.5 for h in highs], highs=highs, lows=[h - 1 for h in highs]))
    out = REGISTRY["swings"].compute(b, left=2, right=2)
    assert np.isnan(out["last_high"][4])     # pivot en 3 pas encore confirmé
    assert out["last_high"][5] == 9 and out["new_high"][5] == 1


def test_bos_and_choch_reference():
    # swing high 9 (i=3) confirmé en i=5 ; cassure en clôture à i=7 → BOS haussier.
    closes = [5, 6, 7, 8.5, 7, 6, 7, 9.5, 9, 8]
    highs = [5.2, 6.2, 7.2, 9, 7.2, 6.2, 7.2, 9.7, 9.2, 8.2]
    lows = [c - 0.4 for c in closes]
    b = bars_from(synthetic.from_closes(closes, highs=highs, lows=lows))
    out = REGISTRY["structure"].compute(b, left=2, right=2, break_on="close", disp_atr=0.0)
    assert np.flatnonzero(out["bos_up"]).tolist() == [7]
    assert out["trend"][7] == 1 and out["choch_up"].sum() == 0  # pas de tendance baissière antérieure


def test_sessions_follow_dst():
    # London KZ = 02:00-05:00 New York. Hiver : 07:00-10:00 UTC ; été : 06:00-09:00 UTC.
    winter = iso_to_ts("2026-01-14T06:30:00Z")
    summer = iso_to_ts("2026-07-14T06:30:00Z")
    r = in_session(np.array([winter, summer]), "london_kz")
    assert r.tolist() == [False, True]


def test_trading_day_rolls_at_17_ny():
    a = iso_to_ts("2026-07-14T20:59:00Z")  # 16:59 NY
    c = iso_to_ts("2026-07-14T21:00:00Z")  # 17:00 NY
    d = trading_day(np.array([a, c]))
    assert d[1] == d[0] + 1


def test_vwap_real_volume_unavailable_is_nan(bars):
    out = REGISTRY["vwap"].compute(bars, anchor="day", volume="real", dev=1.0)
    assert np.isnan(out["vwap"]).all()


def test_cache_key_changes_with_version(bars, monkeypatch):  # AT-005
    c = FeatureCache(bars)
    k1 = c.key("ema", {"period": 20}, None)
    import dataclasses
    monkeypatch.setitem(REGISTRY, "ema", dataclasses.replace(REGISTRY["ema"], version="9.9"))
    assert c.key("ema", {"period": 20}, None) != k1
    assert c.key("ema", {"period": 21}, None) != k1


def _bars_at(start, closes, highs, lows, tf="M5", sym="S"):
    return Bars.from_frame(synthetic.from_closes(closes, start=start, highs=highs, lows=lows, timeframe=tf), sym, tf,
                           content_sha256=sym + start)


def test_judas_reference():
    # 2024-01-09 (hiver) : asia_kz = 01:00-05:00 UTC ; london_kz = 07:00-10:00 UTC. Barres M5 à partir de 22:00 UTC (17:00 NY).
    start = "2024-01-08T22:00:00Z"
    n = 12 * 12  # 12 heures
    c = np.full(n, 100.0)
    h, l = c + 0.2, c - 0.2
    ts0 = iso_to_ts(start)
    k = lambda iso: (iso_to_ts(iso) - ts0) // 300
    h[k("2024-01-09T02:00:00Z")], l[k("2024-01-09T03:00:00Z")] = 101.0, 99.0  # range asiatique [99, 101]
    i = k("2024-01-09T07:30:00Z")
    l[i], c[i] = 98.5, 99.5  # balayage du bas asiatique puis clôture dedans
    b = _bars_at(start, c, h, l)
    out = REGISTRY["judas"].compute(b, sweep_atr=0.0)
    assert np.flatnonzero(out["judas_bull"]).tolist() == [i] and out["judas_bear"].sum() == 0
    assert out["asian_low"][i] == 99.0 and np.isnan(out["asian_low"][k("2024-01-09T03:00:00Z")])  # incomplet en session


def test_po3_reference():
    start = "2024-01-08T22:00:00Z"
    n = 12 * 14
    ts0 = iso_to_ts(start)
    k = lambda iso: (iso_to_ts(iso) - ts0) // 300
    c = np.full(n, 100.0)
    h, l = c + 0.1, c - 0.1
    m = k("2024-01-09T05:00:00Z")  # minuit NY (hiver) = 05:00 UTC
    l[m + 3] = 97.0                # manipulation baissière
    c[m + 6] = 100.5               # clôture au-dessus de l'ouverture de minuit → distribution haussière
    b = _bars_at(start, c, h, l)
    out = REGISTRY["po3"].compute(b, manip_atr=0.5)
    assert np.isnan(out["midnight_open"][m - 1]) and out["midnight_open"][m] == 100.0
    assert out["po3_bull"][m + 5] == 0 and out["po3_bull"][m + 6] == 1 and out["po3_bull"][-1] == 1


def test_smt_with_reference_and_no_lookahead():
    base = synthetic.make_bars(3000, seed=31)
    ref = synthetic.make_bars(3000, seed=32)
    ref["ts"] = base["ts"]
    b = Bars.from_frame(base, "A", "M5", content_sha256="a")
    r = Bars.from_frame(ref, "B", "M5", content_sha256="b")
    full = REGISTRY["smt"].compute(b, ref="B", lookback=20, _ctx={"SYM:B": r})
    assert full["bull"].sum() > 0 and full["bear"].sum() > 0
    part = REGISTRY["smt"].compute(b.slice(0, 1500), ref="B", lookback=20, _ctx={"SYM:B": r})
    np.testing.assert_array_equal(part["bull"], full["bull"][:1500])
    # la référence ne fait pas de plus bas quand le marché en fait un
    i = int(np.flatnonzero(full["bull"])[0])
    assert b.low[i] < b.low[i - 20:i].min() and r.low[i] >= r.low[i - 20:i].min()
    none = REGISTRY["smt"].compute(b, ref="B", lookback=20, _ctx={})
    assert none["bull"].sum() == 0  # référence absente : indisponible


def test_smt_cache_and_validation():
    from qlab.genome import model
    g = {"schema": "qlab.genome/1.0", "market": {"symbol": "XAUUSD", "timeframe": "M5"},
         "entry": {"long": {"id": "n1", "op": "event", "ref": {"feature": "smt", "params": {"ref": "XAGUSD", "lookback": 20},
                                                                 "output": "bull"}}, "short": None},
         "exit": {"stop": {"type": "atr", "period": 14, "mult": 2.0}, "target": None, "break_even": None, "trailing": None,
                  "time_stop_bars": None, "exit_on_opposite": False}, "sizing": {"risk_pct": 0.5},
         "management": {"max_trades_per_day": 3, "cooldown_bars": 0}}
    assert model.validate(g) == []
    assert any("XAGUSD indisponible" in e for e in model.validate(g, {"H1"}))
    assert model.validate(g, {"SYM:XAGUSD"}) == []
    g["entry"]["long"]["ref"]["params"]["ref"] = "XAUUSD"
    assert any("doit différer" in e for e in model.validate(g))
