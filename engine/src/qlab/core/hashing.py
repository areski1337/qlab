"""Empreintes déterministes (SHA-256) d'objets JSON canoniques et de fichiers."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


def _normalize(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            # NaN/inf ne sont pas du JSON valide : on les encode explicitement.
            return {"__float__": repr(obj)}
        return obj
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if hasattr(obj, "item") and callable(obj.item):  # scalaires numpy
        return _normalize(obj.item())
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(_normalize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
