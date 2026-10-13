"""Concepts ICT/SMC avec définitions explicites et testables.

Pivots : un pivot haut en k exige high[k] > max(high[k-L..k-1]) et
high[k] >= max(high[k+1..k+R]). Il n'est CONNU qu'à la clôture de k+R
(confirmation) ; aucune sortie ne l'utilise avant.

Toutes les zones (FVG, Order Blocks) sont créées à la clôture de la barre qui
les définit et ne peuvent produire un événement qu'aux barres suivantes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .classic import atr_arr
from .registry import Param, feature
from .sessions import trading_day, trading_week

P = Param
SWING = {"left": P("int", 1, 20, 3), "right": P("int", 1, 20, 3)}


def pivots(b, left: int, right: int):
    """Retourne (last_high, last_low, conf_high, conf_low) indexés à la confirmation."""
    n = len(b)
    out = []
    for arr, sign in ((b.high, 1), (b.low, -1)):
        x = arr * sign
        lmax = pd.Series(x).rolling(left).max().shift(1).to_numpy()
        rmax = pd.Series(x).rolling(right).max().shift(-right).to_numpy()
        is_p = (x > lmax) & (x >= rmax)
        conf = np.zeros(n, bool)
        conf[right:] = is_p[:n - right]
        lvl = np.full(n, np.nan)
        lvl[right:] = np.where(is_p[:n - right], arr[:n - right], np.nan)
        out.append((pd.Series(lvl).ffill().to_numpy(), conf))
    (lh, ch), (ll, cl) = out
    return lh, ll, ch, cl


@feature("swings", "1.0", "ict", "Derniers swing high/low CONFIRMÉS (pivots L/R) et événements de confirmation.",
         SWING, {"last_high": "price", "last_low": "price", "new_high": "bool", "new_low": "bool"})
def f_swings(b, left, right):
    lh, ll, ch, cl = pivots(b, left, right)
    return {"last_high": lh, "last_low": ll, "new_high": ch.astype(float), "new_low": cl.astype(float)}


def structure_arrays(b, left, right, break_on, disp_atr):
    lh, ll, _, _ = pivots(b, left, right)
    up_x = b.close if break_on == "close" else b.high
    dn_x = b.close if break_on == "close" else b.low
    atr = atr_arr(b, 14)
    body = np.abs(b.close - b.open)
    n = len(b)
    bos_u, bos_d, ch_u, ch_d, ms_u, ms_d = (np.zeros(n) for _ in range(6))
    trend = np.zeros(n)
    t = 0
    used_h = used_l = np.nan  # chaque niveau de swing ne peut être cassé qu'une fois
    for i in range(1, n):
        h, l = lh[i - 1], ll[i - 1]
        if h == h and h != used_h and up_x[i] > h:
            used_h = h
            bos_u[i] = 1
            if t == -1:
                ch_u[i] = 1
                ms_u[i] = float(atr[i] == atr[i] and body[i] >= disp_atr * atr[i])
            t = 1
        elif l == l and l != used_l and dn_x[i] < l:
            used_l = l
            bos_d[i] = 1
            if t == 1:
                ch_d[i] = 1
                ms_d[i] = float(atr[i] == atr[i] and body[i] >= disp_atr * atr[i])
            t = -1
        trend[i] = t
    return {"bos_up": bos_u, "bos_down": bos_d, "choch_up": ch_u, "choch_down": ch_d,
            "mss_up": ms_u, "mss_down": ms_d, "trend": trend}


@feature("structure", "1.0", "ict",
         "BOS : cassure (clôture ou mèche) du dernier swing confirmé, une fois par niveau. "
         "CHOCH : BOS contraire à la tendance courante. MSS : CHOCH dont le corps >= disp_atr × ATR(14). "
         "trend : +1 après BOS haussier, -1 après BOS baissier.",
         {**SWING, "break_on": P("choice", choices=("close", "wick")), "disp_atr": P("float", 0.0, 3.0, 1.0)},
         {"bos_up": "bool", "bos_down": "bool", "choch_up": "bool", "choch_down": "bool",
          "mss_up": "bool", "mss_down": "bool", "trend": "signed"})
def f_structure(b, left, right, break_on, disp_atr):
    return structure_arrays(b, left, right, break_on, disp_atr)


def _zones(n, creations, b, expiry):
    """Moteur commun de zones. creations[i] = liste de (direction, bas, haut) créées à la clôture de i.

    Zone haussière : retest si low <= haut et close >= bas (première touche puis mitigée) ;
    invalidée si close < bas → devient zone inverse baissière (retest : high >= bas et close <= haut).
    Symétrique pour les zones baissières. Expiration après `expiry` barres.
    """
    ev = {k: np.zeros(n) for k in ("bull_retest", "bear_retest", "inv_bull_retest", "inv_bear_retest")}
    active: list[list] = []  # [dir(+1/-1), lo, hi, born, inverted]
    lo_, hi_, cl_ = b.low, b.high, b.close
    for i in range(n):
        keep = []
        for z in active:
            d, lo, hi, born, inv = z
            if i - born > expiry:
                continue
            eff = -d if inv else d  # direction effective de la zone
            if eff == 1:
                if cl_[i] < lo:
                    if inv:
                        continue  # zone inverse cassée : supprimée
                    z[4] = True
                    keep.append(z)
                    continue
                if lo_[i] <= hi and cl_[i] >= lo:
                    ev["inv_bull_retest" if inv else "bull_retest"][i] = 1
                    continue  # mitigée
            else:
                if cl_[i] > hi:
                    if inv:
                        continue
                    z[4] = True
                    keep.append(z)
                    continue
                if hi_[i] >= lo and cl_[i] <= hi:
                    ev["inv_bear_retest" if inv else "bear_retest"][i] = 1
                    continue
            keep.append(z)
        for d, lo, hi in creations.get(i, ()):
            keep.append([d, lo, hi, i, False])
        active = keep[-64:]  # borne mémoire : au plus 64 zones actives
    return ev


@feature("fvg", "1.0", "ict",
         "FVG sur 3 bougies A/B/C (C = barre courante). Haussier : Low(C) > High(A) ; baissier : High(C) < Low(A). "
         "Taille >= min_atr × ATR(14). Zone disponible à la clôture de C. IFVG = FVG invalidé par clôture "
         "au-delà, retesté dans l'autre sens.",
         {"min_atr": P("float", 0.0, 3.0, 0.2), "expiry": P("int", 5, 500, 100)},
         {"new_bull": "bool", "new_bear": "bool", "bull_retest": "bool", "bear_retest": "bool",
          "ifvg_bull_retest": "bool", "ifvg_bear_retest": "bool"})
def f_fvg(b, min_atr, expiry):
    n = len(b)
    atr = atr_arr(b, 14)
    ha, la = np.concatenate([[np.nan] * 2, b.high[:-2]]), np.concatenate([[np.nan] * 2, b.low[:-2]])
    with np.errstate(invalid="ignore"):
        # Sans seuil ATR, l'ATR (indisponible en début de série) n'est pas requis.
        bull = (b.low > ha) & (((b.low - ha) >= min_atr * atr) if min_atr > 0 else True)
        bear = (b.high < la) & (((la - b.high) >= min_atr * atr) if min_atr > 0 else True)
    cr: dict[int, list] = {}
    for i in np.flatnonzero(bull):
        cr.setdefault(int(i), []).append((1, ha[i], b.low[i]))
    for i in np.flatnonzero(bear):
        cr.setdefault(int(i), []).append((-1, b.high[i], la[i]))
    ev = _zones(n, cr, b, expiry)
    return {"new_bull": bull.astype(float), "new_bear": bear.astype(float), "bull_retest": ev["bull_retest"],
            "bear_retest": ev["bear_retest"], "ifvg_bull_retest": ev["inv_bull_retest"],
            "ifvg_bear_retest": ev["inv_bear_retest"]}


@feature("order_block", "1.0", "ict",
         "Order Block : à un BOS haussier (clôture), dernière bougie baissière des `lookback` barres précédentes ; "
         "zone [low, high]. Symétrique en baissier. Breaker = OB invalidé par clôture au-delà puis retesté.",
         {**SWING, "lookback": P("int", 2, 50, 10), "expiry": P("int", 5, 500, 150)},
         {"bull_retest": "bool", "bear_retest": "bool", "breaker_bull_retest": "bool", "breaker_bear_retest": "bool"})
def f_ob(b, left, right, lookback, expiry):
    st = structure_arrays(b, left, right, "close", 0.0)
    bear_c = b.close < b.open
    bull_c = b.close > b.open
    cr: dict[int, list] = {}
    for i in np.flatnonzero(st["bos_up"]):
        js = [j for j in range(i - 1, max(-1, i - 1 - lookback), -1) if bear_c[j]]
        if js:
            cr.setdefault(int(i), []).append((1, b.low[js[0]], b.high[js[0]]))
    for i in np.flatnonzero(st["bos_down"]):
        js = [j for j in range(i - 1, max(-1, i - 1 - lookback), -1) if bull_c[j]]
        if js:
            cr.setdefault(int(i), []).append((-1, b.low[js[0]], b.high[js[0]]))
    ev = _zones(len(b), cr, b, expiry)
    # Un OB haussier invalidé devient un breaker baissier (et inversement).
    return {"bull_retest": ev["bull_retest"], "bear_retest": ev["bear_retest"],
            "breaker_bull_retest": ev["inv_bull_retest"], "breaker_bear_retest": ev["inv_bear_retest"]}


@feature("liquidity", "1.0", "ict",
         "Sweep : mèche au-delà du dernier swing confirmé et clôture de retour en deçà. "
         "Equal highs/lows : deux derniers swings confirmés à moins de tol_atr × ATR(14).",
         {**SWING, "tol_atr": P("float", 0.01, 1.0, 0.1)},
         {"sweep_high": "bool", "sweep_low": "bool", "equal_highs": "bool", "equal_lows": "bool"})
def f_liquidity(b, left, right, tol_atr):
    lh, ll, ch, cl = pivots(b, left, right)
    plh, pll = np.concatenate([[np.nan], lh[:-1]]), np.concatenate([[np.nan], ll[:-1]])
    atr = atr_arr(b, 14)
    with np.errstate(invalid="ignore"):
        sh = (b.high > plh) & (b.close < plh)
        sl = (b.low < pll) & (b.close > pll)

    def equal(levels, conf):
        idx = np.flatnonzero(conf)
        out = np.zeros(len(b))
        prev = np.nan
        for k, i in enumerate(idx):
            cur = levels[i]
            if prev == prev and abs(cur - prev) <= tol_atr * atr[i]:
                end = idx[k + 1] if k + 1 < len(idx) else len(b)
                out[i:end] = 1
            prev = cur
        return out
    return {"sweep_high": sh.astype(float), "sweep_low": sl.astype(float),
            "equal_highs": equal(lh, ch), "equal_lows": equal(ll, cl)}


def _prev_period_extremes(b, grp):
    df = pd.DataFrame({"g": grp, "h": b.high, "l": b.low})
    agg = df.groupby("g").agg(h=("h", "max"), l=("l", "min"))
    prev = agg.shift(1)
    return prev["h"].reindex(grp).to_numpy(), prev["l"].reindex(grp).to_numpy()


@feature("prev_extremes", "1.0", "ict",
         "PDH/PDL et PWH/PWL : extrêmes de la journée/semaine de trading PRÉCÉDENTE (bascule 17:00 NY). "
         "Disponibles dès la première barre de la nouvelle période. Une période absente des données "
         "(jour férié) n'est pas comblée : on prend la dernière période observée.",
         {}, {"pdh": "price", "pdl": "price", "pwh": "price", "pwl": "price"})
def f_prev(b):
    pdh, pdl = _prev_period_extremes(b, trading_day(b.ts))
    pwh, pwl = _prev_period_extremes(b, trading_week(b.ts))
    return {"pdh": pdh, "pdl": pdl, "pwh": pwh, "pwl": pwl}


@feature("range_position", "1.0", "ict",
         "Position de la clôture dans le range des n dernières barres (0 = bas, 100 = haut). "
         "< 50 discount, > 50 premium, 50 equilibrium ; OTE ≈ 21..38 (achat) / 62..79 (vente).",
         {"lookback": P("int", 5, 1000, 100)}, {"value": "osc100"})
def f_range_pos(b, lookback):
    hh = pd.Series(b.high).rolling(lookback).max().to_numpy()
    ll = pd.Series(b.low).rolling(lookback).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        v = np.where(hh > ll, (b.close - ll) / (hh - ll) * 100, 50.0)
    v[np.isnan(hh)] = np.nan
    return {"value": v}


# ------------------------------------------------------------------ itération 2 : Judas, PO3, SMT, Mitigation
from .sessions import in_session  # noqa: E402


def _ny_minutes(ts):
    loc = pd.to_datetime(ts, unit="s", utc=True).tz_convert("America/New_York")
    return (loc.hour * 60 + loc.minute).to_numpy()


@feature("judas", "1.0", "ict",
         "Judas Swing : range asiatique (bars dont la clôture est dans asia_kz, 20:00-00:00 NY) de la journée de "
         "trading ; complet à la fin de la session (sorties NaN avant). Pendant london_kz (02:00-05:00 NY) : "
         "judas_bull si low < bas asiatique - sweep_atr × ATR(14) et clôture > bas asiatique (faux départ "
         "baissier) ; judas_bear symétrique. Un seul événement par journée.",
         {"sweep_atr": P("float", 0.0, 2.0, 0.0)},
         {"asian_high": "price", "asian_low": "price", "judas_bull": "bool", "judas_bear": "bool"})
def f_judas(b, sweep_atr):
    n = len(b)
    day = trading_day(b.ts)
    asia = in_session(b.ts_close, "asia_kz")
    ldn = in_session(b.ts_close, "london_kz")
    atr = atr_arr(b, 14)
    ah, al = np.full(n, np.nan), np.full(n, np.nan)
    jb, js = np.zeros(n), np.zeros(n)
    cur, hi, lo, seen, done, fired = None, -np.inf, np.inf, False, False, False
    for i in range(n):
        if day[i] != cur:
            cur, hi, lo, seen, done, fired = day[i], -np.inf, np.inf, False, False, False
        if asia[i]:
            if done:  # une seconde fenêtre asiatique dans la même journée n'existe pas : ignorée
                pass
            else:
                hi, lo, seen = max(hi, b.high[i]), min(lo, b.low[i]), True
        elif seen:
            done = True
        if done:
            ah[i], al[i] = hi, lo
            if ldn[i] and not fired and atr[i] == atr[i]:
                if b.low[i] < lo - sweep_atr * atr[i] and b.close[i] > lo:
                    jb[i], fired = 1, True
                elif b.high[i] > hi + sweep_atr * atr[i] and b.close[i] < hi:
                    js[i], fired = 1, True
    return {"asian_high": ah, "asian_low": al, "judas_bull": jb, "judas_bear": js}


@feature("po3", "1.0", "ict",
         "Power of Three : ouverture de minuit New York (première barre de la journée de trading ouverte à "
         "00:00 NY ou après). Manipulation baissière : low <= ouverture - manip_atr × ATR(14) ; puis distribution "
         "haussière confirmée par une clôture > ouverture → po3_bull vrai jusqu'à la fin de la journée. Symétrique "
         "pour po3_bear. La première confirmation de la journée l'emporte.",
         {"manip_atr": P("float", 0.1, 3.0, 0.5)},
         {"midnight_open": "price", "po3_bull": "bool", "po3_bear": "bool"})
def f_po3(b, manip_atr):
    n = len(b)
    day = trading_day(b.ts)
    nym = _ny_minutes(b.ts)
    atr = atr_arr(b, 14)
    mo = np.full(n, np.nan)
    pb, ps = np.zeros(n), np.zeros(n)
    cur, op, down, up, state = None, np.nan, False, False, 0
    for i in range(n):
        if day[i] != cur:
            cur, op, down, up, state = day[i], np.nan, False, False, 0
        if op != op and nym[i] < 17 * 60:  # après minuit NY (heures 00:00-16:59 de la journée de trading)
            op = b.open[i]
        if op == op:
            mo[i] = op
            if state == 0 and atr[i] == atr[i]:
                if b.low[i] <= op - manip_atr * atr[i]:
                    down = True
                if b.high[i] >= op + manip_atr * atr[i]:
                    up = True
                if down and b.close[i] > op:
                    state = 1
                elif up and b.close[i] < op:
                    state = -1
            pb[i], ps[i] = float(state == 1), float(state == -1)
    return {"midnight_open": mo, "po3_bull": pb, "po3_bear": ps}


@feature("smt", "1.0", "ict",
         "SMT divergence avec un instrument de référence corrélé (même timeframe, barres appariées par horodatage) : "
         "smt_bull si le marché fait un plus bas sur `lookback` barres (low < min des lookback précédents) alors "
         "que la référence n'en fait pas ; smt_bear symétrique sur les hauts. Référence absente : sorties fausses "
         "(indisponible, jamais supposée).",
         {"ref": Param("symbol", default="XAGUSD"), "lookback": P("int", 5, 200, 20)},
         {"bull": "bool", "bear": "bool"}, needs_context=True)
def f_smt(b, ref, lookback, _ctx=None):
    n = len(b)
    r = (_ctx or {}).get(f"SYM:{ref}")
    z = np.zeros(n)
    if r is None or r.timeframe != b.timeframe:
        return {"bull": z, "bear": z.copy()}
    k = np.searchsorted(r.ts, b.ts)
    k = np.clip(k, 0, len(r) - 1)
    ok = r.ts[k] == b.ts
    rl, rh = np.where(ok, r.low[k], np.nan), np.where(ok, r.high[k], np.nan)
    pl = pd.Series(b.low).rolling(lookback).min().shift(1).to_numpy()
    ph = pd.Series(b.high).rolling(lookback).max().shift(1).to_numpy()
    rpl = pd.Series(rl).rolling(lookback).min().shift(1).to_numpy()  # NaN si une barre de référence manque
    rph = pd.Series(rh).rolling(lookback).max().shift(1).to_numpy()
    with np.errstate(invalid="ignore"):
        bull = (b.low < pl) & (rl >= rpl)
        bear = (b.high > ph) & (rh <= rph)
    return {"bull": bull.astype(float), "bear": bear.astype(float)}


@feature("mitigation", "1.0", "ict",
         "Mitigation Block : à un BOS baissier (clôture) précédé d'un ÉCHEC de swing (dernier swing high confirmé "
         "< swing high confirmé précédent), la dernière bougie haussière des `lookback` barres forme une zone "
         "[low, high] ; retest par le bas (high >= bas et clôture <= haut) → bear_retest. Symétrique (higher low, "
         "BOS haussier, dernière bougie baissière) → bull_retest. Moteur de zones commun (première touche, expiration).",
         {**SWING, "lookback": P("int", 2, 50, 10), "expiry": P("int", 5, 500, 150)},
         {"bull_retest": "bool", "bear_retest": "bool"})
def f_mitigation(b, left, right, lookback, expiry):
    n = len(b)
    lh, ll, ch, cl = pivots(b, left, right)
    st = structure_arrays(b, left, right, "close", 0.0)
    # niveau du swing confirmé précédent (avant la dernière confirmation), à chaque barre
    prev_h, prev_l = np.full(n, np.nan), np.full(n, np.nan)
    ph = pl = np.nan
    last_h = last_l = np.nan
    for i in range(n):
        if ch[i]:
            ph, last_h = last_h, lh[i]
        if cl[i]:
            pl, last_l = last_l, ll[i]
        prev_h[i], prev_l[i] = ph, pl
    bear_c, bull_c = b.close < b.open, b.close > b.open
    cr: dict[int, list] = {}
    for i in np.flatnonzero(st["bos_up"]):
        if i > 0 and ll[i - 1] == ll[i - 1] and prev_l[i - 1] == prev_l[i - 1] and ll[i - 1] > prev_l[i - 1]:
            js = [j for j in range(i - 1, max(-1, i - 1 - lookback), -1) if bear_c[j]]
            if js:
                cr.setdefault(int(i), []).append((1, b.low[js[0]], b.high[js[0]]))
    for i in np.flatnonzero(st["bos_down"]):
        if i > 0 and lh[i - 1] == lh[i - 1] and prev_h[i - 1] == prev_h[i - 1] and lh[i - 1] < prev_h[i - 1]:
            js = [j for j in range(i - 1, max(-1, i - 1 - lookback), -1) if bull_c[j]]
            if js:
                cr.setdefault(int(i), []).append((-1, b.low[js[0]], b.high[js[0]]))
    ev = _zones(n, cr, b, expiry)
    return {"bull_retest": ev["bull_retest"], "bear_retest": ev["bear_retest"]}
