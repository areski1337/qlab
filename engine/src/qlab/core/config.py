r"""Résolution des répertoires et configuration de l'application.

Le répertoire de données est choisi, par ordre de priorité :
1. variable d'environnement QLAB_DATA_DIR ;
2. %LOCALAPPDATA%\QLab sous Windows, ~/.qlab ailleurs.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hashing import sha256_json

DEFAULT_SETTINGS: dict[str, Any] = {
    "mt5": {
        "terminal_path": r"C:\Program Files\MetaTrader 5\terminal64.exe",
        "metaeditor_path": r"C:\Program Files\MetaTrader 5\MetaEditor64.exe",
        "data_path": None,  # détecté via terminal_info() si None
    },
    "workers": {"max_processes": max(1, (os.cpu_count() or 2) - 1)},
    "disk": {"min_free_mb": 2048},
    "api": {"host": "127.0.0.1"},  # jamais 0.0.0.0 par défaut
    "ui": {"language": "fr"},
}


@dataclass
class Paths:
    root: Path
    db: Path = field(init=False)
    artifacts: Path = field(init=False)
    datasets: Path = field(init=False)
    logs: Path = field(init=False)
    backups: Path = field(init=False)
    exports: Path = field(init=False)
    cache: Path = field(init=False)
    settings: Path = field(init=False)
    risk_limits: Path = field(init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.db = self.root / "qlab.sqlite"
        self.artifacts = self.root / "artifacts"
        self.datasets = self.root / "datasets"
        self.logs = self.root / "logs"
        self.backups = self.root / "backups"
        self.exports = self.root / "exports"
        self.cache = self.root / "cache"
        self.settings = self.root / "settings.json"
        self.risk_limits = self.root / "risk_limits.json"

    def ensure(self) -> "Paths":
        for p in (self.root, self.artifacts, self.datasets, self.logs, self.backups, self.exports, self.cache):
            p.mkdir(parents=True, exist_ok=True)
        return self


def default_data_dir() -> Path:
    env = os.environ.get("QLAB_DATA_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "QLab" if base else Path.home() / ".qlab"


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(paths: Paths) -> dict[str, Any]:
    if paths.settings.exists():
        user = json.loads(paths.settings.read_text(encoding="utf-8"))
        return _deep_merge(DEFAULT_SETTINGS, user)
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def save_settings(paths: Paths, settings: dict[str, Any]) -> str:
    if settings.get("api", {}).get("host") not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("l'API locale ne peut pas être exposée hors de la boucle locale")
    tmp = paths.settings.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, paths.settings)
    return sha256_json(settings)
