import json
import random

import pytest

from qlab.backtest.costs import DEFAULT_COST_PROFILE
from qlab.data import dataset, synthetic
from qlab.evolution import campaign, nsga2, operators as ops
from qlab.genome import model, store as gstore
from qlab.lab import Lab
from qlab.tasks import queue, runner


@pytest.fixture
def lab(tmp_path):
    lab = Lab.open(tmp_path / "data")
    yield lab
    lab.close()


def import_synth(lab, n=12000, seed=5):
    v = dataset.import_bars(lab, source="synthetic", broker=None, source_symbol="SYNTH", canonical_symbol="SYNTH",
                            timeframe="M5", raw=synthetic.make_bars(n, seed=seed), spec=synthetic.SYNTHETIC_SPEC,
                            tz_profile="UTC", provenance={"seed": seed}, synthetic=True)
    return v["id"]


def small_cfg(dsv, **kw):
    return {"dataset_version_id": dsv, "population": 8, "generations_per_tribe": 2, "merge_generations": 1,
            "tribes": ["consistency", "exploration", "specialization"], "workers": 0, "seed": 3,
            "constraints": {"min_trades": 5, "max_dd_pct": 60.0, "max_ambiguous_ratio": 0.5},
            "cost_profile": {**DEFAULT_COST_PROFILE, "fixed_spread_points": 30}, **kw}


def test_random_genomes_and_operators_always_valid():
    rng = random.Random(1)
    for _ in range(60):
        g = ops.random_genome(rng, "XAUUSD", "M5")
        assert model.validate(g) == []
        for op in ops.MUTATIONS:
            r = ops.mutate(rng, g, op)
            if r:
                assert model.validate(r[0]) == [], op
        r = ops.crossover(rng, g, ops.random_genome(rng, "XAUUSD", "M5"))
        if r:
            assert model.validate(r[0]) == []


def test_genome_never_contains_absolute_limits():  # AT-009
    rng = random.Random(2)
    g = ops.random_genome(rng, "X", "M5")
    for _ in range(200):
        r = ops.mutate(rng, g, rng.choice(list(ops.MUTATIONS)))
        if r:
            g = r[0]
        assert set(g) == {"schema", "market", "entry", "exit", "sizing", "management"}
        assert set(g["sizing"]) == {"risk_pct"} and g["sizing"]["risk_pct"] == 0.5


def test_nsga2_constraint_domination():
    objs = [(10.0, 10.0), (1.0, 1.0), (2.0, 0.5), (0.5, 2.0)]
    viol = [1.0, 0.0, 0.0, 0.0]  # le meilleur en objectifs est infaisable
    F = nsga2.fronts(objs, viol)
    assert 0 not in F[0] and 0 in F[-1]
    assert sorted(F[0]) == [1, 2, 3]  # (1,1) non dominé par (2,0.5) ni (0.5,2)


def test_lineage_traceable(lab):  # AT-003
    rng = random.Random(4)
    root = gstore.create_revision(lab.con, ops.random_genome(rng, "X", "M5"))
    m = ops.mutate(rng, root["content"], "param") or ops.mutate(rng, root["content"], "exit")
    child = gstore.create_revision(lab.con, m[0], [(root["id"], "param", m[1])])
    other = gstore.create_revision(lab.con, ops.random_genome(rng, "X", "M5"))
    x = ops.crossover(rng, child["content"], other["content"])
    gc = gstore.create_revision(lab.con, x[0], [(child["id"], "crossover", x[1]), (other["id"], "crossover", x[1])])
    lin = gstore.lineage(lab.con, gc["id"])
    assert {(l["child_id"], l["parent_id"]) for l in lin} == {
        (gc["id"], child["id"]), (gc["id"], other["id"]), (child["id"], root["id"])}
    assert child["genome_id"] == root["genome_id"] and child["revision"] == 2


def test_status_ladder_requires_evidence(lab):
    rev = gstore.create_revision(lab.con, ops.random_genome(random.Random(9), "X", "M5"))
    with pytest.raises(gstore.IllegalStatus):
        gstore.set_status(lab.con, rev["id"], "mt5_validated", {}, {"x": 1})  # saut d'échelons
    with pytest.raises(gstore.IllegalStatus):
        gstore.set_status(lab.con, rev["id"], "screened", {}, {})  # sans preuve
    gstore.set_status(lab.con, rev["id"], "screened", {"r": 1}, {"e": 1})
    gstore.set_status(lab.con, rev["id"], "rejected", {"r": 1}, {"e": 1})
    with pytest.raises(gstore.IllegalStatus):
        gstore.set_status(lab.con, rev["id"], "historically_tested", {}, {"e": 1})


def run_campaign(lab, cfg):
    cid, tid = campaign.create(lab, cfg)
    t = runner.run_next(lab)
    return cid, tid, t


def test_specialize_creates_unique_ids():
    rng = random.Random(5)
    for _ in range(30):
        g = campaign.specialize(ops.random_genome(rng, "X", "M5", "both"), "london_kz")
        assert model.validate(g) == [] and campaign.has_session(g, "london_kz")


def test_campaign_end_to_end_and_deterministic(tmp_path):
    results = []
    for k in range(2):
        lab = Lab.open(tmp_path / f"d{k}")
        dsv = import_synth(lab)
        cid, tid, t = run_campaign(lab, small_cfg(dsv))
        assert t["state"] == "completed", t["error"]
        res = t["result"]
        assert res["evaluations"] > 0 and "biais de sélection" in res["warning"]
        results.append([(f["train"]["n_trades"], f["train"]["net_profit"]) for f in res["front"]])
        lab.close()
    assert results[0] == results[1]


def test_campaign_resume_does_not_duplicate(lab, monkeypatch):  # AT-004
    dsv = import_synth(lab)
    cid, tid = campaign.create(lab, small_cfg(dsv))
    calls = {"n": 0}
    orig = campaign.Campaign.generation

    def gen_then_pause(self, st, tribe, rng, pool):
        orig(self, st, tribe, rng, pool)
        calls["n"] += 1
        if calls["n"] == 2:  # « crash » simulé après la première génération complète
            queue.transition(lab.con, tid, "paused")
    monkeypatch.setattr(campaign.Campaign, "generation", gen_then_pause)
    t = runner.run_next(lab)
    assert t["state"] == "paused"
    monkeypatch.setattr(campaign.Campaign, "generation", orig)
    n_before = lab.con.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
    keys_before = {r[0] for r in lab.con.execute("SELECT cache_key FROM evaluations")}
    runner.resume(lab, tid)
    t = runner.run_next(lab)
    assert t["state"] == "completed", t["error"]
    keys = [r[0] for r in lab.con.execute("SELECT cache_key FROM evaluations")]
    assert len(keys) == len(set(keys)) and keys_before <= set(keys)
    assert len(keys) >= n_before

    # même front qu'une exécution ininterrompue
    lab2 = Lab.open(lab.paths.root.parent / "fresh")
    dsv2 = import_synth(lab2)
    _, _, t2 = run_campaign(lab2, small_cfg(dsv2))
    f1 = sorted((f["train"]["n_trades"], round(f["train"]["net_profit"], 6)) for f in t["result"]["front"])
    f2 = sorted((f["train"]["n_trades"], round(f["train"]["net_profit"], 6)) for f in t2["result"]["front"])
    assert f1 == f2
    lab2.close()


def test_campaign_refuses_unknown_spread(lab):
    raw = synthetic.make_bars(3000, seed=1, spread_points=0)
    v = dataset.import_bars(lab, source="synthetic", broker=None, source_symbol="Z", canonical_symbol="Z", timeframe="M5",
                            raw=raw, spec=synthetic.SYNTHETIC_SPEC, tz_profile="UTC", provenance={}, synthetic=True)
    with pytest.raises(ValueError, match="spread"):
        campaign.create(lab, small_cfg(v["id"], cost_profile=DEFAULT_COST_PROFILE))


def test_parallel_workers_match_inline(tmp_path):
    out = []
    for w in (0, 2):
        lab = Lab.open(tmp_path / f"w{w}")
        dsv = import_synth(lab)
        _, _, t = run_campaign(lab, small_cfg(dsv, workers=w))
        assert t["state"] == "completed", t["error"]
        out.append(sorted((f["train"]["n_trades"], round(f["train"]["net_profit"], 6)) for f in t["result"]["front"]))
        lab.close()
    assert out[0] == out[1]


def test_global_operator_memory_is_bounded_prior(lab):
    dsv = import_synth(lab)
    run_campaign(lab, small_cfg(dsv))
    glob = {r[0]: r[1] for r in lab.con.execute("SELECT key, tries FROM evolution_memory WHERE scope='global'")}
    assert sum(glob.values()) > 0
    cid, tid = campaign.create(lab, small_cfg(dsv, seed=9))
    c = campaign.Campaign(lab, tid, cid, json.loads(lab.con.execute(
        "SELECT config_json FROM campaigns WHERE id=?", (cid,)).fetchone()[0]))
    prior = c.prior_op_stats(cap=20)
    assert all(t <= 20 and 0 <= s <= t for t, s in prior.values())
    assert any(t > 0 for t, _ in prior.values())
    runner.run_next(lab)
    after = {r[0]: r[1] for r in lab.con.execute("SELECT key, tries FROM evolution_memory WHERE scope='global'")}
    own = {r[0]: r[1] for r in lab.con.execute("SELECT key, tries FROM evolution_memory WHERE scope=?", (f"campaign:{cid}",))}
    assert all(after[k] == glob.get(k, 0) + own.get(k, 0) for k in after)  # l'a priori n'est pas recompté


def test_strategy_bases_always_valid():
    rng = random.Random(4)
    for base in ops.BASES:
        for tf, htfs in (("M5", ("H1",)), ("M15", ()), ("H1", ("H4",))):
            for sides in ("both", "long", "short"):
                for _ in range(5):
                    g = ops.base_genome(rng, base, "XAUUSD", tf, sides, htfs)
                    assert model.validate(g, set(htfs)) == [], (base, tf, sides)


def test_campaign_with_bases_and_seeds(lab):
    dsv = import_synth(lab)
    cid, tid, t = run_campaign(lab, small_cfg(dsv, bases=["trend", "breakout"]))
    assert t["state"] == "completed", t["error"]
    seeds = [f["revision_id"] for f in t["result"]["front"]][:3]
    with pytest.raises(ValueError):
        campaign.create(lab, small_cfg(dsv, bases=["inconnue"]))
    cid2, tid2, t2 = run_campaign(lab, small_cfg(dsv, seed_revision_ids=seeds, seed=9))
    assert t2["state"] == "completed", t2["error"]
    # chaque stratégie de départ est reprise dans la nouvelle campagne, filiation « reseed » conservée
    links = lab.con.execute("SELECT parent_id FROM genealogy WHERE operator='reseed'").fetchall()
    assert {r[0] for r in links} == set(seeds)
    assert all(r[0] == cid2 for r in lab.con.execute(
        "SELECT g.campaign_id FROM genealogy l JOIN genome_revisions g ON g.id=l.child_id WHERE l.operator='reseed'"))
