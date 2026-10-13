"""Import d'historique depuis le terminal MetaTrader 5 (lecture seule).

Ce module n'envoie aucun ordre : il n'appelle que des fonctions de lecture du
paquet MetaTrader5 (initialize, account_info, symbol_info, copy_rates_*).
"""
from __future__ import annotations

import datetime as dt
import time
from contextlib import contextmanager

import pandas as pd

TF_MAP = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "M30": "TIMEFRAME_M30",
          "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}

SPEC_FIELDS = ["digits", "point", "trade_tick_size", "trade_tick_value", "trade_tick_value_profit",
               "trade_tick_value_loss", "trade_contract_size", "volume_min", "volume_step", "volume_max",
               "currency_base", "currency_profit", "currency_margin", "swap_mode", "swap_long", "swap_short",
               "swap_rollover3days", "spread_float", "trade_stops_level", "trade_freeze_level",
               "trade_calc_mode", "trade_exemode", "filling_mode", "path", "description"]


class MT5Unavailable(RuntimeError):
    pass


def _terminal_running() -> bool:
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/NH"], capture_output=True, text=True)
    return "terminal64.exe" in out.stdout


@contextmanager
def mt5_session(terminal_path: str | None = None, timeout_ms: int = 60000):
    """Session de lecture. Si le terminal n'était pas ouvert, il est refermé proprement (WM_CLOSE) à la fin :
    l'état de l'utilisateur est restauré et le Strategy Tester reste utilisable."""
    try:
        import MetaTrader5 as mt5
    except ImportError as e:
        raise MT5Unavailable("paquet MetaTrader5 non installé") from e
    was_running = _terminal_running()
    kw = {"timeout": timeout_ms}
    if terminal_path:
        kw["path"] = terminal_path
    if not mt5.initialize(**kw):
        raise MT5Unavailable(f"initialisation MT5 impossible : {mt5.last_error()}")
    try:
        yield mt5
    finally:
        mt5.shutdown()
        if not was_running:
            import subprocess
            subprocess.run(["taskkill", "/IM", "terminal64.exe"], capture_output=True)  # sans /F : fermeture propre
            for _ in range(60):  # attendre la sortie effective : sinon une session suivante le croirait « ouvert par l'utilisateur »
                if not _terminal_running():
                    break
                time.sleep(0.5)


def status(terminal_path: str | None = None) -> dict:
    """Diagnostic réel de la connexion (sans secret : pas de mot de passe, login masqué)."""
    try:
        with mt5_session(terminal_path) as mt5:
            ti, ai = mt5.terminal_info(), mt5.account_info()
            return {"available": True, "build": ti.build, "connected": ti.connected,
                    "algo_trading_enabled": ti.trade_allowed, "data_path": ti.data_path,
                    "server": ai.server if ai else None,
                    "account_mode": {0: "demo", 1: "contest", 2: "real"}.get(ai.trade_mode) if ai else None,
                    "margin_mode": {0: "netting", 1: "exchange", 2: "hedging"}.get(ai.margin_mode) if ai else None,
                    "currency": ai.currency if ai else None,
                    "login_masked": f"***{str(ai.login)[-3:]}" if ai else None}
    except MT5Unavailable as e:
        return {"available": False, "error": str(e)}


def fetch_rates(symbol: str, timeframe: str, start: dt.datetime, end: dt.datetime,
                terminal_path: str | None = None) -> tuple[pd.DataFrame, dict, dict]:
    """Retourne (barres en heure serveur, spécification symbole, contexte d'import)."""
    with mt5_session(terminal_path) as mt5:
        if not mt5.symbol_select(symbol, True):
            raise MT5Unavailable(f"symbole indisponible : {symbol}")
        info = mt5.symbol_info(symbol)
        acc = mt5.account_info()
        rates = mt5.copy_rates_range(symbol, getattr(mt5, TF_MAP[timeframe]), start, end)
        if rates is None:
            raise MT5Unavailable(f"copy_rates_range a échoué : {mt5.last_error()}")
        tick = mt5.symbol_info_tick(symbol)
        now = time.time()
        spec = {k: getattr(info, k) for k in SPEC_FIELDS}
        spec.update({"symbol": symbol, "account_currency": acc.currency if acc else None,
                     "account_margin_mode": acc.margin_mode if acc else None})
        ctx = {"server": acc.server if acc else None, "terminal_build": mt5.terminal_info().build,
               "last_tick_server_ts": int(tick.time) if tick else None, "observed_at_utc": now,
               "requested_range": [start.isoformat(), end.isoformat()]}
    df = pd.DataFrame(rates)
    df = df.rename(columns={"time": "ts"})[["ts", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]]
    return df, spec, ctx
