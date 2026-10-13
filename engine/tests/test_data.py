import datetime as dt
import os

import numpy as np
import pandas as pd
import pytest

from qlab.core.timeutil import iso_to_ts
from qlab.data import dataset, mtf, synthetic, tz
from qlab.lab import Lab


@pytest.fixture
def lab(tmp_path):
    lab = Lab.open(tmp_path / "data")
    yield lab
    lab.close()


def test_ny7_profile_across_us_dst():
    # 2026-03-06 (hiver US) : serveur = UTC+2 ; 2026-03-09 (après passage à l'heure d'été US le 8/3) : UTC+3.
    winter_server = iso_to_ts("2026-03-06T12:00:00Z")  # lu comme heure serveur
    summer_server = iso_to_ts("2026-03-09T12:00:00Z")
    utc, inv = tz.server_to_utc(np.array([winter_server, summer_server]), "NY+7")
    assert not inv.any()
    assert winter_server - utc[0] == 2 * 3600
    assert summer_server - utc[1] == 3 * 3600
    assert (tz.utc_to_server(utc, "NY+7") == [winter_server, summer_server]).all()


def test_ny7_ambiguous_hour_is_flagged_not_guessed():
    # Retour à l'heure d'hiver US le 2026-11-01 à 02:00 NY : 01:30 NY est ambigu → 08:30 serveur.
    amb = iso_to_ts("2026-11-01T08:30:00Z")
    _, inv = tz.server_to_utc(np.array([amb]), "NY+7")
    assert inv[0]


def test_profile_check():
    now = iso_to_ts("2026-10-13T12:00:00Z")
    assert tz.check_profile("NY+7", now + 3 * 3600, now)["consistent"]
    assert not tz.check_profile("NY+7", now + 2 * 3600, now)["consistent"]


def test_normalize_documents_every_correction():
    raw = synthetic.from_closes([10, 11, 12, 13, 14])
    raw.loc[2, "ts"] = raw.loc[1, "ts"]          # doublon
    raw.loc[3, "high"] = 1.0                     # OHLC incohérent
    last_close = raw["ts"].iloc[-1] + 300
    norm, corr = dataset.normalize(raw, "M5", "UTC", import_time_utc=last_close - 1)  # dernière barre en cours
    rules = {c["rule"]: c["count"] for c in corr}
    assert rules == {"drop_duplicate_ts_keep_last": 1, "drop_incoherent_ohlc": 1, "drop_incomplete_last_bar": 1}
    assert len(norm) == 2
    assert norm["close"].tolist() == [10, 12]  # le doublon garde la dernière occurrence, jamais de valeur inventée


def test_dataset_versioning_and_integrity(lab):
    raw = synthetic.make_bars(2000, seed=1)
    kw = dict(source="synthetic", broker=None, source_symbol="SYNTH_XAU", canonical_symbol="SYNTH_XAU",
              timeframe="M5", spec=synthetic.SYNTHETIC_SPEC, tz_profile="UTC", provenance={"seed": 1}, synthetic=True)
    v1 = dataset.import_bars(lab, raw=raw, **kw)
    assert dataset.import_bars(lab, raw=raw, **kw)["id"] == v1["id"]  # contenu identique : pas de doublon
    v2 = dataset.import_bars(lab, raw=synthetic.make_bars(2100, seed=1), **kw)
    assert v2["version"] == 2 and v2["parent_version_id"] == v1["id"]
    bars = dataset.load_bars(lab, v1["id"])
    assert bars.synthetic and len(bars) == 2000 and bars.content_sha256 == v1["content_sha256"]
    # Modification silencieuse du fichier détectée.
    p = lab.paths.root / v1["file_relpath"]
    df = pd.read_parquet(p)
    df.loc[5, "close"] += 1
    df.to_parquet(p)
    with pytest.raises(IOError):
        dataset.load_bars(lab, v1["id"])


def test_spec_change_detected(lab):
    raw = synthetic.make_bars(500, seed=2)
    kw = dict(source="synthetic", broker=None, source_symbol="S", canonical_symbol="S", timeframe="M5",
              tz_profile="UTC", provenance={}, synthetic=True, raw=raw)
    dataset.import_bars(lab, spec={**synthetic.SYNTHETIC_SPEC}, **kw)
    v2 = dataset.import_bars(lab, spec={**synthetic.SYNTHETIC_SPEC, "volume_min": 0.1}, **kw)
    import json
    assert json.loads(v2["qc_json"])["spec_changes"] == {"volume_min": [0.01, 0.1]}


def test_qc_flags_gaps_and_zero_spread():
    raw = synthetic.from_closes(np.arange(1, 101, dtype=float))
    raw.loc[50:, "ts"] += 2 * 86400  # trou de 2 jours un lundi (2024-01-01 est un lundi)
    rep = dataset.quality_report(raw, "M5", now_utc=raw["ts"].iloc[-1] + 600)
    assert rep["non_weekend_gaps_by_duration"][">24h"] == 1
    assert rep["zero_spread_ratio"] == 1.0
    assert any("spread" in w for w in rep["warnings"])


def test_mtf_alignment_never_uses_forming_bar():  # AT-001 (synchronisation MTF)
    m5 = iso_to_ts("2024-01-01T00:00:00Z") + np.arange(36) * 300
    h1 = iso_to_ts("2024-01-01T00:00:00Z") + np.arange(3) * 3600
    idx = mtf.align_index(m5 + 300, h1 + 3600)
    # Barres M5 de 00:00 à 00:50 (clôture <= 00:55... <01:00) : aucune H1 close.
    assert (idx[:11] == -1).all()
    # La barre M5 de 00:55 clôture à 01:00 : la H1 de 00:00 vient de clôturer → utilisable.
    assert idx[11] == 0
    assert idx[23] == 1 and idx[22] == 0


@pytest.mark.skipif(os.environ.get("QLAB_MT5_TESTS") != "1", reason="QLAB_MT5_TESTS=1 requis (terminal MT5 réel)")
def test_real_mt5_import(lab):
    from qlab.data import mt5_source
    raw, spec, ctx = mt5_source.fetch_rates("EURUSD", "H1", dt.datetime(2026, 9, 1), dt.datetime(2026, 10, 1))
    assert tz.check_profile("NY+7", ctx["last_tick_server_ts"], ctx["observed_at_utc"])["consistent"]
    v = dataset.import_bars(lab, source="mt5", broker=ctx["server"], source_symbol="EURUSD", canonical_symbol="EURUSD",
                            timeframe="H1", raw=raw, spec=spec, tz_profile="NY+7", provenance=ctx)
    assert v["n_bars"] > 400
