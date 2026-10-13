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
