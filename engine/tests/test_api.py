import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qlab.api import app as api
from qlab.lab import Lab
from qlab.tasks import runner

EX = Path(__file__).resolve().parents[2] / "examples" / "genomes"
TOKEN = "t" * 32


@pytest.fixture
def client(tmp_path):
    lab = Lab.open(tmp_path / "d")
    api.STATE.update(root=str(lab.paths.root), token=TOKEN)
    lab.close()
    c = TestClient(api.app, headers={"X-QLab-Token": TOKEN})
    yield c, tmp_path / "d"


def work(root):
    lab = Lab.attach(root)
    while runner.run_next(lab):
        pass
    lab.close()


def test_token_required(client):
    c, _ = client
    assert TestClient(api.app).get("/api/v1/health").status_code == 401
    assert TestClient(api.app, headers={"X-QLab-Token": "wrong"}).get("/api/v1/health").status_code == 401
    h = c.get("/api/v1/health").json()
    assert h["sqlite"] == "ok" and "désactivé" in h["live_trading"]


def test_end_to_end_via_api(client):
    c, root = client
    t = c.post("/api/v1/datasets/synthetic", json={"n": 15000, "seed": 3}).json()
    work(root)
    task = c.get(f"/api/v1/tasks/{t['task_id']}").json()
    assert task["state"] == "completed", task["error"]
    vid = task["result"]["version_id"]
    ds = c.get("/api/v1/datasets").json()
    assert ds[0]["synthetic"] == 1

    g = json.loads((EX / "valid_ema_trend_rsi.json").read_text(encoding="utf-8"))
    g["market"] = {"symbol": "SYNTH_XAU", "timeframe": "M5"}
    assert c.post("/api/v1/genomes/validate", json={"genome": g}).json()["valid"]
    bad = c.post("/api/v1/genomes", json={"genome": {**g, "entry": {"long": None, "short": None}}})
    assert bad.status_code == 422
    rev = c.post("/api/v1/genomes", json={"genome": g}).json()
    cost = {"name": "t", "version": 1, "spread_mode": "max", "fixed_spread_points": 30, "commission_per_lot_side": 0,
            "slippage_points": 0, "apply_swap": True, "provenance": {}}
    assert c.post(f"/api/v1/genomes/{rev['id']}/backtest",
                  json={"dataset_version_id": vid, "segment": "final"}).status_code == 403
    t = c.post(f"/api/v1/genomes/{rev['id']}/backtest", json={"dataset_version_id": vid, "cost_profile": cost}).json()
    work(root)
    r = c.get(f"/api/v1/tasks/{t['task_id']}").json()
    assert r["state"] == "completed", r["error"]
    detail = c.get(f"/api/v1/genomes/{rev['id']}").json()
    assert detail["evaluations"] and detail["description"]["marché"].startswith("SYNTH_XAU")
    assert "garantie" in c.get(f"/api/v1/genomes/{rev['id']}/passport.html").text

    cfg = {"dataset_version_id": vid, "population": 6, "generations_per_tribe": 1, "merge_generations": 1,
           "tribes": ["growth"], "workers": 0, "constraints": {"min_trades": 3, "max_dd_pct": 80, "max_ambiguous_ratio": 1},
           "cost_profile": cost}
    camp = c.post("/api/v1/campaigns", json={"config": cfg}).json()
    paused = c.post(f"/api/v1/tasks/{camp['task_id']}/pause").json()
    assert paused["state"] == "paused"
    assert c.post(f"/api/v1/tasks/{camp['task_id']}/pause").status_code == 409  # transition illégale refusée
    c.post(f"/api/v1/tasks/{camp['task_id']}/resume")
    work(root)
    d = c.get(f"/api/v1/campaigns/{camp['campaign_id']}").json()
    assert d["task"]["state"] == "completed", d["task"]["error"]
    assert d["state_snapshot"]["history"]
    assert c.get(f"/api/v1/campaigns/{camp['campaign_id']}/candidates").json()

    b = c.post("/api/v1/backups").json()
    work(root)
    name = Path(c.get(f"/api/v1/tasks/{b['task_id']}").json()["result"]["path"]).name
    rep = c.post("/api/v1/backups/verify", json={"name": name}).json()
    assert rep["ok"], rep
    assert c.post("/api/v1/backups/verify", json={"name": "../evil.zip"}).status_code == 422


def test_risk_limits_cannot_enable_live(client):
    c, _ = client
    lim = c.get("/api/v1/settings").json()["risk_limits"]
    assert c.put("/api/v1/risk-limits", json={**lim, "live_trading_enabled": True}).status_code == 422  # AT-012
    assert c.put("/api/v1/risk-limits", json={**lim, "max_risk_per_trade_pct": 50}).status_code == 422
    assert c.put("/api/v1/risk-limits", json={**lim, "max_daily_loss_pct": 3.0}).json()["ok"]
