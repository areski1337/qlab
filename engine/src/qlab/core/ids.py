"""Identifiants uniques triables dans le temps."""
from __future__ import annotations

import secrets
import time


def new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000):013x}{secrets.token_hex(5)}"
