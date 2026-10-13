"""Stockage d'artefacts adressé par contenu (SHA-256)."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from ..core.hashing import sha256_bytes, sha256_file
from ..core.timeutil import utc_now_iso


class ArtifactStore:
    def __init__(self, root: Path, con: sqlite3.Connection):
        self.root = Path(root)
        self.con = con

    def path(self, sha: str) -> Path:
        return self.root / sha[:2] / sha

    def put_bytes(self, data: bytes, kind: str, media_type: str = "application/octet-stream", meta: dict | None = None) -> str:
        sha = sha256_bytes(data)
        p = self.path(sha)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)  # écriture atomique
        self.con.execute("INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?,?)",
                         (sha, kind, media_type, len(data), utc_now_iso(), json.dumps(meta or {})))
        return sha

    def put_json(self, obj, kind: str, meta: dict | None = None) -> str:
        data = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
        return self.put_bytes(data, kind, "application/json", meta)

    def get_bytes(self, sha: str, verify: bool = True) -> bytes:
        data = self.path(sha).read_bytes()
        if verify and sha256_bytes(data) != sha:
            raise IOError(f"artefact corrompu : {sha}")
        return data

    def get_json(self, sha: str):
        return json.loads(self.get_bytes(sha))

    def verify_all(self) -> list[str]:
        """Liste des artefacts référencés mais manquants ou corrompus."""
        bad = []
        for (sha,) in self.con.execute("SELECT sha256 FROM artifacts"):
            p = self.path(sha)
            if not p.exists() or sha256_file(p) != sha:
                bad.append(sha)
        return bad
