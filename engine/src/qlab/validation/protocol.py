"""Protocole de validation chronologique et évaluations traçables avec cache exact.

Segments (fractions configurables, ordre chronologique, sans chevauchement) :
  train | validation | oos | final
- train      : recherche (fitness génétique) ;
- validation : sélection/arbitrage pendant la recherche ;
- oos        : évaluation hors échantillon des candidats retenus (multiplicité enregistrée) ;
- final      : test indépendant. Jamais accessible à une campagne. Chaque
               révision évaluée dessus est comptée ; au-delà d'une, le résultat
               n'est plus présenté comme indépendant (biais de sélection).
Les features n'utilisent que le passé : le calcul sur la série complète ne
fuit pas vers les segments antérieurs (vérifié par AT-001).

Frontières datées (`segments_for`) : au premier usage d'une série (dataset), les
fractions sont converties en horodatages et figées. Toute version ultérieure
(ré-import plus long) réutilise ces dates : une barre déjà oos/final ne revient
jamais en train/validation, et les barres postérieures forment le segment
« forward ». La multiplicité (holdout, oos) est comptée par série, toutes
versions confondues.
"""
from __future__ import annotations

import json

import numpy as np

from ..backtest import engine
from ..core.hashing import sha256_json
from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..core.versions import versions_snapshot
from ..metrics.core import compute
from ..storage.db import audit

DEFAULT_PROTOCOL = {"name": "chrono-4seg", "version": "1.0",
                    "fractions": {"train": 0.5, "validation": 0.2, "oos": 0.15, "final": 0.15},
                    "walk_forward_folds": 4}
SEGMENTS = ("train", "validation", "oos", "final")


def segments(n: int, protocol: dict = DEFAULT_PROTOCOL) -> dict[str, tuple[int, int]]:
    fr = protocol["fractions"]
    if abs(sum(fr[s] for s in SEGMENTS) - 1) > 1e-9:
        raise ValueError("les fractions du protocole doivent sommer à 1")
    out, a = {}, 0
    for s in SEGMENTS:
        b = n if s == "final" else a + int(round(n * fr[s]))
        out[s] = (a, b)
        a = b
    return out


def protocol_sha(protocol: dict) -> str:
    return sha256_json({"name": protocol["name"], "fractions": protocol["fractions"]})


def dataset_of(lab, version_id: str | None) -> str | None:
    if lab is None or version_id is None:
        return None
    row = lab.con.execute("SELECT dataset_id FROM dataset_versions WHERE id=?", (version_id,)).fetchone()
    return row[0] if row else None


def segments_for(lab, bars, protocol: dict = DEFAULT_PROTOCOL, freeze: bool = True) -> dict[str, tuple[int, int]]:
    """Segments aux frontières datées de la série (figées au premier usage), plus `forward` (barres postérieures).
    Sans base (calcul pur), retombe sur les fractions de la série fournie. `freeze=False` (estimation, rapport
    informatif) : utilise les frontières figées si elles existent, sans jamais les figer."""
    ds = dataset_of(lab, getattr(bars, "version_id", None))
    if ds is None:
        return {**segments(len(bars), protocol), "forward": (len(bars), len(bars))}
    psha = protocol_sha(protocol)
    row = lab.con.execute("SELECT * FROM segment_boundaries WHERE dataset_id=? AND protocol_sha256=?",
                          (ds, psha)).fetchone()
    if row is None and not freeze:
        return {**segments(len(bars), protocol), "forward": (len(bars), len(bars))}
    if row is None:
        seg = segments(len(bars), protocol)
        ends = {s: int(bars.ts[seg[s][1] - 1]) for s in SEGMENTS}
        lab.con.execute("INSERT OR IGNORE INTO segment_boundaries VALUES (?,?,?,?,?,?,?,?)",
                        (ds, psha, ends["train"], ends["validation"], ends["oos"], ends["final"], bars.version_id,
                         utc_now_iso()))
        audit(lab.con, "segments.fixed", ds, protocol=psha, version=bars.version_id, ends=ends)
        row = lab.con.execute("SELECT * FROM segment_boundaries WHERE dataset_id=? AND protocol_sha256=?",
                              (ds, psha)).fetchone()
    cut = [int(np.searchsorted(bars.ts, row[c], side="right"))
           for c in ("train_end_ts", "validation_end_ts", "oos_end_ts", "final_end_ts")]
    out = {"train": (0, cut[0]), "validation": (cut[0], cut[1]), "oos": (cut[1], cut[2]), "final": (cut[2], cut[3]),
           "forward": (cut[3], len(bars))}
    return out


def walk_forward(n: int, protocol: dict = DEFAULT_PROTOCOL, end: int | None = None) -> list[dict]:
    """Fenêtres glissantes ancrées couvrant train+validation (jamais oos/final). `end` = fin de validation."""
    if end is None:
        end = segments(n, protocol)["validation"][1]
    k = protocol["walk_forward_folds"]
    step = end // (k + 1)
    return [{"fold": f, "fit": (0, step * (f + 1)), "test": (step * (f + 1), step * (f + 2) if f < k - 1 else end)}
            for f in range(k)]


def cache_key(rev_hash: str, cache, costs: dict, risk, segment: str, window, protocol: dict) -> str:
    """Clé exacte : toute dépendance influençant le résultat y figure (AT-005)."""
    ctx = {tf: b.content_sha256 for tf, b in sorted(cache.context.items())}
    news = cache.news.sha() if getattr(cache, "news", None) is not None else None
    return sha256_json({"g": rev_hash, "d": cache.bars.content_sha256, "ctx": ctx, "seg": segment, "w": list(window),
                        "c": sha256_json(costs), "r": risk.limits_sha256, "p": protocol, "v": versions_snapshot(),
                        "n": news})


def compute_metrics(content: dict, cache, costs: dict, risk, window) -> tuple[dict, dict]:
    """Calcul pur (sans base) : utilisable dans un processus worker."""
    bars = cache.bars
    res = engine.run(content, cache, costs, risk, start=window[0], stop=window[1])
    m = compute(res, (int(bars.ts[window[0]]), int(bars.ts[window[1] - 1])))
    return m, res


def find(lab, key: str) -> dict | None:
    row = lab.con.execute("SELECT * FROM evaluations WHERE cache_key=?", (key,)).fetchone()
    return {**dict(row), "metrics": json.loads(row["metrics_json"]), "cached": True} if row else None


def store(lab, key: str, rev_id: str, cache, costs: dict, risk, segment: str, window, protocol: dict,
          metrics: dict, result: dict | None, campaign_id: str | None, store_trades: bool) -> dict:
    trades_sha = None
    if result is not None and (store_trades or segment == "final"):
        trades_sha = lab.store.put_json({"trades": result["trades"], "skipped": result["skipped"]}, kind="trades",
                                        meta={"revision": rev_id, "segment": segment})
    # INSERT OR IGNORE + clé unique : une reprise ne duplique jamais une évaluation (AT-004).
    lab.con.execute("INSERT OR IGNORE INTO evaluations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        new_id("eval"), key, rev_id, campaign_id, cache.bars.version_id,
        json.dumps({tf: b.version_id for tf, b in cache.context.items()}), segment, json.dumps(list(window)),
        sha256_json(costs), risk.limits_sha256, json.dumps(protocol), None, json.dumps(versions_snapshot()),
        json.dumps(metrics), trades_sha, utc_now_iso()))
    if segment == "final":
        audit(lab.con, "holdout.evaluated", rev_id, dataset=cache.bars.version_id, window=list(window))
    return find(lab, key) | {"cached": False}


def evaluate(lab, rev: dict, cache, costs: dict, risk, segment: str, protocol: dict = DEFAULT_PROTOCOL,
             campaign_id: str | None = None, window: tuple[int, int] | None = None, store_trades: bool = False,
             allow_final: bool = False) -> dict:
    """Évalue une révision sur un segment. Résultat réutilisé si toutes les dépendances sont identiques."""
    if segment == "final" and not allow_final:
        raise PermissionError("le segment final n'est accessible que par une évaluation finale explicite")
    if window is None:
        window = segments_for(lab, cache.bars, protocol)[segment]
    if window[1] - window[0] < 2:
        raise ValueError(f"segment {segment} vide ou trop court pour cette version du dataset {list(window)}")
    key = cache_key(rev["semantic_hash"], cache, costs, risk, segment, window, protocol)
    hit = find(lab, key)
    if hit and (hit["trades_artifact"] or not store_trades):
        return hit
    m, res = compute_metrics(rev["content"], cache, costs, risk, window)
    if hit:  # trades demandés mais non conservés lors du premier calcul : on les ajoute
        sha = lab.store.put_json({"trades": res["trades"], "skipped": res["skipped"]}, kind="trades",
                                 meta={"revision": rev["id"], "segment": segment})
        lab.con.execute("UPDATE evaluations SET trades_artifact=? WHERE cache_key=?", (sha, key))
        return find(lab, key) | {"result": res}
    return store(lab, key, rev["id"], cache, costs, risk, segment, window, protocol, m, res, campaign_id,
                 store_trades) | {"result": res}


def segment_usage(lab, dataset_version_id: str, segment: str) -> int:
    """Révisions distinctes déjà évaluées sur ce segment de la série, toutes versions du dataset confondues."""
    return lab.con.execute(
        "SELECT COUNT(DISTINCT e.revision_id) FROM evaluations e JOIN dataset_versions v ON v.id=e.dataset_version_id "
        "WHERE e.segment=? AND v.dataset_id=(SELECT dataset_id FROM dataset_versions WHERE id=?)",
        (segment, dataset_version_id)).fetchone()[0]


def holdout_usage(lab, dataset_version_id: str, window=None) -> dict:
    """Nombre de révisions distinctes déjà évaluées sur le holdout final de la série (toutes versions)."""
    n = segment_usage(lab, dataset_version_id, "final")
    return {"revisions_evaluated": n, "independent": n <= 1}
