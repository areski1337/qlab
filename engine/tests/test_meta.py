import pytest

from qlab.evolution import campaign, meta
from qlab.lab import Lab
from qlab.tasks import queue, runner
from test_evolution import import_synth, small_cfg


@pytest.fixture
def lab(tmp_path):
    lab = Lab.open(tmp_path / "d")
    yield lab
    lab.close()


def test_guardrails_cannot_be_experimented(lab):
    base = small_cfg("x")
    for bad in ({"constraints": {"min_trades": 1}}, {"cost_profile": {}}, {"protocol": {}}, {"exportable_only": False}):
        with pytest.raises(ValueError, match="interdites"):
            meta.create(lab, "h", {"base": base, "baseline": {}, "variant": bad, "seeds": [1, 2, 3],
                                   "metric": "front_size", "direction": "higher"})


def test_sign_test():
    assert meta.sign_test_p(4, 0) == pytest.approx(1 / 16)
    assert meta.sign_test_p(0, 0) == 1.0


def test_experiment_promotion_and_rollback(lab):
    dsv = import_synth(lab, n=6000)
    base = {k: v for k, v in small_cfg(dsv).items() if k not in ("population", "seed")}
    base.update(generations_per_tribe=1, merge_generations=1, tribes=["growth"])
    eid, tid = meta.create(lab, "Une population plus grande évalue plus de candidats.", {
        "base": base, "baseline": {"population": 4}, "variant": {"population": 8}, "seeds": [1, 2, 3, 4],
        "metric": "evaluations", "direction": "higher"})
    t = runner.run_next(lab)
    assert t["state"] == "completed", t["error"]
    assert t["result"]["verdict"] == "promote_candidate" and t["result"]["sign_test_p"] == pytest.approx(1 / 16)
    assert meta.experimental_overrides(lab) == {}  # rien n'est appliqué automatiquement
    assert meta.promote(lab, eid) == {"population": 8}
    cid, _ = campaign.create(lab, {**base, "channel": "experimental", "seed": 5})
    import json
    cfg = json.loads(lab.con.execute("SELECT config_json FROM campaigns WHERE id=?", (cid,)).fetchone()[0])
    assert cfg["population"] == 8
    cid2, _ = campaign.create(lab, {**base, "seed": 5})  # canal stable : inchangé
    cfg2 = json.loads(lab.con.execute("SELECT config_json FROM campaigns WHERE id=?", (cid2,)).fetchone()[0])
    assert cfg2["population"] == campaign.DEFAULT_CONFIG["population"]
    assert meta.rollback(lab) == {}
    assert meta.experimental_overrides(lab) == {}


def test_reject_verdict_cannot_be_promoted(lab):
    dsv = import_synth(lab, n=6000)
    base = {k: v for k, v in small_cfg(dsv).items() if k not in ("population", "seed")}
    base.update(generations_per_tribe=1, merge_generations=1, tribes=["growth"])
    eid, _ = meta.create(lab, "Une population plus petite évalue plus de candidats (fausse).", {
        "base": base, "baseline": {"population": 8}, "variant": {"population": 4}, "seeds": [1, 2, 3],
        "metric": "evaluations", "direction": "higher"})
    t = runner.run_next(lab)
    assert t["result"]["verdict"] == "reject"
    with pytest.raises(PermissionError):
        meta.promote(lab, eid)
