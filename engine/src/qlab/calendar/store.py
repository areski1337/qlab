"""Stockage local du calendrier, couverture, fenêtres d'interdiction et fichier lu par l'EA."""
from __future__ import annotations

import json
from pathlib import Path

from ..core.timeutil import utc_now_iso
from ..storage.db import audit
from . import fxstreet
from .windows import NewsWindows, build, symbol_currencies


def refresh(lab, start_ts: int, end_ts: int, fetch=fxstreet.fetch_range) -> dict:
    """Récupère et enregistre les événements ; la couverture n'est enregistrée qu'après succès complet."""
    raw = fetch(start_ts, end_ts)
    sha = lab.store.put_json(raw, kind="calendar_raw", meta={"source": fxstreet.SOURCE, "range": [start_ts, end_ts]})
    now = utc_now_iso()
    n = 0
    for ev in raw:
        e = fxstreet.normalize(ev)
        lab.con.execute("INSERT OR REPLACE INTO economic_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            e["id"], fxstreet.SOURCE, e["event_id"], e["date_ts"], e["currency"], e["country"], e["name"],
            e["volatility"], int(e["is_tentative"]), int(e["is_all_day"]), e["actual"], e["consensus"],
            e["previous"], e["last_updated"], now))
        n += 1
    lab.con.execute("INSERT INTO calendar_coverage (source, start_ts, end_ts, n_events, raw_artifact, fetched_at) "
                    "VALUES (?,?,?,?,?,?)", (fxstreet.SOURCE, start_ts, end_ts, n, sha, now))
    audit(lab.con, "calendar.refreshed", None, source=fxstreet.SOURCE, start=start_ts, end=end_ts, n=n)
    return {"events": n, "start": start_ts, "end": end_ts}


def windows_for(lab, spec: dict, limits: dict) -> NewsWindows | None:
    nf = limits.get("news_filter") or {}
    if not nf.get("enabled"):
        return None
    cur = symbol_currencies(spec)
    evs = [dict(r) for r in lab.con.execute(
        "SELECT date_ts, currency, volatility, is_tentative, is_all_day FROM economic_events WHERE source=?",
        (fxstreet.SOURCE,))]
    cov = [(r[0], r[1]) for r in lab.con.execute("SELECT start_ts, end_ts FROM calendar_coverage WHERE source=?",
                                                 (fxstreet.SOURCE,))]
    return build(evs, cov, cur, nf["before_min"], nf["after_min"], nf["min_volatility"], fxstreet.SOURCE)


def status(lab) -> dict:
    cov = lab.con.execute("SELECT MIN(start_ts), MAX(end_ts), COUNT(*), MAX(fetched_at) FROM calendar_coverage").fetchone()
    n = lab.con.execute("SELECT COUNT(*) FROM economic_events").fetchone()[0]
    return {"source": fxstreet.SOURCE, "credentials_configured": fxstreet.credentials() is not None,
            "events": n, "coverage_from": cov[0], "coverage_to": cov[1], "refreshes": cov[2], "last_refresh": cov[3]}


def write_ea_file(path: Path, w: NewsWindows | None, enabled: bool) -> Path:
    """Fichier lu par l'EA (dossier commun MT5) : COV;début;fin et BLK;début;fin en secondes UTC."""
    lines = [f"QLAB_NEWS;1;{1 if enabled else 0}"]
    if w is not None:
        lines += [f"COV;{a};{b}" for a, b in w.coverage.tolist()]
        lines += [f"BLK;{a};{b}" for a, b in w.blocked.tolist()]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    tmp.replace(path)
    return path
