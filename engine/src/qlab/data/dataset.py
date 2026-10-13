"""Datasets versionnés : normalisation UTC, contrôle qualité, stockage Parquet.

Convention d'horodatage interne :
- `ts` = ouverture de la barre en secondes UTC ;
- une barre est *disponible* à `ts + tf_seconds` (sa clôture) ;
- les prix OHLC sont des prix Bid (convention MT5) ; `spread` est en points.

Les données brutes sont conservées telles quelles (artefact Parquet) ; la
version normalisée est un fichier distinct et chaque correction appliquée est
listée dans `corrections_json`. Rien n'est interpolé ni reconstitué.
"""
from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..core.hashing import sha256_bytes, sha256_json
from ..core.ids import new_id
from ..core.timeutil import tf_seconds, ts_to_iso, utc_now_iso
from ..storage.db import audit
from .tz import server_to_utc

COLUMNS = ["ts", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]


@dataclass
class Bars:
    """Série OHLC normalisée (UTC) prête pour les features et le backtest."""
    symbol: str
    timeframe: str
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    tick_volume: np.ndarray
    spread: np.ndarray
    real_volume: np.ndarray
    spec: dict = field(default_factory=dict)
    version_id: str | None = None
    content_sha256: str | None = None
    synthetic: bool = False

    def __len__(self) -> int:
        return len(self.ts)

    @property
    def tf_s(self) -> int:
        return tf_seconds(self.timeframe)

    @property
    def ts_close(self) -> np.ndarray:
        return self.ts + self.tf_s

    def slice(self, start: int, stop: int) -> "Bars":
        kw = {c: getattr(self, c)[start:stop] for c in COLUMNS}
        return Bars(self.symbol, self.timeframe, spec=self.spec, version_id=self.version_id,
                    content_sha256=self.content_sha256, synthetic=self.synthetic, **kw)

    @classmethod
    def from_frame(cls, df: pd.DataFrame, symbol: str, timeframe: str, **kw) -> "Bars":
        return cls(symbol, timeframe, **{c: df[c].to_numpy() for c in COLUMNS}, **kw)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({c: getattr(self, c) for c in COLUMNS})


def content_hash(df: pd.DataFrame) -> str:
    """Empreinte indépendante du format de fichier (octets canoniques des colonnes)."""
    parts = [np.ascontiguousarray(df[c].to_numpy().astype(t)).tobytes()
             for c, t in zip(COLUMNS, ["<i8", "<f8", "<f8", "<f8", "<f8", "<i8", "<i8", "<i8"])]
    return sha256_bytes(b"".join(parts))


def normalize(raw: pd.DataFrame, timeframe: str, tz_profile: str, import_time_utc: float | None = None
              ) -> tuple[pd.DataFrame, list[dict]]:
    """Heure serveur → UTC + corrections documentées. `raw` a les colonnes COLUMNS en heure serveur."""
    tf = tf_seconds(timeframe)
    import_time_utc = time.time() if import_time_utc is None else import_time_utc
    corrections: list[dict] = []
    df = raw[COLUMNS].copy()
    for c in ("tick_volume", "spread", "real_volume", "ts"):
        df[c] = df[c].astype(np.int64)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(np.float64)

    ts_utc, invalid = server_to_utc(df["ts"].to_numpy(), tz_profile)
    df["ts"] = ts_utc
    if invalid.any():
        corrections.append({"rule": "drop_ambiguous_local_time", "count": int(invalid.sum()),
                            "detail": "heure serveur ambiguë/inexistante lors d'un changement d'heure"})
        df = df[~invalid]

    df = df.sort_values("ts", kind="stable")
    dup = df["ts"].duplicated(keep="last").to_numpy()
    if dup.any():
        corrections.append({"rule": "drop_duplicate_ts_keep_last", "count": int(dup.sum())})
        df = df[~dup]

    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    bad = (h < np.maximum(o, c)) | (l > np.minimum(o, c)) | (l <= 0) | ~np.isfinite(o + h + l + c)
    if bad.any():
        corrections.append({"rule": "drop_incoherent_ohlc", "count": int(bad.sum()),
                            "first_ts": [ts_to_iso(t) for t in df["ts"].to_numpy()[bad][:5]]})
        df = df[~bad]

    if len(df) and df["ts"].iloc[-1] + tf > import_time_utc:
        corrections.append({"rule": "drop_incomplete_last_bar", "count": 1, "ts": ts_to_iso(df["ts"].iloc[-1])})
        df = df.iloc[:-1]
    return df.reset_index(drop=True), corrections


def quality_report(df: pd.DataFrame, timeframe: str, now_utc: float | None = None) -> dict:
    tf = tf_seconds(timeframe)
    now_utc = time.time() if now_utc is None else now_utc
    ts = df["ts"].to_numpy()
    rep: dict = {"n_bars": int(len(ts))}
    if len(ts) == 0:
        rep["empty"] = True
        return rep
    d = np.diff(ts)
    gap_idx = np.where(d > tf)[0]
    dow = pd.to_datetime(ts[gap_idx], unit="s").dayofweek.to_numpy() if len(gap_idx) else np.array([])
    # Gap de week-end : commence vendredi/samedi et dure moins de 3,5 jours.
    weekend = (np.isin(dow, [4, 5])) & (d[gap_idx] <= 84 * 3600) if len(gap_idx) else np.array([], bool)
    other = gap_idx[~weekend] if len(gap_idx) else gap_idx
    largest = other[np.argsort(d[other])[::-1][:10]] if len(other) else []
    buckets = {"<=1h": 0, "1h-6h": 0, "6h-24h": 0, ">24h": 0}
    for g in d[other]:
        k = "<=1h" if g <= 3600 else "1h-6h" if g <= 6 * 3600 else "6h-24h" if g <= 86400 else ">24h"
        buckets[k] += 1
    rep.update({
        "start_utc": ts_to_iso(ts[0]), "end_utc": ts_to_iso(ts[-1]),
        "missing_bar_gaps_total": int(len(gap_idx)), "weekend_gaps": int(weekend.sum()),
        "non_weekend_gaps_by_duration": buckets,
        "largest_non_weekend_gaps": [{"after": ts_to_iso(ts[i]), "hours": round(d[i] / 3600, 2)} for i in largest],
        "zero_spread_ratio": float((df["spread"].to_numpy() == 0).mean()),
        "zero_tick_volume_ratio": float((df["tick_volume"].to_numpy() == 0).mean()),
        "real_volume_available": bool((df["real_volume"].to_numpy() > 0).any()),
        "hours_since_last_bar": round((now_utc - ts[-1] - tf) / 3600, 2),
    })
    warnings = []
    if rep["zero_spread_ratio"] > 0.5:
        warnings.append("spread historique majoritairement nul : traité comme INCONNU (profil de coûts requis)")
    if not rep["real_volume_available"]:
        warnings.append("volume réel absent : seules les features tick-volume sont disponibles")
    if buckets[">24h"]:
        warnings.append(f"{buckets['>24h']} trou(s) > 24 h hors week-end")
    rep["warnings"] = warnings
    return rep


def import_bars(lab, *, source: str, broker: str | None, source_symbol: str, canonical_symbol: str,
                timeframe: str, raw: pd.DataFrame, spec: dict, tz_profile: str, provenance: dict,
                synthetic: bool = False, import_time_utc: float | None = None) -> dict:
    """Crée (ou réutilise si contenu identique) une version de dataset. Retourne la ligne de version."""
    con = lab.con
    norm, corrections = normalize(raw, timeframe, tz_profile, import_time_utc)
    qc = quality_report(norm, timeframe, import_time_utc)
    csha = content_hash(norm)
    spec_sha = sha256_json(spec)

    row = con.execute("SELECT id FROM datasets WHERE source=? AND broker IS ? AND source_symbol=? AND timeframe=?",
                      (source, broker, source_symbol, timeframe)).fetchone()
    if row:
        ds_id = row["id"]
    else:
        ds_id = new_id("ds")
        con.execute("INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?)", (ds_id, source, broker, source_symbol,
                    canonical_symbol, timeframe, int(synthetic), utc_now_iso()))

    prev = con.execute("SELECT * FROM dataset_versions WHERE dataset_id=? ORDER BY version DESC LIMIT 1",
                       (ds_id,)).fetchone()
    if prev and prev["content_sha256"] == csha and prev["spec_sha256"] == spec_sha:
        return dict(prev)
    if prev and prev["spec_sha256"] != spec_sha:
        old = json.loads(prev["symbol_spec_json"])
        qc["spec_changes"] = {k: [old.get(k), spec.get(k)] for k in set(old) | set(spec) if old.get(k) != spec.get(k)}

    buf = io.BytesIO()
    raw[COLUMNS].to_parquet(buf, compression="zstd", index=False)
    raw_sha = lab.store.put_bytes(buf.getvalue(), kind="raw_bars", media_type="application/vnd.apache.parquet",
                                  meta={"source": source, "symbol": source_symbol, "tf": timeframe, "tz": tz_profile})
    version = (prev["version"] + 1) if prev else 1
    rel = f"datasets/{ds_id}/v{version}.parquet"
    path = lab.paths.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    norm.to_parquet(path, compression="zstd", index=False)
    vid = new_id("dsv")
    con.execute("INSERT INTO dataset_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        vid, ds_id, version, prev["id"] if prev else None, rel, csha, raw_sha,
        qc.get("start_utc"), qc.get("end_utc"), len(norm), tz_profile, utc_now_iso(),
        json.dumps(spec, sort_keys=True), spec_sha, json.dumps(qc), json.dumps(corrections),
        json.dumps({**provenance, "synthetic": synthetic})))
    audit(con, "dataset.version_created", vid, dataset_id=ds_id, version=version, n_bars=len(norm),
          content_sha256=csha, corrections=corrections)
    return dict(con.execute("SELECT * FROM dataset_versions WHERE id=?", (vid,)).fetchone())


def load_bars(lab, version_id: str, verify: bool = True) -> Bars:
    row = lab.con.execute("SELECT v.*, d.canonical_symbol, d.timeframe, d.synthetic FROM dataset_versions v "
                          "JOIN datasets d ON d.id=v.dataset_id WHERE v.id=?", (version_id,)).fetchone()
    if row is None:
        raise KeyError(version_id)
    df = pd.read_parquet(lab.paths.root / row["file_relpath"])
    if verify and content_hash(df) != row["content_sha256"]:
        raise IOError(f"dataset {version_id} modifié sur disque (empreinte différente)")
    return Bars.from_frame(df, row["canonical_symbol"], row["timeframe"], spec=json.loads(row["symbol_spec_json"]),
                           version_id=version_id, content_sha256=row["content_sha256"], synthetic=bool(row["synthetic"]))


def list_versions(lab) -> list[dict]:
    rows = lab.con.execute("SELECT v.id, v.version, v.n_bars, v.start_utc, v.end_utc, v.content_sha256, v.qc_json, "
                           "v.corrections_json, v.source_timezone, v.imported_at, d.source, d.broker, "
                           "d.canonical_symbol, d.timeframe, d.synthetic FROM dataset_versions v "
                           "JOIN datasets d ON d.id=v.dataset_id ORDER BY v.imported_at DESC")
    out = []
    for r in rows:
        d = dict(r)
        d["qc"] = json.loads(d.pop("qc_json"))
        d["corrections"] = json.loads(d.pop("corrections_json"))
        out.append(d)
    return out
