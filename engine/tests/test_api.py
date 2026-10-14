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


def test_non_ascii_token_gives_401(client):
    """Un en-tête X-QLab-Token non ASCII doit donner 401, jamais 500 ni exception (T-003)."""
    # La fixture `client` initialise STATE (racine + jeton) ; on utilise un client sans en-tête par défaut.
    raw =TestClient(api.app, raise_server_exceptions=False)
    # Octets latin-1 : Starlette décode les en-têtes en latin-1, le serveur reçoit donc "é" * 30.
    r = raw.get("/api/v1/health", headers={"X-QLab-Token": "é".encode("latin-1") * 30})
    assert r.status_code == 401
    assert r.json() == {"error": "jeton invalide"}
    # Non-régression : jeton absent -> 401, jeton correct -> 200.
    assert raw.get("/api/v1/health").status_code == 401
    ok = raw.get("/api/v1/health", headers={"X-QLab-Token": TOKEN})
    assert ok.status_code == 200 and ok.json()["sqlite"] == "ok"


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


def test_library_notes_and_schedules(client):
    import datetime as dt
    from qlab.tasks import schedules
    c, root = client
    g = json.loads((EX / "valid_ema_trend_rsi.json").read_text(encoding="utf-8"))
    rid = c.post("/api/v1/genomes", json={"genome": g}).json()["id"]
    assert c.put(f"/api/v1/genomes/{rid}/notes", json={"favorite": True, "tags": [" or ", "or", "tendance"], "note": "à suivre"}).json()["tags"] == ["or", "tendance"]
    lib = {r["id"]: r for r in c.get("/api/v1/library").json()}
    assert lib[rid]["favorite"] == 1 and lib[rid]["note"] == "à suivre"
    assert c.put("/api/v1/genomes/rev_inconnue/notes", json={}).status_code == 404

    t0 = dt.datetime(2026, 1, 5, 6, 0, tzinfo=dt.timezone.utc)
    assert c.post("/api/v1/schedules", json={"name": "x", "kind": "rm", "payload": {}, "first_run_utc": t0.isoformat()}).status_code == 422
    imp = c.post("/api/v1/schedules", json={"name": "maj XAU", "kind": "import_mt5", "every": "daily", "first_run_utc": t0.isoformat(),
                                            "payload": {"symbol": "XAUUSD", "timeframes": ["H1"], "from": "2020-01-01", "tz_profile": "NY+7"}}).json()["id"]
    bad = c.post("/api/v1/schedules", json={"name": "camp", "kind": "campaign", "every": "weekly", "first_run_utc": t0.isoformat(),
                                            "payload": {"dataset_version_id": None}}).json()["id"]
    lab = Lab.attach(root)
    try:
        assert schedules.tick(lab, t0 - dt.timedelta(minutes=1)) == []          # pas encore échue
        tids = schedules.tick(lab, t0 + dt.timedelta(days=2, hours=1))          # en retard de 2 jours : une seule exécution
        assert len(tids) == 1
        t = lab.con.execute("SELECT kind, payload_json FROM tasks WHERE id=?", (tids[0],)).fetchone()
        assert t["kind"] == "import_mt5" and json.loads(t["payload_json"])["to"].startswith("2026-01-07T07:00")
    finally:
        lab.close()
    s = {r["id"]: r for r in c.get("/api/v1/schedules").json()}
    assert s[imp]["next_run_utc"].startswith("2026-01-08T06:00") and s[imp]["enabled"] == 1
    assert s[bad]["enabled"] == 0 and "dataset_version_id" in s[bad]["last_error"]  # invalide : désactivée, erreur conservée
    assert c.put(f"/api/v1/schedules/{bad}", json={"enabled": True}).json()["enabled"] is True
