"""Journaux structurés JSON Lines, horodatés UTC, sans secrets."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from .timeutil import utc_now, utc_now_iso

_SECRET_KEY = re.compile(r"(pass(word)?|secret|token|api[_-]?key|credential)", re.I)
_lock = threading.Lock()


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***" if _SECRET_KEY.search(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class JsonLogger:
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _file(self) -> Path:
        return self.log_dir / f"qlab-{utc_now():%Y%m%d}.jsonl"

    def log(self, level: str, event: str, correlation_id: str | None = None, **fields: Any) -> dict:
        rec = {"ts": utc_now_iso(), "level": level, "event": event, "correlation_id": correlation_id, **redact(fields)}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with _lock, open(self._file(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return rec

    def info(self, event: str, **kw: Any) -> dict:
        return self.log("info", event, **kw)

    def warning(self, event: str, **kw: Any) -> dict:
        return self.log("warning", event, **kw)

    def error(self, event: str, **kw: Any) -> dict:
        return self.log("error", event, **kw)

    def tail(self, n: int = 200) -> list[dict]:
        files = sorted(self.log_dir.glob("qlab-*.jsonl"))
        out: list[dict] = []
        for f in reversed(files):
            lines = f.read_text(encoding="utf-8").splitlines()
            out = [json.loads(l) for l in lines[-(n - len(out)):]] + out
            if len(out) >= n:
                break
        return out[-n:]
