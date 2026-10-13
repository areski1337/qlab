"""Opérateurs génétiques typés (version : COMPONENT_VERSIONS['evolution_operators']).

Chaque opérateur part d'un génome valide et produit un génome candidat ; un
candidat invalide est rejeté et l'opérateur réessaie (le taux d'échec est
mesuré). L'espace de recherche ne contient JAMAIS les limites de risque
absolues : seul `sizing.risk_pct` (une demande) est mutable, et il est
plafonné par le contrôleur de risque.
"""
from __future__ import annotations

import copy
import random

from ..features import REGISTRY
from ..genome import model

# Comparaisons « prix contre prix » pertinentes : (feature, sortie) de niveaux de prix.
PRICE_LEVELS = [("ema", "value"), ("sma", "value"), ("bollinger", "upper"), ("bollinger", "lower"),
                ("bollinger", "mid"), ("keltner", "upper"), ("keltner", "lower"), ("donchian", "upper"),
                ("donchian", "lower"), ("vwap", "vwap"), ("vwap", "upper"), ("vwap", "lower"),
                ("prev_extremes", "pdh"), ("prev_extremes", "pdl"), ("swings", "last_high"), ("swings", "last_low")]
# Ratios/oscillateurs comparables à une constante indépendante de l'instrument (l'ATR brut est exclu).
CONST_COMPARABLE = {("rsi", "value"): (10, 90), ("stoch", "k"): (5, 95), ("stoch", "d"): (5, 95),
                    ("adx", "adx"): (10, 50), ("range_position", "value"): (5, 95),
                    ("compression", "value"): (0.4, 2.0), ("rel_volume", "value"): (0.3, 3.0),
                    ("momentum", "roc"): (-1.0, 1.0), ("macd", "hist"): (0.0, 0.0),
                    ("structure", "trend"): (0.0, 0.0)}
SESSION_NAMES = REGISTRY["session"].params["name"].choices
HTF = {"M1": ["M15", "H1"], "M5": ["H1", "H4"], "M15": ["H1", "H4"], "M30": ["H4"], "H1": ["H4"], "H4": []}


def rand_params(rng: random.Random, name: str, refs=()) -> dict:
    out = {}
    for k, p in REGISTRY[name].params.items():
        if p.kind == "symbol":
            out[k] = rng.choice(list(refs))
        elif p.kind == "choice":
            out[k] = rng.choice(p.choices)
        elif p.kind == "int":
            # tirage log-uniforme autour des valeurs usuelles
            lo, hi = int(p.lo), int(min(p.hi, max(p.default * 5, p.lo + 2)))
            out[k] = rng.randint(lo, hi)
        else:
            out[k] = round(rng.uniform(p.lo, min(p.hi, max(p.default * 3, p.lo + 0.5))), 2)
    if name == "macd" and out["fast"] >= out["slow"]:
        out["fast"], out["slow"] = min(out["fast"], out["slow"] - 1) or 2, max(out["slow"], out["fast"] + 1)
    if name == "compression" and out["fast"] >= out["slow"]:
        out["slow"] = out["fast"] + 10
    if name == "vwap":
        out["volume"] = "tick"  # le volume réel est rarement disponible (FX/CFD)
    return out


def ref(rng, name, output, tf_choices=()) -> dict:
    r = {"feature": name, "params": rand_params(rng, name), "output": output}
    if tf_choices and rng.random() < 0.25:
        r["tf"] = rng.choice(tf_choices)
    return r


def random_leaf(rng: random.Random, base_tf: str, side: int, htfs=()) -> dict:
    htf = [t for t in HTF.get(base_tf, []) if t in htfs]
    kind = rng.random()
    if kind < 0.35:  # événement booléen
        refs = [x[4:] for x in htfs if x.startswith("SYM:")]
        # features à instrument de référence (SMT) : seulement si une référence est chargée dans le contexte
        bools = [(n, o) for n, s in REGISTRY.items() for o, k in s.outputs.items()
                 if k == "bool" and (refs or not s.needs_context)]
        n, o = rng.choice(bools)
        if n == "session":
            return {"id": "n0", "op": "event", "ref": {"feature": "session", "params": {"name": rng.choice(SESSION_NAMES)},
                                                         "output": "active"}}
        if REGISTRY[n].needs_context:
            return {"id": "n0", "op": "event", "ref": {"feature": n, "params": rand_params(rng, n, refs), "output": o}}
        return {"id": "n0", "op": "event", "ref": ref(rng, n, o, htf if n != "session" else ())}
    if kind < 0.7:  # oscillateur/ratio contre constante
        (n, o), (lo, hi) = rng.choice(list(CONST_COMPARABLE.items()))
        c = round(rng.uniform(lo, hi), 2)
        cmp = rng.choice(["gt", "lt", "cross_above", "cross_below"])
        return {"id": "n0", "op": "compare", "left": ref(rng, n, o, htf), "cmp": cmp, "right": {"const": c}}
    # prix contre niveau de prix
    n, o = rng.choice(PRICE_LEVELS)
    cmp = rng.choice(["gt", "lt", "cross_above", "cross_below"])
    left = {"feature": "price", "params": {}, "output": "close"}
    return {"id": "n0", "op": "compare", "left": left, "cmp": cmp, "right": ref(rng, n, o, htf)}


def random_tree(rng: random.Random, base_tf: str, side: int, htfs=(), max_leaves: int = 4) -> dict:
    k = rng.randint(1, max_leaves)
    leaves = [random_leaf(rng, base_tf, side, htfs) for _ in range(k)]
    if k == 1:
        return leaves[0]
    return {"id": "n0", "op": "and" if rng.random() < 0.8 else "or", "children": leaves}


def random_exit(rng: random.Random) -> dict:
    st = rng.random()
    stop = ({"type": "atr", "period": 14, "mult": round(rng.uniform(0.8, 4.0), 2)} if st < 0.6 else
            {"type": "swing", "left": rng.randint(2, 6), "right": rng.randint(2, 6),
             "buffer_atr": round(rng.uniform(0.0, 0.5), 2)})
    target = None if rng.random() < 0.15 else {"type": "rr", "rr": round(rng.uniform(0.8, 4.0), 2)}
    return {"stop": stop, "target": target,
            "break_even": {"at_r": round(rng.uniform(0.5, 2.0), 2)} if rng.random() < 0.3 else None,
            "trailing": ({"period": 14, "mult": round(rng.uniform(1.0, 4.0), 2),
                          "activate_r": round(rng.uniform(0.5, 2.0), 2)} if rng.random() < 0.25 else None),
            "time_stop_bars": rng.choice([None, 12, 24, 48, 96, 192]),
            "exit_on_opposite": rng.random() < 0.3}


def random_genome(rng: random.Random, symbol: str, tf: str, sides: str = "both", htfs=()) -> dict:
    """`htfs` : timeframes supérieurs dont les données sont disponibles (aucun autre n'est référencé)."""
    lg = random_tree(rng, tf, 1, htfs) if sides in ("both", "long") else None
    sh = random_tree(rng, tf, -1, htfs) if sides in ("both", "short") else None
    g = {"schema": model.SCHEMA_ID, "market": {"symbol": symbol, "timeframe": tf}, "entry": {"long": lg, "short": sh},
         "exit": random_exit(rng), "sizing": {"risk_pct": 0.5},
         "management": {"max_trades_per_day": rng.randint(1, 6), "cooldown_bars": rng.choice([0, 1, 3, 6, 12])}}
    return model.renumber(g)


# ---------- bases de stratégie (points de départ structurés, paramètres tirés au hasard) ----------

def _r(feature, output, tf=None, **params):
    r = {"feature": feature, "params": params, "output": output}
    if tf:
        r["tf"] = tf
    return r


def _cmp(left, cmp, right):
    return {"id": "n0", "op": "compare", "left": left, "cmp": cmp, "right": right}


def _ev(ref_):
    return {"id": "n0", "op": "event", "ref": ref_}


_CLOSE = {"feature": "price", "params": {}, "output": "close"}


def _base_trend(rng, side, htf):
    up = side == 1
    kids = [_cmp(_CLOSE, "cross_above" if up else "cross_below", _r("ema", "value", period=rng.randint(15, 60))),
            _cmp(_r("adx", "adx", period=14), "gt", {"const": round(rng.uniform(18, 30), 1)})]
    if htf:
        kids.append(_cmp(_CLOSE, "gt" if up else "lt", _r("ema", "value", htf, period=rng.randint(20, 100))))
    return kids


def _base_reversion(rng, side, htf):
    up = side == 1
    lvl = round(rng.uniform(22, 35), 1)
    return [_cmp(_r("rsi", "value", period=rng.randint(5, 21)), "lt" if up else "gt", {"const": lvl if up else 100 - lvl}),
            _cmp(_CLOSE, "lt" if up else "gt", _r("bollinger", "lower" if up else "upper",
                                                  period=rng.randint(15, 40), dev=round(rng.uniform(1.6, 2.6), 2)))]


def _base_breakout(rng, side, htf):
    up = side == 1
    return [_cmp(_CLOSE, "cross_above" if up else "cross_below", _r("donchian", "upper" if up else "lower",
                                                                    period=rng.randint(20, 60))),
            _cmp(_r("compression", "value", fast=5, slow=rng.randint(40, 80)), "lt", {"const": round(rng.uniform(0.6, 1.0), 2)})]


def _base_session(rng, side, htf):
    up = side == 1
    return [_ev(_r("session", "active", name=rng.choice(["london", "new_york", "ldn_ny_overlap"]))),
            _cmp(_CLOSE, "cross_above" if up else "cross_below", _r("prev_extremes", "pdh" if up else "pdl"))]


def _base_ict(rng, side, htf):
    up = side == 1
    setup = rng.choice([("fvg", "bull_retest", "bear_retest"), ("order_block", "bull_retest", "bear_retest"),
                        ("liquidity", "sweep_low", "sweep_high"), ("judas", "judas_bull", "judas_bear")])
    kids = [_ev(_r("session", "active", name=rng.choice(["london_kz", "asia_kz", "new_york"]))),
            _ev({"feature": setup[0], "params": rand_params(rng, setup[0]), "output": setup[1] if up else setup[2]})]
    if htf:
        kids.append(_cmp(_r("structure", "trend", htf, left=3, right=3, break_on="close", disp_atr=1.0),
                         "gt" if up else "lt", {"const": 0.0}))
    return kids


def _base_pullback(rng, side, htf):
    up = side == 1
    lvl = round(rng.uniform(35, 45), 1)
    return [_cmp(_CLOSE, "gt" if up else "lt", _r("ema", "value", htf, period=rng.randint(100, 200))),
            _cmp(_r("rsi", "value", period=14), "cross_above" if up else "cross_below", {"const": lvl if up else 100 - lvl})]


BASES = {
    "trend": ("Suivi de tendance", "croisement de moyenne mobile confirmé par l'ADX (+ filtre de tendance supérieure)", _base_trend),
    "reversion": ("Retour à la moyenne", "RSI en excès et prix hors de la bande de Bollinger", _base_reversion),
    "breakout": ("Cassure de range", "cassure de Donchian après compression de la volatilité", _base_breakout),
    "session": ("Cassure de session", "session active et cassure du plus haut/bas de la veille", _base_session),
    "ict": ("ICT / Smart Money", "kill zone + retest FVG/order block, chasse de liquidité ou Judas (+ structure supérieure)", _base_ict),
    "pullback": ("Repli dans la tendance", "prix du bon côté d'une moyenne longue et RSI qui repart", _base_pullback),
}


def base_genome(rng: random.Random, base: str, symbol: str, tf: str, sides: str = "both", htfs=()) -> dict:
    """Génome construit sur une base ; sorties et gestion tirées comme pour un génome aléatoire."""
    htf = next((t for t in HTF.get(tf, []) if t in htfs), None)
    build = BASES[base][2]
    tree = lambda s: {"id": "n0", "op": "and", "children": build(rng, s, htf)}
    g = random_genome(rng, symbol, tf, sides, htfs)
    g["entry"] = {"long": tree(1) if sides in ("both", "long") else None,
                  "short": tree(-1) if sides in ("both", "short") else None}
    return model.renumber(g)


# ---------- mutations ----------

def _entry_nodes(g):
    return [(s, n) for s in ("long", "short") for n in model.iter_nodes(g["entry"][s])]


def _leaves(g):
    return [(s, n) for s, n in _entry_nodes(g) if n["op"] in ("compare", "event")]


def _refs_in(n):
    if n["op"] == "compare":
        return [n["left"]] + ([n["right"]] if "feature" in n["right"] else [])
    return [n["ref"]] if n["op"] == "event" else []


def m_param(rng, g, htfs=()):
    refs = [r for _, n in _leaves(g) for r in _refs_in(n) if REGISTRY[r["feature"]].params]
    if not refs:
        return None
    r = rng.choice(refs)
    keys = [k for k, p in REGISTRY[r["feature"]].params.items() if p.kind != "symbol"]
    if not keys:
        return None
    k = rng.choice(keys)
    p = REGISTRY[r["feature"]].params[k]
    if p.kind == "choice":
        r["params"][k] = rng.choice(p.choices)
    elif p.kind == "int":
        r["params"][k] = max(int(p.lo), min(int(p.hi), r["params"][k] + rng.choice([-3, -2, -1, 1, 2, 3])))
    else:
        r["params"][k] = round(max(p.lo, min(p.hi, r["params"][k] * rng.uniform(0.7, 1.3))), 3)
    return {"ref": r["feature"], "param": k}


def m_const(rng, g, htfs=()):
    cs = [n for _, n in _leaves(g) if n["op"] == "compare" and "const" in n["right"]]
    if not cs:
        return None
    n = rng.choice(cs)
    lo, hi = CONST_COMPARABLE.get((n["left"]["feature"], n["left"]["output"]), (0, 100))
    span = (hi - lo) or 1.0
    n["right"]["const"] = round(min(hi, max(lo, n["right"]["const"] + rng.gauss(0, span * 0.1))), 3)
    return {"node": n["id"]}


def m_cmp(rng, g, htfs=()):
    cs = [n for _, n in _leaves(g) if n["op"] == "compare"]
    if not cs:
        return None
    n = rng.choice(cs)
    n["cmp"] = rng.choice([c for c in ("gt", "lt", "cross_above", "cross_below") if c != n["cmp"]])
    return {"node": n["id"]}


def _replace(g, target, new):
    for s in ("long", "short"):
        if g["entry"][s] is target:
            g["entry"][s] = new
            return
        for n in model.iter_nodes(g["entry"][s]):
            ch = n.get("children", [])
            for i, c in enumerate(ch):
                if c is target:
                    ch[i] = new
                    return


def m_replace_leaf(rng, g, htfs=()):
    ls = _leaves(g)
    if not ls:
        return None
    s, n = rng.choice(ls)
    _replace(g, n, random_leaf(rng, g["market"]["timeframe"], 1 if s == "long" else -1, htfs))
    return {"side": s}


def m_add_leaf(rng, g, htfs=()):
    sides = [s for s in ("long", "short") if g["entry"][s] is not None]
    s = rng.choice(sides)
    root = g["entry"][s]
    leaf = random_leaf(rng, g["market"]["timeframe"], 1 if s == "long" else -1, htfs)
    if root["op"] in ("and", "or"):
        root["children"].append(leaf)
    else:
        g["entry"][s] = {"id": "n0", "op": "and", "children": [root, leaf]}
    return {"side": s}


def m_remove_leaf(rng, g, htfs=()):
    groups = [n for _, n in _entry_nodes(g) if n["op"] in ("and", "or") and len(n["children"]) >= 2]
    if not groups:
        return None
    n = rng.choice(groups)
    n["children"].pop(rng.randrange(len(n["children"])))
    if len(n["children"]) == 1:
        _replace(g, n, n["children"][0])
    return {}


def m_logic(rng, g, htfs=()):
    ns = [n for _, n in _entry_nodes(g) if n["op"] in ("and", "or")]
    if ns and rng.random() < 0.6:
        n = rng.choice(ns)
        n["op"] = "or" if n["op"] == "and" else "and"
        return {"swap": n["id"]}
    ls = _leaves(g)
    if not ls:
        return None
    _, n = rng.choice(ls)
    _replace(g, n, {"id": "n0", "op": "not", "children": [n]})
    return {"not": True}


def m_exit(rng, g, htfs=()):
    ex = g["exit"]
    what = rng.choice(["stop", "target", "be", "trail", "time", "opp"])
    if what == "stop":
        st = ex["stop"]
        if st["type"] == "atr":
            st["mult"] = round(min(20, max(0.2, st["mult"] * rng.uniform(0.75, 1.3))), 2)
        elif st["type"] == "swing":
            st["buffer_atr"] = round(min(5, max(0.0, st["buffer_atr"] + rng.uniform(-0.15, 0.15))), 2)
        else:
            st["points"] = max(1, int(st["points"] * rng.uniform(0.75, 1.3)))
    elif what == "target":
        ex["target"] = (None if ex["target"] and rng.random() < 0.15 else
                        {"type": "rr", "rr": round(min(20, max(0.2, (ex["target"] or {"rr": 2})
                                                                .get("rr", 2) * rng.uniform(0.7, 1.4))), 2)})
    elif what == "be":
        ex["break_even"] = None if ex["break_even"] else {"at_r": round(rng.uniform(0.5, 2.0), 2)}
    elif what == "trail":
        ex["trailing"] = None if ex["trailing"] else {"period": 14, "mult": round(rng.uniform(1, 4), 2),
                                                     "activate_r": round(rng.uniform(0.5, 2), 2)}
    elif what == "time":
        ex["time_stop_bars"] = rng.choice([None, 12, 24, 48, 96, 192, 384])
    else:
        ex["exit_on_opposite"] = not ex["exit_on_opposite"]
    return {"exit": what}


def m_management(rng, g, htfs=()):
    mg = g["management"]
    if rng.random() < 0.5:
        mg["max_trades_per_day"] = max(1, min(20, mg["max_trades_per_day"] + rng.choice([-1, 1])))
    else:
        mg["cooldown_bars"] = rng.choice([0, 1, 3, 6, 12, 24])
    return {}


def m_side(rng, g, htfs=()):
    """Ajoute/retire un côté (long/short) — exploration structurelle."""
    s = rng.choice(["long", "short"])
    other = "short" if s == "long" else "long"
    if g["entry"][s] is None:
        g["entry"][s] = random_tree(rng, g["market"]["timeframe"], 1 if s == "long" else -1, htfs)
    elif g["entry"][other] is not None:
        g["entry"][s] = None
    else:
        return None
    return {"side": s}


MUTATIONS = {"param": m_param, "const": m_const, "cmp": m_cmp, "replace_leaf": m_replace_leaf,
             "add_leaf": m_add_leaf, "remove_leaf": m_remove_leaf, "logic": m_logic, "exit": m_exit,
             "management": m_management, "side": m_side}


def mutate(rng: random.Random, g: dict, op: str, htfs=(), tries: int = 8) -> tuple[dict, dict] | None:
    for _ in range(tries):
        c = copy.deepcopy(g)
        detail = MUTATIONS[op](rng, c, htfs)
        if detail is None:
            return None
        c = model.renumber(c)
        if not model.validate(c, set(htfs)) and model.semantic_hash(c) != model.semantic_hash(g):
            return c, detail
    return None


# ---------- croisements ----------

def crossover(rng: random.Random, a: dict, b: dict, tries: int = 8) -> tuple[dict, dict] | None:
    """Croisement respectant les rôles : sous-arbre d'entrée du même côté, ou bloc de sortie entier."""
    if a["market"] != b["market"]:
        return None
    for _ in range(tries):
        c = copy.deepcopy(a)
        mode = rng.choice(["subtree", "exit", "side"])
        if mode == "exit":
            c["exit"] = copy.deepcopy(b["exit"])
        elif mode == "side":
            s = rng.choice(["long", "short"])
            c["entry"][s] = copy.deepcopy(b["entry"][s])
        else:
            s = rng.choice(["long", "short"])
            if c["entry"][s] is None or b["entry"][s] is None:
                continue
            donor = rng.choice(list(model.iter_nodes(b["entry"][s])))
            target = rng.choice(list(model.iter_nodes(c["entry"][s])))
            _replace(c, target, copy.deepcopy(donor))
        c = model.renumber(c)
        if not model.validate(c) and model.semantic_hash(c) not in (model.semantic_hash(a), model.semantic_hash(b)):
            return c, {"mode": mode}
    return None
