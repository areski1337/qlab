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

from fastapi import Depends, FastAPI, HTTPException, Query, Request
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
    if not STATE["token"] or not hmac.compare_digest(tok.encode(), STATE["token"].encode()):
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
    daily_profit_target_pct: float | None = None
    close_before_weekend_minutes: int | None = None
    news_filter: dict = {"enabled": False, "before_min": 30, "after_min": 30, "min_volatility": "HIGH"}
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


# ---------------------------------------------------------------- calendrier économique (FXStreet)
@app.get(f"{API}/calendar")
def calendar_status(limit: int = 200, lab=Depends(L)):
    from ..calendar import store
    st = store.status(lab)
    st["upcoming_high"] = rows(lab.con.execute(
        "SELECT date_ts, currency, name, volatility, is_tentative FROM economic_events WHERE date_ts >= strftime('%s','now') "
        "AND volatility IN ('HIGH','MEDIUM') ORDER BY date_ts LIMIT ?", (min(limit, 1000),)))
    return st


class CalRefresh(BaseModel):
    date_from: str = Field(alias="from")
    date_to: str = Field(alias="to")


@app.post(f"{API}/calendar/refresh")
def calendar_refresh(body: CalRefresh, lab=Depends(L)):
    from ..calendar import fxstreet
    from ..core.timeutil import iso_to_ts
    if fxstreet.credentials() is None:
        raise HTTPException(409, "clés FXStreet absentes : définir QLAB_FXSTREET_CLIENT_ID et QLAB_FXSTREET_CLIENT_SECRET "
                                 "(variables d'environnement) puis redémarrer QLab")
    a, b = iso_to_ts(body.date_from + "T00:00:00Z"), iso_to_ts(body.date_to + "T00:00:00Z")
    if b <= a or b - a > 7 * 366 * 86400:
        raise HTTPException(422, "plage invalide (au plus 7 ans)")
    return submit(lab, "calendar_refresh", {"start": a, "end": b})


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


# ---------------------------------------------------------------- bibliothèque de stratégies
@app.get(f"{API}/library")
def library(lab=Depends(L)):
    """Stratégies annotées ou ayant franchi le filtrage, avec la dernière évaluation de recherche (ou train)."""
    out = rows(lab.con.execute(
        "SELECT g.id, g.status, g.campaign_id, g.created_at, COALESCE(n.favorite,0) AS favorite, "
        "COALESCE(n.tags_json,'[]') AS tags_json, COALESCE(n.note,'') AS note, "
        "(SELECT metrics_json FROM evaluations e WHERE e.revision_id=g.id AND e.segment IN ('research','train') "
        " ORDER BY e.segment='research' DESC, e.created_at DESC LIMIT 1) AS metrics_json "
        "FROM genome_revisions g LEFT JOIN strategy_notes n ON n.revision_id=g.id "
        "WHERE n.revision_id IS NOT NULL OR g.status NOT IN ('unverified','rejected') ORDER BY g.created_at DESC LIMIT 2000"))
    for r in out:
        r["tags"] = json.loads(r.pop("tags_json"))
        r["metrics"] = json.loads(r.pop("metrics_json") or "null")
    return out


class NotesIn(BaseModel):
    favorite: bool = False
    tags: list[str] = Field(default_factory=list, max_length=20)
    note: str = Field("", max_length=5000)


@app.put(f"{API}/genomes/{{rid}}/notes")
def put_notes(rid: str, body: NotesIn, lab=Depends(L)):
    if not lab.con.execute("SELECT 1 FROM genome_revisions WHERE id=?", (rid,)).fetchone():
        raise HTTPException(404, "révision inconnue")
    tags = sorted({t.strip()[:32] for t in body.tags if t.strip()})
    lab.con.execute("INSERT INTO strategy_notes VALUES (?,?,?,?,?) ON CONFLICT(revision_id) DO UPDATE SET "
                    "favorite=excluded.favorite, tags_json=excluded.tags_json, note=excluded.note, updated_at=excluded.updated_at",
                    (rid, int(body.favorite), json.dumps(tags), body.note, utc_now_iso()))
    return {"revision_id": rid, "favorite": body.favorite, "tags": tags, "note": body.note}


# ---------------------------------------------------------------- planification
@app.get(f"{API}/schedules")
def schedules_list(lab=Depends(L)):
    out = rows(lab.con.execute("SELECT * FROM schedules ORDER BY created_at DESC"))
    for r in out:
        r["payload"] = json.loads(r.pop("payload_json"))
    return out


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str
    payload: dict
    every: str = "once"
    first_run_utc: str


@app.post(f"{API}/schedules")
def schedules_add(body: ScheduleIn, lab=Depends(L)):
    from ..tasks import schedules
    try:
        return schedules.add(lab.con, body.name, body.kind, body.payload, body.every, body.first_run_utc)
    except ValueError as e:
        raise HTTPException(422, str(e))


class Enabled(BaseModel):
    enabled: bool


@app.put(f"{API}/schedules/{{sid}}")
def schedules_enable(sid: str, body: Enabled, lab=Depends(L)):
    n = lab.con.execute("UPDATE schedules SET enabled=?, last_error=NULL WHERE id=?", (int(body.enabled), sid)).rowcount
    if not n:
        raise HTTPException(404, "planification inconnue")
    return {"id": sid, "enabled": body.enabled}


@app.get(f"{API}/strategy-bases")
def strategy_bases():
    from ..evolution.operators import BASES
    return [{"id": k, "label": v[0], "description": v[1]} for k, v in BASES.items()]


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
    transfer_datasets: dict[str, str] = {}


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
        return submit(lab, "advance", {**p, "stop_at": body.stop_at, "transfer_datasets": body.transfer_datasets})
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


@app.get(f"{API}/campaigns/estimate")
def campaign_estimate(dataset_version_id: str, n: int = Query(ge=0, le=10_000_000), lab=Depends(L)):
    """Budget d'essais : N total sur la série, Sharpe minimal requis pour passer le DSR (avant lancement)."""
    from ..validation import budget
    try:
        return budget.estimate(lab, dataset_version_id, n)
    except KeyError:
        raise HTTPException(404, "version de dataset inconnue")


@app.get(f"{API}/campaigns/{{cid}}/funnel")
def campaign_funnel(cid: str, lab=Depends(L)):
    from ..validation import budget
    if not lab.con.execute("SELECT 1 FROM campaigns WHERE id=?", (cid,)).fetchone():
        raise HTTPException(404, "campagne inconnue")
    return budget.funnel(lab, cid)


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
    c["n_evaluations"] = lab.con.execute("SELECT COUNT(DISTINCT e.id) FROM evaluations e JOIN genome_revisions g "
                                         "ON g.id=e.revision_id WHERE g.campaign_id=?", (cid,)).fetchone()[0]
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


# ---------------------------------------------------------------- portefeuilles
class PortfolioIn(BaseModel):
    name: str = "Portefeuille"
    revision_ids: list[str]
    method: str = "min_corr"
    segment: str = "research"
    w_min: float = Field(0.05, ge=0, le=1)
    w_max: float = Field(0.5, gt=0, le=1)


@app.post(f"{API}/portfolios")
def create_portfolio(body: PortfolioIn, lab=Depends(L)):
    from ..portfolio import service
    if body.segment == "final":
        raise HTTPException(403, "le holdout final n'est pas utilisable pour construire un portefeuille")
    ok = ("oos_evaluated", "reference_matched", "mt5_validated", "demo_observed")
    bad = [r for r in body.revision_ids
           if (lab.con.execute("SELECT status FROM genome_revisions WHERE id=?", (r,)).fetchone() or [None])[0] not in ok]
    if bad:
        raise HTTPException(409, f"stratégies non validées hors échantillon (statut >= oos_evaluated requis) : {bad}")
    try:
        return service.build(lab, body.name, body.revision_ids, body.method, body.segment, body.w_min, body.w_max)
    except ValueError as e:
        raise HTTPException(422, str(e))


class PortfolioFromCampaign(BaseModel):
    campaign_id: str
    method: str = "min_corr"
    w_min: float = Field(0.05, ge=0, le=1)
    w_max: float = Field(0.5, gt=0, le=1)


@app.post(f"{API}/portfolios/from-campaign")
def portfolio_from_campaign(body: PortfolioFromCampaign, lab=Depends(L)):
    """Portefeuille des révisions de la campagne validées hors échantillon (statut >= oos_evaluated, non rejetées) :
    poids sur la recherche, performance rapportée aussi hors échantillon."""
    from ..portfolio import service
    ok = ("oos_evaluated", "reference_matched", "mt5_validated", "demo_observed")
    ids = [r[0] for r in lab.con.execute(
        f"SELECT id FROM genome_revisions WHERE campaign_id=? AND status IN ({','.join('?' * len(ok))})",
        (body.campaign_id, *ok))]
    if len(ids) < 2:
        raise HTTPException(409, f"{len(ids)} stratégie(s) éligible(s) (statut >= oos_evaluated, non rejetée) : "
                                 "au moins deux requises")
    try:
        return service.build(lab, f"Portefeuille {body.campaign_id}", ids, body.method, "research", body.w_min, body.w_max)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get(f"{API}/portfolios")
def portfolios(lab=Depends(L)):
    out = rows(lab.con.execute("SELECT * FROM portfolios ORDER BY created_at DESC"))
    for p in out:
        p["allocations"] = rows(lab.con.execute("SELECT revision_id, weight FROM portfolio_allocations WHERE portfolio_id=?", (p["id"],)))
    return out


@app.get(f"{API}/portfolios/{{pid}}")
def portfolio(pid: str, lab=Depends(L)):
    r = lab.con.execute("SELECT * FROM portfolios WHERE id=?", (pid,)).fetchone()
    if not r:
        raise HTTPException(404, "portefeuille inconnu")
    return {**dict(r), "report": lab.store.get_json(r["report_artifact"])}


# ---------------------------------------------------------------- démo (lecture seule)
@app.get(f"{API}/demo")
def demo_list(lab=Depends(L)):
    from ..demo.monitor import flag_path
    out = rows(lab.con.execute("SELECT * FROM demo_deployments ORDER BY started_at DESC"))
    for d in out:
        last = lab.con.execute("SELECT observed_at, report_json FROM demo_observations WHERE deployment_id=? "
                               "ORDER BY observed_at DESC LIMIT 1", (d["id"],)).fetchone()
        d["last_observation"] = {"at": last[0], **json.loads(last[1])} if last else None
    from ..demo.monitor import guard_states
    try:
        emergency = flag_path(lab).exists()
        guards = guard_states(lab)
    except FileNotFoundError:
        emergency, guards = None, []
    return {"deployments": out, "emergency_stop": emergency, "account_guards": guards,
            "news_filter": "actif si activé dans les limites et calendrier FXStreet couvrant la période ; sinon entrées refusées",
            "weekend_close": "configurable (limites de risque)"}


class DemoReg(BaseModel):
    revision_id: str


@app.post(f"{API}/demo/register")
def demo_register(body: DemoReg, lab=Depends(L)):
    from ..demo import monitor
    try:
        return monitor.register(lab, body.revision_id)
    except PermissionError as e:
        raise HTTPException(409, str(e))


class Flag(BaseModel):
    on: bool
    reason: str = "manuel"


@app.post(f"{API}/demo/emergency-stop")
def emergency(body: Flag, lab=Depends(L)):
    from ..demo import monitor
    try:
        return monitor.set_flag(lab, None, body.on, body.reason)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))


@app.post(f"{API}/demo/guards/{{login}}/reset")
def demo_guard_reset(login: str, body: Flag | None = None, lab=Depends(L)):
    from ..demo import monitor
    try:
        return monitor.reset_guard(lab, login, body.reason if body else "levée manuelle")
    except ValueError as e:
        raise HTTPException(422, str(e))
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))


@app.post(f"{API}/demo/{{did}}/{{action}}")
def demo_action(did: str, action: str, body: Flag | None = None, lab=Depends(L)):
    from ..demo import monitor
    dep = lab.con.execute("SELECT * FROM demo_deployments WHERE id=?", (did,)).fetchone()
    if not dep:
        raise HTTPException(404, "déploiement inconnu")
    if action == "observe":
        return submit(lab, "demo_observe", {"deployment_id": did})
    if action == "promote":
        try:
            return monitor.promote_stage(lab, did)
        except PermissionError as e:
            raise HTTPException(409, str(e))
    if action == "suspend":
        try:
            return monitor.set_flag(lab, dep["magic"], body.on if body else True, body.reason if body else "manuel")
        except FileNotFoundError as e:
            raise HTTPException(503, str(e))
    raise HTTPException(400, "action inconnue")


# ---------------------------------------------------------------- expériences sur le moteur (section 18)
class ExperimentIn(BaseModel):
    hypothesis: str = Field(min_length=10)
    spec: dict


@app.post(f"{API}/engine-experiments")
def create_experiment(body: ExperimentIn, lab=Depends(L)):
    from ..evolution import meta
    try:
        eid, tid = meta.create(lab, body.hypothesis, body.spec)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e))
    return {"experiment_id": eid, "task_id": tid}


@app.get(f"{API}/engine-experiments")
def experiments(lab=Depends(L)):
    from ..evolution import meta
    out = rows(lab.con.execute("SELECT id, hypothesis, spec_json, task_id, results_json, verdict, created_at "
                               "FROM engine_experiments ORDER BY created_at DESC"))
    for e in out:
        e["spec"] = json.loads(e.pop("spec_json"))
        e["results"] = json.loads(e.pop("results_json")) if e["results_json"] else None
    return {"experiments": out, "experimental_overrides": meta.experimental_overrides(lab),
            "method_keys": sorted(meta.METHOD_KEYS), "metrics": sorted(meta.METRICS),
            "history": rows(lab.con.execute("SELECT * FROM engine_promotions ORDER BY id DESC LIMIT 50"))}


@app.post(f"{API}/engine-experiments/{{eid}}/promote")
def promote_experiment(eid: str, lab=Depends(L)):
    from ..evolution import meta
    try:
        return {"experimental_overrides": meta.promote(lab, eid)}
    except PermissionError as e:
        raise HTTPException(409, str(e))


@app.post(f"{API}/engine-rollback")
def engine_rollback(lab=Depends(L)):
    from ..evolution import meta
    return {"experimental_overrides": meta.rollback(lab)}


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
def calendar_tick(lab, state: dict) -> None:
    """Toutes les 6 h, si des clés FXStreet sont configurées : rafraîchit [-1 j, +14 j] et réécrit les fichiers
    d'annonces lus par les EA des déploiements démo actifs. Un échec est journalisé ; les EA refusent alors les
    entrées dès que la couverture expire (aucune donnée inventée)."""
    import time as _t
    from ..calendar import fxstreet, store
    if fxstreet.credentials() is None or _t.time() - state.get("last", 0) < 6 * 3600:
        return
    state["last"] = _t.time()
    now = int(_t.time())
    try:
        store.refresh(lab, now - 86400, now + 14 * 86400)
        from ..demo.monitor import publish_news_files
        publish_news_files(lab)
    except Exception as e:
        lab.log.error("calendar.refresh_failed", error=str(e))


def worker_loop(root: str, stop: threading.Event) -> None:
    lab = Lab.attach(root)
    cal_state: dict = {}
    try:
        while not stop.is_set():
            calendar_tick(lab, cal_state)
            try:
                from ..tasks import schedules
                schedules.tick(lab)
            except Exception as e:
                lab.log.error("schedules.error", error=repr(e))
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
