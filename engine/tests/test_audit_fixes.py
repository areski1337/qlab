"""Non-régression des correctifs de l'audit produit (cycle 1, 2026-10-14)."""
import json
from pathlib import Path

import numpy as np
import pytest

from qlab.backtest.costs import DEFAULT_COST_PROFILE, spread_series
from qlab.data import dataset, synthetic
from qlab.demo import monitor
from qlab.features import FeatureCache
from qlab.genome import store as gstore
from qlab.lab import Lab
from qlab.risk.controller import DEFAULT_LIMITS, RiskController
from qlab.validation import budget, pipeline, protocol as proto, robustness

EX = Path(__file__).resolve().parents[2] / "examples" / "genomes"
COSTS = {**DEFAULT_COST_PROFILE, "fixed_spread_points": 10}


def _import(lab, n, seed=8):
    return dataset.import_bars(lab, source="synthetic", broker=None, source_symbol="SYNTH", canonical_symbol="SYNTH",
                               timeframe="M5", raw=synthetic.make_bars(n, seed=seed), spec=synthetic.SYNTHETIC_SPEC,
                               tz_profile="UTC", provenance={}, synthetic=True)


def _genome(name="valid_ema_trend_rsi.json"):
    g = json.loads((EX / name).read_text(encoding="utf-8"))
    g["market"] = {"symbol": "SYNTH", "timeframe": "M5"}
    g["management"]["max_trades_per_day"] = 10
    return g


@pytest.fixture
def env(tmp_path):
    lab = Lab.open(tmp_path / "d")
    v = _import(lab, 30000)
    bars = dataset.load_bars(lab, v["id"])
    yield lab, bars, FeatureCache(bars), gstore.create_revision(lab.con, _genome())
    lab.close()


# F-TRAD-001 : le stress multiplie le spread effectif, il ne relève pas un plancher
def test_cost_stress_multiplies_effective_spread(env):
    lab, bars, cache, rev = env
    base = spread_series(bars, COSTS)
    assert np.allclose(spread_series(bars, {**COSTS, "spread_scale": 1.5}), base * 1.5)
    risk = RiskController(DEFAULT_LIMITS)
    w = proto.segments(len(bars))["train"]
    _, m = robustness._run(rev["content"], cache, COSTS, risk, w)
    st = robustness.cost_stress(rev["content"], cache, COSTS, risk, w)
    assert m["n_trades"] > 20
    for k in ("spread_x1.5", "spread_x2", "slippage+", "commission+"):
        assert st[k]["expectancy"] < m["expectancy"], k  # chaque scénario coûte strictement plus


# F-TRAD-010 : frontières datées, stables d'une version à l'autre ; holdout compté par série
def test_dated_segments_survive_longer_reimport(tmp_path):
    lab = Lab.open(tmp_path / "d")
    v1 = dataset.load_bars(lab, _import(lab, 30000)["id"])
    s1 = proto.segments_for(lab, v1)
    v2 = dataset.load_bars(lab, _import(lab, 36000)["id"])
    assert v2.version_id != v1.version_id
    s2 = proto.segments_for(lab, v2)
    final_v1 = set(v1.ts[s1["final"][0]:s1["final"][1]].tolist())
    research_v2 = set(v2.ts[s2["train"][0]:s2["validation"][1]].tolist())
    assert not final_v1 & research_v2  # aucune barre finale de v1 ne revient en recherche
    assert v2.ts[s2["final"][1] - 1] == v1.ts[s1["final"][1] - 1]  # même fin de holdout
    assert s2["forward"][1] - s2["forward"][0] > 0  # barres nouvelles = segment forward
    rev = gstore.create_revision(lab.con, _genome())
    risk = RiskController(DEFAULT_LIMITS)
    proto.evaluate(lab, rev, FeatureCache(v1), COSTS, risk, "final", allow_final=True)
    rev2 = gstore.create_revision(lab.con, {**_genome(), "management": {**_genome()["management"], "cooldown_bars": 3}})
    proto.evaluate(lab, rev2, FeatureCache(v2), COSTS, risk, "final", allow_final=True)
    assert proto.holdout_usage(lab, v2.version_id) == {"revisions_evaluated": 2, "independent": False}
    lab.close()


# F-TRAD-002 : le seuil OOS se resserre avec le nombre de révisions évaluées sur le segment
def test_oos_decision_corrected_for_multiplicity():
    r = list(np.random.default_rng(0).normal(0.35, 1.0, 40))
    m = {"n_trades": 40, "expectancy": 1.0, "profit_factor": 1.6}
    one = pipeline.oos_decision(m, r, 1)
    many = pipeline.oos_decision(m, r, 200)
    assert one["p_value"] < 0.05 and one["pass"]
    assert many["alpha_effective"] < one["alpha_effective"] and not many["pass"]
    assert not pipeline.oos_decision({**m, "n_trades": 10}, r, 1)["pass"]


# F-TRAD-003 / F-CODE-002 : essais du DSR comptés sur la série, toutes campagnes confondues
def test_dsr_trials_cover_all_revisions_of_series(env):
    lab, bars, cache, rev = env
    risk = RiskController(DEFAULT_LIMITS)
    rev2 = gstore.create_revision(lab.con, _genome("valid_regime_trend.json") | {"market": {"symbol": "SYNTH", "timeframe": "M5"}})
    for r, camp in ((rev, None), (rev2, None)):
        proto.evaluate(lab, r, cache, COSTS, risk, "train", campaign_id=camp)
    assert len(robustness.trial_sharpes(lab, bars.version_id)) == 2


# F-PERF-001 : arrêt des tests coûteux au premier échec ; un test non exécuté ne peut pas valider
def test_robustness_stops_after_first_failure(env):
    lab, bars, cache, rev = env
    crit = {**robustness.DEFAULT_CRITERIA, "min_trades": 10**6}
    rep = robustness.run_suite(lab, rev, cache, COSTS, RiskController(DEFAULT_LIMITS), proto.DEFAULT_PROTOCOL,
                               criteria=crit)
    assert rep["passed"] is False
    assert rep["walk_forward_reopt"].get("skipped") and rep["random_baseline"].get("skipped")
    assert rep["checks"]["random_baseline"]["pass"] is None


# F-TRAD-005 : chaque palier exige des transactions nouvelles ; une observation n'autorise qu'une montée
def test_risk_stage_requires_new_trades(tmp_path, monkeypatch):
    from qlab.core.ids import new_id
    from qlab.mql5 import toolchain
    lab = Lab.open(tmp_path / "d")
    bars = dataset.load_bars(lab, _import(lab, 20000, seed=6)["id"])
    rev = gstore.create_revision(lab.con, _genome())
    risk = RiskController(DEFAULT_LIMITS)
    proto.evaluate(lab, rev, FeatureCache(bars), {**COSTS, "fixed_spread_points": 30}, risk, "oos", store_trades=True)
    for s in gstore.LADDER[1:7]:
        gstore.set_status(lab.con, rev["id"], s, {"fixture": True}, {"test": s})
    ea = toolchain.save_ea(lab, gstore.get(lab.con, rev["id"]), "S", "UTC", DEFAULT_LIMITS, risk.limits_sha256)
    lab.con.execute("INSERT INTO compilation_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (new_id("comp"), ea["id"], "succeeded", 0, 0, 0, "fixture", None, None, "fixture de test", "2026"))
    dep = monitor.register(lab, rev["id"])
    monkeypatch.setattr(monitor, "degradation", lambda *a, **k: {"alerts": [], "checks": {}, "n_live": len(a[1])})
    trades = [{"pnl": 10.0, "costs": -1.0, "lots": 0.1, "r": 0.5}] * 25
    monitor.observe(lab, dep["id"], live=trades, account={"server": "T-Demo", "account_masked": "***1"})
    assert monitor.promote_stage(lab, dep["id"])["risk_stage"] == 0.5
    with pytest.raises(PermissionError):  # même observation : pas de seconde montée
        monitor.promote_stage(lab, dep["id"])
    again = monitor.observe(lab, dep["id"], live=trades, account={"server": "T-Demo", "account_masked": "***1"})
    assert again["stage_trades"] == 0 and again["next_risk_stage_allowed"] is None
    more = monitor.observe(lab, dep["id"], live=trades * 2, account={"server": "T-Demo", "account_masked": "***1"})
    assert more["stage_trades"] == 25 and more["next_risk_stage_allowed"] == 1.0
    lab.close()


# F-TRAD-007 / F-TRAD-008 : R exact, glissement et dérive des coûts
def test_live_r_slippage_and_cost_drift():
    assert monitor.live_r(50.0, 2000.0, 1990.0, 0.1, 1.0, 0.01) == pytest.approx(0.5)  # risque 10 × 100 × 0,1 = 100
    assert monitor.live_r(50.0, 2000.0, 0.0, 0.1, 1.0, 0.01) is None
    assert monitor.entry_slippage(2000.35, 1, 2000.0, 30, 0.01) == pytest.approx(5.0)  # Ask attendu 2000,30
    assert monitor.entry_slippage(1999.95, -1, 2000.0, 30, 0.01) == pytest.approx(5.0)
    ref = [{"r": 0.2, "pnl": 20, "lots": 1.0, "costs": 0.0}] * 30
    live = [{"r": 0.2, "pnl": 20, "lots": 1.0, "costs": -8.0, "slippage_pts": 20.0, "spread_pts": 30.0}] * 12
    al = monitor.degradation(ref, live, None, 10_000, risk_per_lot=100.0)["alerts"]
    assert any("coûts" in a for a in al)  # référence sans coûts : la tolérance vaut 5 % du risque par lot
    assert any("glissement" in a for a in al)


# F-PROD-001 : budget d'essais et entonnoir
def test_trial_budget_and_funnel(env):
    lab, bars, cache, rev = env
    lo, hi = budget.required_sharpe(10, 1.0, 500), budget.required_sharpe(5000, 1.0, 500)
    assert hi["sr0_annual"] > lo["sr0_annual"] and hi["required_sharpe_annual"] > hi["sr0_annual"]
    est = budget.estimate(lab, bars.version_id, 2000)
    assert est["n_trials_total"] == 2000 and "supposée" in est["sd_source"]
    f = budget.funnel(lab, "camp_inexistante")
    assert f["reached"]["unverified"] == 0 and f["dominant_cause"] is None


# --- cycles 2 et 3 ---

# F-TRAD-018 : une graine qui a vu le segment OOS est refusée
def test_seed_after_oos_refused(env):
    from qlab.evolution import campaign
    lab, bars, cache, rev = env
    cfg = {"dataset_version_id": bars.version_id, "cost_profile": COSTS, "seed_revision_ids": [rev["id"]]}
    campaign.create(lab, cfg)  # unverified : admise
    for s in ("screened", "historically_tested", "robustness_tested", "oos_evaluated"):
        gstore.set_status(lab.con, rev["id"], s, {"fixture": True}, {"test": s})
    with pytest.raises(ValueError, match="hors échantillon"):
        campaign.create(lab, cfg)


# F-TRAD-012 : une estimation ne fige pas les frontières et les expose
def test_budget_does_not_freeze_segments(env):
    lab, bars, cache, rev = env
    est = budget.estimate(lab, bars.version_id, 10)
    assert lab.con.execute("SELECT COUNT(*) FROM segment_boundaries").fetchone()[0] == 0
    assert est["segments"]["frozen"] is False and est["segments"]["train_end"] < est["segments"]["oos_end"]
    proto.segments_for(lab, bars)
    assert budget.estimate(lab, bars.version_id, 10)["segments"]["frozen"] is True


# F-TRAD-019 : pas d'expérience de méthode sur une série de recherche
def test_experiment_refused_on_research_series(env):
    from qlab.evolution import campaign, meta
    lab, bars, cache, rev = env
    spec = {"base": {"dataset_version_id": bars.version_id, "cost_profile": COSTS}, "baseline": {}, "variant": {},
            "seeds": [1, 2, 3], "metric": "front_size", "direction": "higher"}
    meta.create(lab, "h", spec)  # série vierge : admise
    campaign.create(lab, {"dataset_version_id": bars.version_id, "cost_profile": COSTS})
    with pytest.raises(ValueError, match="série dédiée"):
        meta.create(lab, "h", spec)


# F-TRAD-015 : l'arrêt du fichier .halt prime sur le .csv, la levée supprime les deux
def test_guard_halt_file(env, tmp_path, monkeypatch):
    lab = env[0]
    d = tmp_path / "QLab"
    d.mkdir()
    monkeypatch.setattr(monitor, "flag_path", lambda lab, magic=None: d / "EMERGENCY_STOP")
    (d / "guard_12345.csv").write_text("1000.00;0;20000;1000.00", encoding="ascii")  # .csv réécrit sans arrêt
    (d / "guard_12345.halt").write_text("1000.00", encoding="ascii")
    (d / "guard_678.halt").write_text("1.00", encoding="ascii")  # arrêt sans .csv
    st = {s["login"]: s for s in monitor.guard_states(lab)}
    assert st["12345"]["halted"] and st["12345"]["peak_equity"] == 1000 and st["678"]["halted"]
    assert monitor.reset_guard(lab, "12345", "test")["reset"]
    assert not list(d.glob("guard_12345.*"))


# F-TRAD-013 : la décision OOS porte sur le R net ; une commission élevée annule un avantage brut significatif
def test_oos_decision_uses_net_r(env, monkeypatch):
    lab, bars, cache, rev = env
    risk_amount, commission = 100.0, 45.0  # commission = 0,45 R par trade
    gross_r = [1.5 if i % 2 else -0.5 for i in range(40)]  # R brut moyen 0,5 : significatif seul
    trades = [{"r": r, "pnl": r * risk_amount - commission, "risk_amount": risk_amount} for r in gross_r]
    pnls = [t["pnl"] for t in trades]
    metrics = {"n_trades": 40, "expectancy": sum(pnls) / 40,  # net encore positif : seuils de base satisfaits
               "profit_factor": sum(p for p in pnls if p > 0) / -sum(p for p in pnls if p < 0)}
    assert metrics["expectancy"] > 0 and metrics["profit_factor"] > 1
    assert pipeline.oos_decision(metrics, gross_r, 1)["pass"]  # sur le R brut, la stratégie serait admise

    def fake_evaluate(lab_, rev_, cache_, costs, risk, segment, *a, **k):
        assert segment == "oos"
        return {"id": "eval_fixture", "metrics": metrics, "trades_artifact": None, "result": {"trades": trades}}
    monkeypatch.setattr(proto, "evaluate", fake_evaluate)
    for s in ("screened", "historically_tested", "robustness_tested"):
        gstore.set_status(lab.con, rev["id"], s, {"fixture": True}, {"test": s})
    out = pipeline.advance(lab, rev["id"], cache, COSTS, RiskController(DEFAULT_LIMITS))
    assert out["status"] == "rejected" and "non significatif" in out["log"][-1]["reason"]
    dec = gstore.transitions(lab.con, rev["id"])[-1]["evidence"]["oos_test"]
    assert dec["base_pass"] and dec["p_value"] > dec["alpha_effective"]


# F-TRAD-017 : le transfert suit les frontières datées figées de la série, pas les fractions de la version fournie
def test_transfer_uses_frozen_dated_boundaries(env):
    lab, bars, cache, rev = env
    proto.segments_for(lab, bars)  # fige les frontières sur la version de 30 000 barres
    v2 = dataset.load_bars(lab, _import(lab, 36000)["id"])  # ré-import plus long de la même série
    c2 = FeatureCache(v2)
    dated_end = proto.segments_for(lab, v2)["validation"][1]  # frontières déjà figées : relues, non refigées
    frac_end = proto.segments(len(v2))["validation"][1]
    assert dated_end < frac_end
    risk = RiskController(DEFAULT_LIMITS)
    g = rev["content"]
    expected = robustness._summ(robustness._run(g, c2, COSTS, risk, (0, dated_end))[1])
    by_fractions = robustness._summ(robustness._run(g, c2, COSTS, risk, (0, frac_end))[1])
    assert expected["n_trades"] != by_fractions["n_trades"]  # les deux fenêtres sont distinguables
    out = robustness.transfer(g, {"SYNTH": c2}, COSTS, risk, proto.DEFAULT_PROTOCOL, lab)["SYNTH"]
    assert out["n_trades"] == expected["n_trades"]
    assert out["net_profit"] == pytest.approx(expected["net_profit"])
    assert lab.con.execute("SELECT COUNT(*) FROM segment_boundaries").fetchone()[0] == 1  # rien de figé en plus


# F-CODE-004 : la pause ou l'annulation de l'expérience parente arrête la campagne enfant
def test_campaign_stops_when_parent_task_paused(env):
    from qlab.evolution import campaign
    from qlab.tasks import queue
    lab, bars, cache, rev = env
    parent = queue.submit(lab.con, "experiment", {"fixture": True})
    for s in ("validating", "running"):
        queue.transition(lab.con, parent, s)
    cid, tid = campaign.create(lab, {"dataset_version_id": bars.version_id, "cost_profile": COSTS,
                                     "parent_task_id": parent})
    for s in ("validating", "running"):
        queue.transition(lab.con, tid, s)
    cfg = json.loads(lab.con.execute("SELECT config_json FROM campaigns WHERE id=?", (cid,)).fetchone()[0])
    camp = campaign.Campaign(lab, tid, cid, cfg)
    assert camp.stop_state() is None  # parent et enfant actifs
    queue.transition(lab.con, parent, "paused")
    assert queue.get(lab.con, tid)["state"] == "running"
    assert camp.stop_state() == "paused"
    queue.transition(lab.con, parent, "cancelled")
    assert camp.stop_state() == "cancelled"


# F-PROD-003 : le passeport expose le N de la série (essais du Sharpe dégonflé du rapport de robustesse)
def test_passport_series_trials_from_robustness_report(env):
    from qlab.passport import build as passport
    lab, bars, cache, rev = env
    risk = RiskController(DEFAULT_LIMITS)
    rev2 = gstore.create_revision(lab.con, _genome("valid_regime_trend.json") | {"market": {"symbol": "SYNTH", "timeframe": "M5"}})
    rev3 = gstore.create_revision(lab.con, {**_genome(), "management": {**_genome()["management"], "cooldown_bars": 3}})
    for r in (rev, rev2, rev3):
        proto.evaluate(lab, r, cache, COSTS, risk, "train")
    trials = robustness.trial_sharpes(lab, bars.version_id)
    assert len(trials) == 3
    rep = {"checks": {}, "deflated_sharpe": robustness.deflated_sharpe(trials[0], 250, 0.0, 3.0, trials)}
    n_trials = rep["deflated_sharpe"]["n_trials"]
    assert n_trials >= 2
    sha = lab.store.put_json(rep, kind="robustness_report", meta={"revision": rev["id"]})
    for s in ("screened", "historically_tested"):
        gstore.set_status(lab.con, rev["id"], s, {"fixture": True}, {"test": s})
    gstore.set_status(lab.con, rev["id"], "robustness_tested", {"fixture": True}, {"robustness_report": sha})
    p = passport.build(lab, rev["id"])
    assert p["observations"]["multiplicity"]["series_trials"] == n_trials
    assert p["observations"]["multiplicity"]["campaign_candidates"] is None  # hors campagne : seul N de série
    assert any(f"{n_trials} stratégie(s) essayée(s)" in s for s in p["interpretations"])


# F-TRAD-016 : un portefeuille manuel exige des révisions >= oos_evaluated (409) ; le holdout final est refusé (403)
def test_portfolio_api_requires_oos_and_refuses_final(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from qlab.api import app as api
    token = "t" * 32
    lab = Lab.open(tmp_path / "api")
    ok = gstore.create_revision(lab.con, _genome())
    raw = gstore.create_revision(lab.con, _genome("valid_regime_trend.json") | {"market": {"symbol": "SYNTH", "timeframe": "M5"}})
    for s in ("screened", "historically_tested", "robustness_tested", "oos_evaluated"):
        gstore.set_status(lab.con, ok["id"], s, {"fixture": True}, {"test": s})
    gstore.set_status(lab.con, raw["id"], "screened", {"fixture": True}, {"test": "screened"})
    monkeypatch.setitem(api.STATE, "root", str(lab.paths.root))
    monkeypatch.setitem(api.STATE, "token", token)
    lab.close()
    c = TestClient(api.app, headers={"X-QLab-Token": token})
    r = c.post("/api/v1/portfolios", json={"revision_ids": [ok["id"], raw["id"]]})
    assert r.status_code == 409
    assert raw["id"] in r.json()["detail"] and ok["id"] not in r.json()["detail"]  # seule la révision non validée
    r = c.post("/api/v1/portfolios", json={"revision_ids": [ok["id"], raw["id"]], "segment": "final"})
    assert r.status_code == 403


# F-TRAD-015 : l'EA crée guard_<login>.halt et ne le supprime jamais (levée manuelle seulement)
def test_ea_guard_halt_file_never_deleted():
    import re
    from qlab.genome import model
    from qlab.mql5 import generator
    g = json.loads((EX / "valid_ict_fvg_killzone.json").read_text(encoding="utf-8"))
    rev = {"id": "rev_test", "content": g, "semantic_hash": model.semantic_hash(g)}
    src = generator.generate(rev, "XAUUSD", "NY+7", DEFAULT_LIMITS, RiskController(DEFAULT_LIMITS).limits_sha256)["source"]
    assert re.search(r'QL_GuardHaltFile\(\)\s*\{\s*return\s*"QLab\\\\guard_"\s*\+\s*'
                     r'IntegerToString\(AccountInfoInteger\(ACCOUNT_LOGIN\)\)\s*\+\s*"\.halt"', src)
    assert re.search(r"FileOpen\(QL_GuardHaltFile\(\),\s*FILE_WRITE", src)  # créé par l'EA à l'arrêt
    assert re.search(r"halted\s*=\s*FileIsExist\(QL_GuardHaltFile\(\)", src)  # sa présence vaut arrêt
    for call in re.findall(r"\b(?:FileDelete|FileMove)\s*\(([^;]*)", src):
        assert "halt" not in call.lower(), call  # ni supprimé ni déplacé par l'EA
