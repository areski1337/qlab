import json
import zipfile
from pathlib import Path

from qlab.backtest.costs import DEFAULT_COST_PROFILE
from qlab.data import dataset, synthetic
from qlab.features import FeatureCache
from qlab.genome import store as gstore
from qlab.lab import Lab
from qlab.mql5 import toolchain
from qlab.passport import build
from qlab.risk.controller import DEFAULT_LIMITS, RiskController
from qlab.validation import pipeline

EX = Path(__file__).resolve().parents[2] / "examples" / "genomes"


def test_passport_sections_and_export(tmp_path):  # AT-013, AT-014
    lab = Lab.open(tmp_path / "d")
    v = dataset.import_bars(lab, source="synthetic", broker=None, source_symbol="SYNTH", canonical_symbol="SYNTH",
                            timeframe="M5", raw=synthetic.make_bars(20000, seed=4), spec=synthetic.SYNTHETIC_SPEC,
                            tz_profile="UTC", provenance={}, synthetic=True)
    g = json.loads((EX / "valid_ema_trend_rsi.json").read_text(encoding="utf-8"))
    g["market"] = {"symbol": "SYNTH", "timeframe": "M5"}
    rev = gstore.create_revision(lab.con, g)
    cache = FeatureCache(dataset.load_bars(lab, v["id"]))
    risk = RiskController(DEFAULT_LIMITS)
    pipeline.advance(lab, rev["id"], cache, {**DEFAULT_COST_PROFILE, "fixed_spread_points": 30}, risk,
                     stop_at="historically_tested")
    toolchain.save_ea(lab, gstore.get(lab.con, rev["id"]), "SYNTH", "UTC", DEFAULT_LIMITS, risk.limits_sha256)
    p = build.build(lab, rev["id"])
    assert set(("observations", "hypotheses", "interpretations", "unverified")) <= set(p)
    assert any("SYNTHÉTIQUES" in h for h in p["hypotheses"])
    assert any("compilé" in u for u in p["unverified"]) and any("Parité" in u for u in p["unverified"])
    html = build.render_html(p)
    assert "Non vérifié" in html and "Hypothèses" in html and "garantie" in html
    out = build.export_bundle(lab, rev["id"])
    with zipfile.ZipFile(out["path"]) as z:
        names = set(z.namelist())
        man = json.loads(z.read("manifest.json"))
        assert {"genome.json", "passport.json", "passport.html", "manifest.json", f"QLab_{rev['id']}.mq5"} <= names
        src = z.read(f"QLab_{rev['id']}.mq5").decode()
    assert rev["semantic_hash"] in src and man["semantic_hash"] == rev["semantic_hash"]
    assert man["tests"]["status_history"]
    lab.close()
