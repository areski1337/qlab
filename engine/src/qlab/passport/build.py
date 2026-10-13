"""Passeport de stratégie : tout ce qui permet de comprendre, reproduire et contester un résultat.

Le rapport sépare explicitement :
- observations : valeurs mesurées par le moteur (avec leur provenance) ;
- hypothèses   : conventions et paramètres supposés (coûts, fuseau, intrabar…) ;
- interprétations : lectures prudentes générées à partir de règles fixes ;
- non vérifié  : étapes absentes ou bloquées.
"""
from __future__ import annotations

import html
import io
import json
import zipfile

import numpy as np

from ..core.hashing import sha256_bytes
from ..core.timeutil import ts_to_iso, utc_now, utc_now_iso
from ..core.versions import versions_snapshot
from ..genome import model, store as gstore
from ..storage.db import audit

DISCLAIMER = ("Aucune stratégie n'est garantie rentable. Les performances passées, même hors échantillon, "
              "ne préjugent pas des performances futures. Le meilleur résultat d'une recherche portant sur de "
              "nombreux candidats est biaisé à la hausse.")


def _evals(con, rid):
    rows = con.execute("SELECT e.*, v.content_sha256 AS dataset_sha256, v.version AS dataset_version, d.canonical_symbol, "
                       "d.timeframe, d.synthetic FROM evaluations e JOIN dataset_versions v ON v.id=e.dataset_version_id "
                       "JOIN datasets d ON d.id=v.dataset_id WHERE e.revision_id=? ORDER BY e.created_at", (rid,))
    out = []
    for r in rows:
        d = dict(r)
        for k in ("metrics_json", "window_json", "versions_json", "context_versions_json", "protocol_json"):
            d[k[:-5]] = json.loads(d.pop(k))
        out.append(d)
    return out


def build(lab, rid: str) -> dict:
    con = lab.con
    rev = gstore.get(con, rid)
    g = rev["content"]
    evals = _evals(con, rid)
    trs = gstore.transitions(con, rid)
    rob_sha = next((t["evidence"].get("robustness_report") for t in reversed(trs) if "robustness_report" in t["evidence"]), None)
    robustness = lab.store.get_json(rob_sha) if rob_sha else None
    research = next((e for e in reversed(evals) if e["segment"] == "research" and e["trades_artifact"]), None)
    oos = next((e for e in reversed(evals) if e["segment"] == "oos"), None)
    final = next((e for e in reversed(evals) if e["segment"] == "final"), None)
    curve = None
    trades_sample = []
    if research:
        tr = lab.store.get_json(research["trades_artifact"])["trades"]
        eq0 = research["metrics"]["initial_equity"]
        curve = {"ts": [t["exit_ts"] for t in tr], "equity": list(np.round(eq0 + np.cumsum([t["pnl"] for t in tr]), 2)),
                 "unit": "devise du compte", "segment": "train+validation"}
        trades_sample = tr[:200]
    eas = [dict(r) for r in con.execute("SELECT * FROM ea_artifacts WHERE revision_id=?", (rid,))]
    comps, pars = [], []
    for ea in eas:
        comps += [dict(r) for r in con.execute("SELECT * FROM compilation_runs WHERE ea_id=? ORDER BY created_at", (ea["id"],))]
        for r in con.execute("SELECT * FROM parity_runs WHERE ea_id=? ORDER BY created_at", (ea["id"],)):
            d = dict(r)
            d["report"] = json.loads(d.pop("report_json")) if d["report_json"] else None
            if d["report"]:
                d["report"].pop("matched_sample", None)
            pars.append(d)
    n_candidates = None
    if rev["campaign_id"]:
        n_candidates = con.execute("SELECT COUNT(*) FROM genome_revisions WHERE campaign_id=?", (rev["campaign_id"],)).fetchone()[0]

    hyp = ["Exécution : signal à la clôture de barre, ordre au marché à l'ouverture suivante.",
           "Stop et objectif atteints dans la même barre OHLC : le stop est retenu (convention conservatrice).",
           "Drawdown mesuré sur l'equity de clôture des trades (flottant intra-trade non inclus).",
           "Sharpe/Sortino sur rendements journaliers (journée 17:00 New York), annualisés √252, taux sans risque 0."]
    datasets = {}
    for e in evals:
        datasets[e["dataset_version_id"]] = {"sha256": e["dataset_sha256"], "symbol": e["canonical_symbol"],
                                             "timeframe": e["timeframe"], "version": e["dataset_version"],
                                             "synthetic": bool(e["synthetic"]), "context": e["context_versions"]}
        if e["synthetic"]:
            hyp.append("DONNÉES SYNTHÉTIQUES : aucun enseignement sur un marché réel.")
    for dv in datasets:
        row = con.execute("SELECT source_timezone, symbol_spec_json FROM dataset_versions WHERE id=?", (dv,)).fetchone()
        hyp.append(f"Fuseau serveur déclaré du dataset {dv} : {row['source_timezone']}.")
    cost_rows = {e["cost_profile_sha256"] for e in evals}
    hyp.append(f"Profils de coûts utilisés (empreintes) : {sorted(cost_rows)} — valeurs 'assumed' non observées "
               "sauf mention contraire.")

    unverified = []
    ladder = gstore.LADDER
    cur = rev["status"]
    if cur in ("rejected", "quarantined"):
        unverified.append(f"Statut {cur} : la stratégie ne doit pas être utilisée.")
    else:
        unverified += [f"Étape non atteinte : {s}" for s in ladder[ladder.index(cur) + 1:]]
    if not comps:
        unverified.append("EA MQL5 jamais compilé.")
    if not pars or not any(p["status"] == "completed" for p in pars):
        unverified.append("Parité MT5 non mesurée.")
    if final is None:
        unverified.append("Test final indépendant non exécuté.")

    interp = []
    if oos and research:
        mi, mo = research["metrics"], oos["metrics"]
        if mi.get("expectancy_r") and mo.get("expectancy_r") is not None:
            ratio = mo["expectancy_r"] / mi["expectancy_r"] if mi["expectancy_r"] else None
            if ratio is not None:
                interp.append(f"Expectancy (R) hors échantillon = {ratio:.0%} de celle de la recherche "
                              f"({'dégradation' if ratio < 0.7 else 'cohérence'} ; interprétation, non une prévision).")
    if robustness:
        failed = [k for k, c in robustness["checks"].items() if c["pass"] is not True]
        interp.append("Tests de robustesse : tous satisfaits." if not failed else f"Robustesse : échecs ou non calculables {failed}.")
    if n_candidates and n_candidates > 1:
        interp.append(f"Sélectionnée parmi {n_candidates} candidats : biais de sélection probable.")

    p = {
        "passport_version": "1.0",
        "generated_at": utc_now_iso(),
        "identity": {"revision_id": rid, "genome_id": rev["genome_id"], "revision": rev["revision"],
                     "semantic_hash": rev["semantic_hash"], "status": cur, "campaign_id": rev["campaign_id"]},
        "rules": model.describe(g),
        "genome": g,
        "lineage": gstore.lineage(con, rid),
        "risk": {"requested_risk_pct": g["sizing"]["risk_pct"],
                 "note": "plafonné par les limites absolues du contrôleur de risque (empreinte dans chaque évaluation)"},
        "datasets": datasets,
        "versions": versions_snapshot(),
        "observations": {
            "evaluations": [{k: e[k] for k in ("id", "segment", "window", "metrics", "dataset_version_id",
                                                "cost_profile_sha256", "risk_limits_sha256", "versions", "created_at",
                                                "trades_artifact")} for e in evals],
            "equity_curve": curve,
            "trades_sample": trades_sample,
            "robustness": robustness,
            "oos": oos["metrics"] if oos else None,
            "final_holdout": final["metrics"] if final else None,
            "compilations": comps, "parity": pars,
            "multiplicity": {"campaign_candidates": n_candidates},
        },
        "hypotheses": hyp,
        "interpretations": interp,
        "unverified": unverified,
        "status_history": trs,
        "artifacts": sorted({a for e in evals for a in [e["trades_artifact"]] if a} | ({rob_sha} if rob_sha else set())
                            | {c["log_artifact"] for c in comps if c["log_artifact"]}
                            | {c["ex5_artifact"] for c in comps if c["ex5_artifact"]}
                            | {e["source_sha256"] for e in eas}),
        "disclaimer": DISCLAIMER,
    }
    return p


def _svg_curve(curve) -> str:
    if not curve or len(curve["equity"]) < 2:
        return "<p><em>Courbe indisponible (aucune évaluation de recherche avec trades conservés).</em></p>"
    y = np.array(curve["equity"], float)
    W, H, pad = 760, 220, 30
    lo, hi = float(y.min()), float(y.max())
    hi = hi if hi > lo else lo + 1
    xs = np.linspace(pad, W - pad, len(y))
    ys = H - pad - (y - lo) / (hi - lo) * (H - 2 * pad)
    pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in zip(xs, ys))
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Courbe de capital">'
            f'<polyline fill="none" stroke="currentColor" stroke-width="1.5" points="{pts}"/>'
            f'<text x="{pad}" y="14" font-size="11">max {hi:,.0f}</text>'
            f'<text x="{pad}" y="{H - 8}" font-size="11">min {lo:,.0f} — {html.escape(curve["unit"])}, '
            f'{ts_to_iso(curve["ts"][0])} → {ts_to_iso(curve["ts"][-1])} ({html.escape(curve["segment"])})</text></svg>')


def render_html(p: dict) -> str:
    e = html.escape
    rows = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in p["rules"].items())
    ev = "".join(
        f"<tr><td>{e(x['segment'])}</td><td>{x['metrics']['n_trades']}</td><td>{_f(x['metrics'].get('net_profit'))}</td>"
        f"<td>{_f(x['metrics'].get('profit_factor'))}</td><td>{_f(x['metrics'].get('sharpe'))}</td>"
        f"<td>{_f(x['metrics'].get('max_dd_pct'))}</td><td><code>{e(x['dataset_version_id'])}</code></td></tr>"
        for x in p["observations"]["evaluations"])
    lst = lambda xs: "<ul>" + "".join(f"<li>{e(str(x))}</li>" for x in xs) + "</ul>"
    par = "".join(f"<li>{e(x['status'])} — note {e(str(x['grade']))}, critique : {e(str(x['critical']))}"
                  f"{' — ' + e(x['diagnostic']) if x['diagnostic'] else ''}</li>" for x in p["observations"]["parity"]) or "<li>aucune</li>"
    comp = "".join(f"<li>{e(c['status'])} — {c['errors']} erreur(s), {c['warnings']} avertissement(s)"
                   f"{' — ' + e(c['diagnostic']) if c['diagnostic'] else ''}</li>" for c in p["observations"]["compilations"]) or "<li>aucune</li>"
    st = "".join(f"<li>{e(t['ts'])} : {e(t['from_status'])} → <strong>{e(t['to_status'])}</strong></li>" for t in p["status_history"])
    rob = p["observations"]["robustness"]
    def num(v):
        return f"{v:.4g}" if isinstance(v, float) else str(v)
    verdict = lambda ok: "OK" if ok else ("non calculable" if ok is None else "ÉCHEC")
    robh = ("<ul>" + "".join(f"<li>{e(k)} : {e(num(c['value']))} → {verdict(c['pass'])}</li>"
                             for k, c in rob["checks"].items()) + "</ul>") if rob else "<p>Non exécutés.</p>"
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Passeport {e(p['identity']['revision_id'])}</title>
<style>:root{{--bg:#fff;--fg:#1b1f24;--mut:#5b6470;--bd:#d8dde3;--warn:#8a5a00}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171b;--fg:#e6e9ed;--mut:#9aa3ad;--bd:#2c333b;--warn:#e0b050}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,Segoe UI,sans-serif;max-width:900px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid var(--bd);padding:4px 6px;text-align:left;vertical-align:top}}
th{{color:var(--mut);font-weight:500}}code{{font-size:12px}}.warn{{color:var(--warn);border:1px solid var(--warn);padding:8px;border-radius:6px}}
h2{{margin-top:28px;border-bottom:1px solid var(--bd)}}</style></head><body>
<h1>Passeport de stratégie</h1>
<p><code>{e(p['identity']['revision_id'])}</code> — statut <strong>{e(p['identity']['status'])}</strong> — empreinte <code>{e(p['identity']['semantic_hash'][:16])}…</code></p>
<p class="warn">{e(p['disclaimer'])}</p>
<h2>Règles</h2><table>{rows}</table>
<h2>Observations mesurées</h2>
<h3>Évaluations</h3><table><tr><th>segment</th><th>trades</th><th>net</th><th>PF</th><th>Sharpe</th><th>DD %</th><th>dataset</th></tr>{ev}</table>
<h3>Courbe de capital</h3>{_svg_curve(p['observations']['equity_curve'])}
<h3>Robustesse</h3>{robh}
<h3>Compilation MQL5</h3><ul>{comp}</ul>
<h3>Parité MT5</h3><ul>{par}</ul>
<h2>Hypothèses</h2>{lst(p['hypotheses'])}
<h2>Interprétations</h2>{lst(p['interpretations'] or ['aucune'])}
<h2>Non vérifié</h2>{lst(p['unverified'] or ['—'])}
<h2>Historique des statuts</h2><ul>{st or '<li>aucun</li>'}</ul>
<h2>Versions et artefacts</h2><p><code>{e(json.dumps(p['versions']))}</code></p>{lst(p['artifacts'])}
<p style="color:var(--mut)">Généré le {e(p['generated_at'])}.</p></body></html>"""


def _f(x):
    return "—" if x is None else f"{x:,.2f}"


def export_bundle(lab, rid: str) -> dict:
    """Archive d'export : génome, passeport (JSON+HTML), EA source/ex5, manifeste d'empreintes (AT-014)."""
    p = build(lab, rid)
    files = {"genome.json": json.dumps(p["genome"], indent=2, ensure_ascii=False).encode(),
             "passport.json": json.dumps(p, indent=1, ensure_ascii=False, default=str).encode(),
             "passport.html": render_html(p).encode()}
    for ea in lab.con.execute("SELECT * FROM ea_artifacts WHERE revision_id=? ORDER BY created_at DESC LIMIT 1", (rid,)):
        files[f"QLab_{rid}.mq5"] = lab.store.get_bytes(ea["source_sha256"])
        c = lab.con.execute("SELECT ex5_artifact FROM compilation_runs WHERE ea_id=? AND status='succeeded' "
                            "ORDER BY created_at DESC LIMIT 1", (ea["id"],)).fetchone()
        if c:
            files[f"QLab_{rid}.ex5"] = lab.store.get_bytes(c["ex5_artifact"])
    manifest = {"revision_id": rid, "status": p["identity"]["status"], "semantic_hash": p["identity"]["semantic_hash"],
                "versions": p["versions"], "files": {k: sha256_bytes(v) for k, v in files.items()},
                "tests": {"status_history": [(t["to_status"], t["evidence"]) for t in p["status_history"]],
                          "parity_runs": [x["id"] for x in p["observations"]["parity"]]},
                "disclaimer": DISCLAIMER}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
        z.writestr("manifest.json", json.dumps(manifest, indent=1, default=str))
    out = lab.paths.exports / f"qlab-{rid}-{utc_now():%Y%m%dT%H%M%S}.zip"
    out.write_bytes(buf.getvalue())
    audit(lab.con, "export.bundle", rid, path=str(out), files=manifest["files"])
    return {"path": str(out), "manifest": manifest}
