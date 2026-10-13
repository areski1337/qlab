"""Compilation MetaEditor réelle et exécution du Strategy Tester MT5.

Rien n'est simulé : en l'absence d'outil, le statut est `blocked` avec la
cause exacte. MetaEditor renvoie un code de sortie non nul même en cas de
succès : seul le compte-rendu « Result: N errors, M warnings » du journal fait foi.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..storage.db import audit
from . import generator

RESULT_RE = re.compile(r"Result:\s*(\d+)\s+errors?,\s*(\d+)\s+warnings?", re.I)


def read_utf16_log(p: Path) -> str:
    b = p.read_bytes()
    for enc in ("utf-16", "utf-8", "cp1252"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def data_path(settings: dict) -> Path | None:
    """Répertoire de données du terminal (MQL5/, tester/) : configuré, sinon détecté sans lancer MT5."""
    p = settings["mt5"].get("data_path")
    if p and Path(p).exists():
        return Path(p)
    import os
    base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    term = Path(settings["mt5"]["terminal_path"]).parent
    for d in base.glob("*") if base.exists() else []:
        o = d / "origin.txt"
        if o.exists():
            try:
                if Path(read_utf16_log(o).strip().lstrip("﻿")).resolve() == term.resolve():
                    return d
            except OSError:
                continue
    return None


def save_ea(lab, rev: dict, symbol: str, tz_profile: str, limits: dict, limits_sha: str) -> dict:
    out = generator.generate(rev, symbol, tz_profile, limits, limits_sha)
    sha = lab.store.put_bytes(out["source"].encode("utf-8"), kind="ea_source", media_type="text/x-mql5",
                              meta={"revision": rev["id"]})
    row = lab.con.execute("SELECT * FROM ea_artifacts WHERE revision_id=? AND source_sha256=?", (rev["id"], sha)).fetchone()
    if row:
        return dict(row)
    eid = new_id("ea")
    lab.con.execute("INSERT INTO ea_artifacts VALUES (?,?,?,?,?,?,?,?,?)", (
        eid, rev["id"], sha, generator.GENERATOR_VERSION, symbol, tz_profile, limits_sha, json.dumps(out["meta"]),
        utc_now_iso()))
    audit(lab.con, "ea.generated", eid, revision=rev["id"], source_sha256=sha)
    return dict(lab.con.execute("SELECT * FROM ea_artifacts WHERE id=?", (eid,)).fetchone())


def ea_name(ea: dict) -> str:
    return f"QLab_{ea['revision_id']}"


def compile_ea(lab, ea: dict, timeout_s: int = 180) -> dict:
    me = Path(lab.settings["mt5"]["metaeditor_path"])
    dp = data_path(lab.settings)
    rid = new_id("comp")

    def record(status, errors=None, warnings=None, code=None, log_sha=None, ex5_sha=None, diag=None):
        lab.con.execute("INSERT INTO compilation_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            rid, ea["id"], status, errors, warnings, code, str(me), log_sha, ex5_sha, diag, utc_now_iso()))
        audit(lab.con, "ea.compiled", ea["id"], status=status, errors=errors, warnings=warnings, diagnostic=diag)
        return dict(lab.con.execute("SELECT * FROM compilation_runs WHERE id=?", (rid,)).fetchone())

    if not me.exists():
        return record("blocked", diag=f"MetaEditor introuvable : {me}")
    if dp is None:
        return record("blocked", diag="répertoire de données MT5 introuvable (configurer mt5.data_path)")
    target_dir = dp / "MQL5" / "Experts" / "QLab"
    target_dir.mkdir(parents=True, exist_ok=True)
    name = ea_name(ea)
    src = target_dir / f"{name}.mq5"
    src.write_bytes(lab.store.get_bytes(ea["source_sha256"]))
    log = target_dir / f"{name}.compile.log"
    ex5 = target_dir / f"{name}.ex5"
    for p in (log, ex5):
        p.unlink(missing_ok=True)
    try:
        proc = subprocess.run([str(me), f"/compile:{src}", f"/log:{log}"], timeout=timeout_s, capture_output=True)
    except subprocess.TimeoutExpired:
        return record("failed", diag=f"délai de compilation dépassé ({timeout_s} s)")
    for _ in range(50):  # le journal peut apparaître juste après la fin du processus
        if log.exists() and log.stat().st_size > 0:
            break
        time.sleep(0.2)
    if not log.exists():
        return record("failed", code=proc.returncode, diag="aucun journal produit par MetaEditor")
    text = read_utf16_log(log)
    log_sha = lab.store.put_bytes(text.encode("utf-8"), kind="compile_log", media_type="text/plain")
    m = RESULT_RE.search(text)
    if not m:
        return record("failed", code=proc.returncode, log_sha=log_sha, diag="ligne Result absente du journal")
    errors, warnings = int(m.group(1)), int(m.group(2))
    if errors == 0 and ex5.exists():
        ex5_sha = lab.store.put_bytes(ex5.read_bytes(), kind="ea_ex5", media_type="application/octet-stream")
        return record("succeeded", errors, warnings, proc.returncode, log_sha, ex5_sha)
    lines = [l for l in text.splitlines() if " error " in l.lower() or ": error" in l.lower()][:30]
    return record("failed", errors, warnings, proc.returncode, log_sha, diag="\n".join(lines) or "ex5 absent")


def terminal_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/NH"], capture_output=True, text=True)
    return "terminal64.exe" in out.stdout


def run_tester(lab, ea: dict, run_id: str, symbol: str, tf: str, from_date: str, to_date: str,
               deposit: float = 10_000.0, currency: str = "USD", leverage: int = 100, model: int = 1,
               timeout_s: int = 3600) -> dict:
    """Lance le Strategy Tester (terminal fermé requis). model : 0 tous ticks, 1 OHLC M1, 4 ticks réels.

    Retourne {'status', 'trace_path', 'diagnostic', 'config'}.
    """
    term = Path(lab.settings["mt5"]["terminal_path"])
    dp = data_path(lab.settings)
    cfg = {"symbol": symbol, "tf": tf, "from": from_date, "to": to_date, "deposit": deposit, "currency": currency,
           "leverage": leverage, "model": model, "run_id": run_id}
    if not term.exists() or dp is None:
        return {"status": "blocked", "diagnostic": "terminal MT5 ou répertoire de données introuvable", "config": cfg}
    if terminal_running():
        return {"status": "blocked", "config": cfg,
                "diagnostic": "le terminal MT5 est ouvert : le Strategy Tester en ligne de commande exige qu'il "
                              "soit fermé (fermer MT5 puis relancer la vérification de parité)"}
    ex5 = dp / "MQL5" / "Experts" / "QLab" / f"{ea_name(ea)}.ex5"
    if not ex5.exists():
        return {"status": "blocked", "diagnostic": "EA non compilé dans le terminal", "config": cfg}
    common = dp.parent / "Common" / "Files" / "QLab"
    common.mkdir(parents=True, exist_ok=True)
    trace = common / f"{run_id}.csv"
    trace.unlink(missing_ok=True)
    ini = dp / "MQL5" / "Experts" / "QLab" / f"{run_id}.ini"
    ini.write_text("\r\n".join([
        "[Tester]", f"Expert=QLab\\{ea_name(ea)}.ex5", f"Symbol={symbol}", f"Period={tf}", f"Model={model}",
        "ExecutionMode=0", "Optimization=0", f"FromDate={from_date}", f"ToDate={to_date}", "ForwardMode=0",
        f"Deposit={deposit:g}", f"Currency={currency}", f"Leverage={leverage}", "ProfitInPips=0",
        f"Report=QLab\\{run_id}", "ReplaceReport=1", "ShutdownTerminal=1", "Visual=0",
        "[TesterInputs]", "InpTrace=true", f"InpRunId={run_id}", ""]), encoding="utf-16")
    t0 = time.time()
    try:
        subprocess.run([str(term), f"/config:{ini}"], timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "diagnostic": f"Strategy Tester : délai dépassé ({timeout_s} s)", "config": cfg}
    for _ in range(100):
        if trace.exists() and trace.stat().st_size > 0:
            break
        time.sleep(0.3)
    if not trace.exists():
        return {"status": "failed", "config": cfg, "elapsed_s": round(time.time() - t0, 1),
                "diagnostic": "aucune trace produite (voir journaux du testeur dans <data>/Tester/logs)"}
    return {"status": "completed", "trace_path": str(trace), "config": cfg, "elapsed_s": round(time.time() - t0, 1)}
