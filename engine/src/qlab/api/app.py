"""API locale versionnée (/api/v1). Liée à 127.0.0.1 ; jeton obligatoire (en-tête X-QLab-Token).

Les opérations longues créent des tâches persistantes exécutées par le worker ;
les requêtes HTTP ne font que lire l'état ou soumettre des tâches.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import socket
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..core.timeutil import utc_now_iso
from ..core.versions import versions_snapshot
from ..data import dataset
from ..genome import model, store as gstore
from ..lab import Lab
from ..risk.controller import DEFAULT_LIMITS, load_limits
from ..tasks import queue, runner

API = "/api/v1"
STATE: dict = {"root": None, "token": None, "worker": None, "stop": threading.Event()}
app = FastAPI(title="QLab API", version="1.0", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def auth(request: Request, call_next):
    tok = request.headers.get("x-qlab-token", "")
    if not STATE["token"] or not hmac.compare_digest(tok, STATE["token"]):
        return JSONResponse({"error": "jeton invalide"}, status_code=401)
    return await call_next(request)


def L():
    lab = Lab.attach(STATE["root"])
    try:
        yield lab
    finally:
        lab.close()


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur]


def submit(lab, kind: str, payload: dict, key: str | None = None, priority: int = 0) -> dict:
    tid = queue.submit(lab.con, kind, payload, priority=priority, idempotency_key=key)
    return {"task_id": tid}


# ---------------------------------------------------------------- santé / système
@app.get(f"{API}/health")
def health(lab=Depends(L)):
    from ..mql5.toolchain import data_path
    import shutil
    me = Path(lab.settings["mt5"]["metaeditor_path"])
    term = Path(lab.settings["mt5"]["terminal_path"])
    du = shutil.disk_usage(lab.paths.root)
    integ = lab.con.execute("PRAGMA quick_check").fetchone()[0]
    return {"ts": utc_now_iso(), "versions": versions_snapshot(), "data_dir": str(lab.paths.root),
            "sqlite": integ, "schema": lab.con.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
            "disk_free_mb": du.free // 2**20, "mt5": {"terminal_found": term.exists(), "metaeditor_found": me.exists(),
                                                      "data_path": str(data_path(lab.settings) or "")},
            "worker_alive": bool(STATE["worker"] and STATE["worker"].is_alive()),
            "live_trading": "désactivé (non disponible dans cette version)"}


@app.get(f"{API}/stats")
def stats(lab=Depends(L)):
    by = {r[0]: r[1] for r in lab.con.execute("SELECT status, COUNT(*) FROM genome_revisions GROUP BY status")}
    alerts = [f"Tâche {r['kind']} en échec : {r['error']}" for r in lab.con.execute(
        "SELECT kind, error FROM tasks WHERE state='failed' AND updated_at > datetime('now','-1 day') ORDER BY updated_at DESC LIMIT 5")]
    alerts += [f"Parité MT5 critique ({r['id']}) : divergence non expliquée" for r in lab.con.execute(
        "SELECT id FROM parity_runs WHERE critical=1 ORDER BY created_at DESC LIMIT 5")]
    return {"revisions_by_status": by, "alerts": alerts,
            "evaluations": lab.con.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0],
            "datasets": lab.con.execute("SELECT COUNT(*) FROM dataset_versions").fetchone()[0]}


@app.get(f"{API}/mt5/status")
def mt5_status(lab=Depends(L)):
    from ..data.mt5_source import status
    return status(lab.settings["mt5"]["terminal_path"])


@app.get(f"{API}/settings")
def get_settings(lab=Depends(L)):
    return {"settings": lab.settings, "risk_limits": load_limits(lab.paths.risk_limits),
            "risk_limits_default": DEFAULT_LIMITS}


class RiskLimits(BaseModel):
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_drawdown_pct: float
    max_open_positions: int = Field(ge=1, le=20)
    max_lots: float = Field(gt=0)
    max_orders_per_day: int = Field(ge=1, le=1000)
    max_spread_points: float | None = None
    live_trading_enabled: bool = False


@app.put(f"{API}/risk-limits")
def put_limits(body: RiskLimits, lab=Depends(L)):
    data = body.model_dump()
    tmp = lab.paths.risk_limits.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        load_limits(tmp)  # valide plafonds logiciels et refus du trading réel
    except ValueError as e:
        tmp.unlink()
        raise HTTPException(422, str(e))
    os.replace(tmp, lab.paths.risk_limits)
    from ..storage.db import audit
    audit(lab.con, "risk_limits.changed", None, limits=data)
    return {"ok": True, "risk_limits": data}


@app.get(f"{API}/logs")
def logs(n: int = 200, lab=Depends(L)):
    return lab.log.tail(min(n, 2000))


@app.get(f"{API}/audit")
def audit_events(n: int = 200, subject: str | None = None, lab=Depends(L)):
    q = "SELECT * FROM audit_events " + ("WHERE subject_id=? " if subject else "") + "ORDER BY id DESC LIMIT ?"
    return rows(lab.con.execute(q, ((subject,) if subject else ()) + (min(n, 2000),)))


# ---------------------------------------------------------------- tâches
@app.get(f"{API}/tasks")
def tasks(lab=Depends(L)):
    return queue.list_tasks(lab.con)


@app.get(f"{API}/tasks/{{tid}}")
def task(tid: str, lab=Depends(L)):
    try:
        return queue.get(lab.con, tid)
    except KeyError:
        raise HTTPException(404, "tâche inconnue")


@app.post(f"{API}/tasks/{{tid}}/{{action}}")
def task_action(tid: str, action: str, lab=Depends(L)):
    target = {"pause": "paused", "resume": "queued", "cancel": "cancelled", "retry": "queued"}.get(action)
    if target is None:
        raise HTTPException(400, "action inconnue")
    try:
        queue.transition(lab.con, tid, target)
    except queue.IllegalTransition as e:
        raise HTTPException(409, str(e))
    return queue.get(lab.con, tid)


# ---------------------------------------------------------------- données
@app.get(f"{API}/datasets")
def datasets(lab=Depends(L)):
    return dataset.list_versions(lab)


class ImportMT5(BaseModel):
    symbol: str = Field(pattern=r"^[A-Za-z0-9._#-]{1,32}$")
    timeframes: list[str]
    date_from: str = Field(alias="from")
    date_to: str = Field(alias="to")
    tz_profile: str = "NY+7"


@app.post(f"{API}/datasets/import-mt5")
def import_mt5(body: ImportMT5, lab=Depends(L)):
    if not set(body.timeframes) <= {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
        raise HTTPException(422, "timeframe non supporté")
    return submit(lab, "import_mt5", {"symbol": body.symbol, "timeframes": body.timeframes, "from": body.date_from,
                                      "to": body.date_to, "tz_profile": body.tz_profile})


class Synth(BaseModel):
    n: int = Field(ge=500, le=2_000_000)
    seed: int = 7
    timeframe: str = "M5"


@app.post(f"{API}/datasets/synthetic")
def import_synth(body: Synth, lab=Depends(L)):
    return submit(lab, "import_synthetic", body.model_dump())


@app.get(f"{API}/datasets/{{vid}}/bars")
def bars(vid: str, start: int = 0, limit: int = 2000, lab=Depends(L)):
    b = dataset.load_bars(lab, vid)
    s = max(0, start if start >= 0 else len(b) + start)
    sl = b.slice(s, min(len(b), s + min(limit, 20000)))
    return {"n_total": len(b), "start": s, "synthetic": b.synthetic, "symbol": b.symbol, "timeframe": b.timeframe,
            "ts": sl.ts.tolist(), "open": sl.open.tolist(), "high": sl.high.tolist(), "low": sl.low.tolist(),
            "close": sl.close.tolist(), "spread": sl.spread.tolist(), "unit": "prix Bid ; temps UTC (ouverture)"}


# ---------------------------------------------------------------- génomes
@app.get(f"{API}/features")
def features():
    from ..features import REGISTRY
    from ..mql5.generator import SUPPORTED
    return [{"name": s.name, "version": s.version, "family": s.family, "description": s.description,
             "outputs": s.outputs, "approximate": s.approximate, "mql5": s.name in SUPPORTED,
             "params": {k: {"kind": p.kind, "lo": p.lo, "hi": p.hi, "default": p.default, "choices": list(p.choices)}
                        for k, p in s.params.items()}} for s in REGISTRY.values()]


@app.get(f"{API}/genomes")
def genomes(campaign: str | None = None, status: str | None = None, limit: int = 200, lab=Depends(L)):
    q, a = "SELECT id, genome_id, revision, semantic_hash, status, campaign_id, created_at FROM genome_revisions WHERE 1=1", []
    if campaign:
        q += " AND campaign_id=?"
        a.append(campaign)
    if status:
        q += " AND status=?"
        a.append(status)
    q += " ORDER BY created_at DESC LIMIT ?"
    return rows(lab.con.execute(q, a + [min(limit, 5000)]))


class GenomeIn(BaseModel):
    genome: dict


@app.post(f"{API}/genomes/validate")
def validate(body: GenomeIn):
    errs = model.validate(body.genome)
    return {"valid": not errs, "errors": errs, "description": model.describe(body.genome) if not errs else None}


@app.post(f"{API}/genomes")
def create_genome(body: GenomeIn, lab=Depends(L)):
    try:
        return gstore.create_revision(lab.con, body.genome)
    except gstore.InvalidGenome as e:
        raise HTTPException(422, {"errors": e.errors})


@app.get(f"{API}/genomes/{{rid}}")
def genome(rid: str, lab=Depends(L)):
    try:
        r = gstore.get(lab.con, rid)
    except KeyError:
        raise HTTPException(404, "révision inconnue")
    r["description"] = model.describe(r["content"])
    r["lineage"] = gstore.lineage(lab.con, rid)
    r["transitions"] = gstore.transitions(lab.con, rid)
    r["evaluations"] = rows(lab.con.execute("SELECT id, segment, window_json, metrics_json, dataset_version_id, "
                                            "trades_artifact, created_at FROM evaluations WHERE revision_id=? "
                                            "ORDER BY created_at", (rid,)))
    for e in r["evaluations"]:
        e["metrics"] = json.loads(e.pop("metrics_json"))
        e["window"] = json.loads(e.pop("window_json"))
    from ..mql5.generator import check_exportable
    r["export_blockers"] = check_exportable(r["content"], "NY+7")
    return r


@app.get(f"{API}/artifacts/{{sha}}")
def artifact(sha: str, lab=Depends(L)):
    row = lab.con.execute("SELECT media_type FROM artifacts WHERE sha256=?", (sha,)).fetchone()
    if not row:
        raise HTTPException(404, "artefact inconnu")
    data = lab.store.get_bytes(sha)
    if row["media_type"] == "application/json":
        return json.loads(data)
    if row["media_type"].startswith("text/"):
        return {"text": data.decode("utf-8", "replace")}
    raise HTTPException(415, "artefact binaire : utiliser l'export")


class RunReq(BaseModel):
    dataset_version_id: str
    context: dict[str, str] = {}
    cost_profile: dict | None = None
    segment: str = "research"
    stop_at: str = "oos_evaluated"
    campaign_id: str | None = None
    date_from: str | None = Field(None, alias="from")
    date_to: str | None = Field(None, alias="to")
    model: int = 1


@app.post(f"{API}/genomes/{{rid}}/{{action}}")
def genome_action(rid: str, action: str, body: RunReq, lab=Depends(L)):
    gstore.get(lab.con, rid)
    p = {"revision_id": rid, "dataset_version_id": body.dataset_version_id, "context": body.context,
         "cost_profile": body.cost_profile, "campaign_id": body.campaign_id}
    if action == "backtest":
        if body.segment == "final":
            raise HTTPException(403, "segment final : utiliser l'action final-test (consommation tracée)")
        return submit(lab, "backtest", {**p, "segment": body.segment})
    if action == "advance":
        return submit(lab, "advance", {**p, "stop_at": body.stop_at})
    if action == "final-test":
        return submit(lab, "final_test", p)
    if action == "mt5-verify":
        if not (body.date_from and body.date_to):
            raise HTTPException(422, "from/to requis (AAAA.MM.JJ)")
        return submit(lab, "mt5_verify", {**p, "from": body.date_from, "to": body.date_to, "model": body.model})
    raise HTTPException(400, "action inconnue")


@app.post(f"{API}/genomes/{{rid}}/export")
def export(rid: str, lab=Depends(L)):
    gstore.get(lab.con, rid)
    return submit(lab, "export", {"revision_id": rid})


@app.get(f"{API}/genomes/{{rid}}/passport")
def passport(rid: str, lab=Depends(L)):
    from ..passport.build import build
    return build(lab, rid)


@app.get(f"{API}/genomes/{{rid}}/passport.html", response_class=HTMLResponse)
def passport_html(rid: str, lab=Depends(L)):
    from ..passport.build import build, render_html
    return render_html(build(lab, rid))


@app.get(f"{API}/genomes/{{rid}}/ea")
def ea(rid: str, lab=Depends(L)):
    out = []
    for e in rows(lab.con.execute("SELECT * FROM ea_artifacts WHERE revision_id=? ORDER BY created_at DESC", (rid,))):
        e["compilations"] = rows(lab.con.execute("SELECT * FROM compilation_runs WHERE ea_id=? ORDER BY created_at DESC", (e["id"],)))
        e["parity"] = rows(lab.con.execute("SELECT id, status, grade, critical, tester_config_json, report_json, diagnostic, "
                                           "created_at FROM parity_runs WHERE ea_id=? ORDER BY created_at DESC", (e["id"],)))
        for p in e["parity"]:
            p["report"] = json.loads(p.pop("report_json")) if p["report_json"] else None
        out.append(e)
    return out


# ---------------------------------------------------------------- campagnes
class CampaignIn(BaseModel):
    config: dict


@app.post(f"{API}/campaigns")
def create_campaign(body: CampaignIn, lab=Depends(L)):
    from ..evolution import campaign
    try:
        cid, tid = campaign.create(lab, body.config)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"campaign_id": cid, "task_id": tid}


@app.get(f"{API}/campaigns")
def campaigns(lab=Depends(L)):
    out = rows(lab.con.execute("SELECT c.id, c.name, c.state, c.task_id, c.created_at, t.state AS task_state, t.progress "
                               "FROM campaigns c LEFT JOIN tasks t ON t.id=c.task_id ORDER BY c.created_at DESC"))
    for c in out:
        c["n_candidates"] = lab.con.execute("SELECT COUNT(*) FROM genome_revisions WHERE campaign_id=?", (c["id"],)).fetchone()[0]
    return out


@app.get(f"{API}/campaigns/{{cid}}")
def campaign_detail(cid: str, lab=Depends(L)):
    from ..tasks import checkpoints
    c = lab.con.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
    if not c:
        raise HTTPException(404, "campagne inconnue")
    c = dict(c)
    c["config"] = json.loads(c.pop("config_json"))
    st = checkpoints.latest(lab.con, lab.store, c["task_id"])
    c["task"] = queue.get(lab.con, c["task_id"])
    c["state_snapshot"] = None if st is None else {
        "phase": st["phase"], "gen": st["gen"], "history": st["history"], "op_stats": st["op_stats"],
        "stagnation": st["stagnation"], "archives": {k: len(v) for k, v in st["archives"].items()},
        "populations": {k: len(v) for k, v in st["pops"].items()}}
    c["n_candidates"] = lab.con.execute("SELECT COUNT(*) FROM genome_revisions WHERE campaign_id=?", (cid,)).fetchone()[0]
    c["n_evaluations"] = lab.con.execute("SELECT COUNT(*) FROM evaluations WHERE campaign_id=?", (cid,)).fetchone()[0]
    return c


@app.get(f"{API}/campaigns/{{cid}}/candidates")
def campaign_candidates(cid: str, segment: str = "train", limit: int = 500, lab=Depends(L)):
    """Candidats évalués (y compris rejetés) avec métriques du segment demandé."""
    rs = rows(lab.con.execute(
        "SELECT r.id, r.status, r.genome_id, r.revision, e.metrics_json FROM genome_revisions r JOIN evaluations e "
        "ON e.revision_id=r.id AND e.segment=? WHERE r.campaign_id=? ORDER BY e.created_at DESC LIMIT ?",
        (segment, cid, min(limit, 5000))))
    for r in rs:
        m = json.loads(r.pop("metrics_json"))
        r["metrics"] = {k: m.get(k) for k in ("n_trades", "net_profit", "return_pct", "profit_factor", "sharpe",
                                              "max_dd_pct", "expectancy_r", "win_rate", "r2_equity")}
    return rs


# ---------------------------------------------------------------- sauvegardes
@app.post(f"{API}/backups")
def backup_now(lab=Depends(L)):
    return submit(lab, "backup", {}, priority=10)


@app.get(f"{API}/backups")
def backups(lab=Depends(L)):
    return [{"name": p.name, "size": p.stat().st_size} for p in sorted(lab.paths.backups.glob("*"), reverse=True)]


class VerifyBackup(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9._-]+$")


@app.post(f"{API}/backups/verify")
def verify_backup(body: VerifyBackup, lab=Depends(L)):
    """Restaure dans un répertoire temporaire et vérifie empreintes + références (sans toucher aux données)."""
    import shutil
    import tempfile
    from ..storage.backup import restore_backup
    arc = lab.paths.backups / body.name
    if not arc.exists() or arc.suffix != ".zip":
        raise HTTPException(404, "sauvegarde inconnue")
    d = Path(tempfile.mkdtemp(prefix="qlab-verify-"))
    try:
        return restore_backup(arc, d / "r")
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- événements
@app.get(f"{API}/events")
async def events(request: Request):
    async def gen():
        last = ""
        while not await request.is_disconnected():
            lab = Lab.attach(STATE["root"])
            try:
                rs = rows(lab.con.execute("SELECT id, kind, state, progress, error, updated_at FROM tasks "
                                          "WHERE updated_at > ? ORDER BY updated_at", (last,)))
            finally:
                lab.close()
            for r in rs:
                last = max(last, r["updated_at"])
                ev = {"type": "task.updated", "correlation_id": r["id"], "ts": utc_now_iso(), "task": r}
                yield f"data: {json.dumps(ev)}\n\n"
            yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------------------------------------------------------- worker et démarrage
def worker_loop(root: str, stop: threading.Event) -> None:
    lab = Lab.attach(root)
    try:
        while not stop.is_set():
            try:
                t = runner.run_next(lab)
            except Exception as e:  # le worker ne meurt pas sur une erreur inattendue
                lab.log.error("worker.error", error=repr(e))
                t = None
            if t is None:
                stop.wait(1.0)
    finally:
        lab.close()


def free_port(host: str) -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def main() -> None:
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser(description="QLab API locale")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-worker", action="store_true")
    a = ap.parse_args()
    token = os.environ.get("QLAB_API_TOKEN")
    if not token or len(token) < 24:
        raise SystemExit("QLAB_API_TOKEN (>= 24 caractères) requis")
    lab = Lab.open(a.data_dir)  # migrations ici, une seule fois
    host = lab.settings["api"]["host"]
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("hôte API non local refusé")
    recovered = queue.recover_interrupted(lab.con)
    if recovered:
        lab.log.warning("tasks.recovered_paused", tasks=recovered)
    STATE.update(root=str(lab.paths.root), token=token)
    lab.close()
    if not a.no_worker:
        STATE["worker"] = threading.Thread(target=worker_loop, args=(STATE["root"], STATE["stop"]), daemon=True)
        STATE["worker"].start()
    port = a.port or free_port(host)
    print(f"QLAB_API_READY port={port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    STATE["stop"].set()


if __name__ == "__main__":
    main()
