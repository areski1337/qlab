"""Génome canonique : validation structurelle + sémantique, empreinte, rendu lisible, signaux.

Le génome est une DONNÉE déclarative : aucun code n'est jamais exécuté depuis
son contenu ; seules les features du registre peuvent être référencées.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from importlib import resources

import jsonschema
import numpy as np

from ..core.hashing import sha256_json
from ..data.mtf import align_values
from ..features import REGISTRY, FeatureCache, validate_params

SCHEMA_ID = "qlab.genome/1.0"
MAX_NODES = 500  # garde-fou de ressources (pas un plafond de découverte) — voir docs/decisions


@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads((resources.files("qlab.genome") / "schema.json").read_text(encoding="utf-8"))


def iter_nodes(node):
    if node is None:
        return
    yield node
    for c in node.get("children", ()):
        yield from iter_nodes(c)


def all_nodes(g: dict) -> list[dict]:
    return [n for side in ("long", "short") for n in iter_nodes(g["entry"][side])]


def refs(g: dict) -> list[dict]:
    out = []
    for n in all_nodes(g):
        if n["op"] == "compare":
            out.append(n["left"])
            if "feature" in n["right"]:
                out.append(n["right"])
        elif n["op"] == "event":
            out.append(n["ref"])
    return out


def _ref_kind(r: dict, path: str, errs: list[str]) -> str | None:
    spec = REGISTRY.get(r["feature"])
    if spec is None:
        errs.append(f"{path}: feature inconnue « {r['feature']} »")
        return None
    errs.extend(f"{path}: {e}" for e in validate_params(r["feature"], r["params"]))
    if r["output"] not in spec.outputs:
        errs.append(f"{path}: sortie « {r['output']} » absente de {r['feature']} ({sorted(spec.outputs)})")
        return None
    return spec.outputs[r["output"]]


def validate(g: dict, available_tfs: set[str] | None = None) -> list[str]:
    """Retourne la liste des erreurs (vide si valide). Diagnostic précis par chemin (AT-002)."""
    errs = [f"{'/'.join(map(str, e.absolute_path)) or '(racine)'}: {e.message}"
            for e in jsonschema.Draft202012Validator(schema()).iter_errors(g)]
    if errs:
        return errs
    nodes = all_nodes(g)
    if g["entry"]["long"] is None and g["entry"]["short"] is None:
        errs.append("entry: aucune règle d'entrée (long et short absents) — sémantique d'exécution indéfinie")
    if len(nodes) > MAX_NODES:
        errs.append(f"entry: {len(nodes)} nœuds > garde-fou de ressources {MAX_NODES}")
    ids = [n["id"] for n in nodes]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.append(f"entry: identifiants de nœuds dupliqués {dup}")
    for n in nodes:
        p = f"node {n['id']}"
        if n["op"] == "event":
            k = _ref_kind(n["ref"], p, errs)
            if k is not None and k != "bool":
                errs.append(f"{p}: un événement exige une sortie bool, « {n['ref']['output']} » est {k}")
        elif n["op"] == "compare":
            lk = _ref_kind(n["left"], p + ".left", errs)
            if "const" in n["right"]:
                c = n["right"]["const"]
                if lk == "bool":
                    errs.append(f"{p}: comparer un bool à une constante est interdit (utiliser event)")
                elif lk == "price":
                    errs.append(f"{p}: un prix ne se compare pas à une constante (dépend de l'instrument)")
                elif lk == "osc100" and not 0 <= c <= 100:
                    errs.append(f"{p}: constante {c} hors de 0..100 pour un oscillateur borné")
                elif lk == "ratio" and c < 0:
                    errs.append(f"{p}: constante négative pour un ratio positif")
            else:
                rk = _ref_kind(n["right"], p + ".right", errs)
                if lk and rk and lk != rk:
                    errs.append(f"{p}: types incompatibles {lk} vs {rk}")
                elif lk == "bool":
                    errs.append(f"{p}: comparaison de booléens interdite (utiliser and/or/not)")
                elif lk == "signed" and n["left"]["feature"] != n["right"]["feature"]:
                    errs.append(f"{p}: oscillateurs signés de features différentes non comparables")
                if n["left"] == n["right"]:
                    errs.append(f"{p}: comparaison d'une valeur avec elle-même (toujours vraie/fausse)")
    base_tf = g["market"]["timeframe"]
    from ..core.timeutil import tf_seconds
    for r in refs(g):
        tf = r.get("tf")
        if tf and tf_seconds(tf) < tf_seconds(base_tf):
            errs.append(f"ref {r['feature']}: timeframe {tf} inférieur au timeframe d'exécution {base_tf}")
        if tf and tf != base_tf and available_tfs is not None and tf not in available_tfs:
            errs.append(f"ref {r['feature']}: données {tf} indisponibles")
    return errs


def strip_ids(node):
    if node is None:
        return None
    n = {k: v for k, v in node.items() if k != "id"}
    if "children" in n:
        n["children"] = [strip_ids(c) for c in n["children"]]
    return n


def semantic_hash(g: dict) -> str:
    """Empreinte du comportement : ignore les identifiants de nœuds (renumérotation sans effet)."""
    h = copy.deepcopy(g)
    for s in ("long", "short"):
        h["entry"][s] = strip_ids(h["entry"][s])
    return sha256_json(h)


def renumber(g: dict) -> dict:
    """Attribue des identifiants stables n1..nK en ordre préfixe."""
    g = copy.deepcopy(g)
    k = 0
    for n in all_nodes(g):
        k += 1
        n["id"] = f"n{k}"
    return g


# ---------- rendu lisible ----------

CMP_FR = {"gt": ">", "lt": "<", "cross_above": "croise au-dessus de", "cross_below": "croise en dessous de"}


def ref_fr(r: dict) -> str:
    p = ",".join(f"{k}={v}" for k, v in r["params"].items())
    s = f"{r['feature']}({p}).{r['output']}"
    if r.get("tf"):
        s += f"[{r['tf']}]"
    if r.get("shift"):
        s += f"[-{r['shift']}]"
    return s


def node_fr(n) -> str:
    if n is None:
        return "—"
    op = n["op"]
    if op in ("and", "or"):
        j = " ET " if op == "and" else " OU "
        return "(" + j.join(node_fr(c) for c in n["children"]) + ")"
    if op == "not":
        return f"NON {node_fr(n['children'][0])}"
    if op == "event":
        return ref_fr(n["ref"])
    right = str(n["right"]["const"]) if "const" in n["right"] else ref_fr(n["right"])
    return f"{ref_fr(n['left'])} {CMP_FR[n['cmp']]} {right}"


def describe(g: dict) -> dict:
    ex = g["exit"]
    st = ex["stop"]
    stop = {"atr": lambda: f"{st['mult']} × ATR({st['period']})", "points": lambda: f"{st['points']} points",
            "swing": lambda: f"dernier swing ({st['left']}/{st['right']}) ± {st['buffer_atr']} × ATR(14)"}[st["type"]]()
    tg = ex["target"]
    target = "aucun" if tg is None else (f"{tg['rr']} R" if tg["type"] == "rr" else f"{tg['mult']} × ATR({tg['period']})")
    return {
        "marché": f"{g['market']['symbol']} {g['market']['timeframe']}",
        "entrée long": node_fr(g["entry"]["long"]),
        "entrée short": node_fr(g["entry"]["short"]),
        "exécution": "signal à la clôture de la barre, ordre au marché à l'ouverture suivante",
        "stop": stop, "objectif": target,
        "break-even": f"à {ex['break_even']['at_r']} R" if ex["break_even"] else "non",
        "trailing": (f"{ex['trailing']['mult']} × ATR({ex['trailing']['period']}) après {ex['trailing']['activate_r']} R"
                     if ex["trailing"] else "non"),
        "time stop": f"{ex['time_stop_bars']} barres" if ex["time_stop_bars"] else "non",
        "sortie sur signal opposé": "oui" if ex["exit_on_opposite"] else "non",
        "risque demandé": f"{g['sizing']['risk_pct']} % (plafonné par le contrôleur de risque)",
        "gestion": f"max {g['management']['max_trades_per_day']} trades/jour, pause {g['management']['cooldown_bars']} barres",
    }


# ---------- évaluation vectorisée des signaux ----------

def _values(r: dict, cache: FeatureCache) -> np.ndarray:
    tf = r.get("tf")
    arr = cache.get(r["feature"], r["params"], tf)[r["output"]].astype(float)
    if tf and tf != cache.bars.timeframe:
        htf = cache.context[tf]
        arr = align_values(cache.bars.ts_close, htf.ts_close, arr)
    sh = r.get("shift", 0)
    if sh:
        arr = np.concatenate([np.full(sh, np.nan), arr[:-sh]])
    return arr


def _operand(o: dict, cache: FeatureCache, n: int) -> np.ndarray:
    return np.full(n, float(o["const"])) if "const" in o else _values(o, cache)


def eval_node(node, cache: FeatureCache) -> np.ndarray:
    n = len(cache.bars)
    op = node["op"]
    if op == "and":
        out = np.ones(n, bool)
        for c in node["children"]:
            out &= eval_node(c, cache)
        return out
    if op == "or":
        out = np.zeros(n, bool)
        for c in node["children"]:
            out |= eval_node(c, cache)
        return out
    if op == "not":
        # NON d'une condition non calculable reste non calculable : on n'invente pas un « vrai ».
        child = node["children"][0]
        return ~eval_node(child, cache) & _computable(child, cache)
    if op == "event":
        v = _values(node["ref"], cache)
        return np.nan_to_num(v, nan=0.0) > 0.5
    a, b = _values(node["left"], cache), _operand(node["right"], cache, n)
    with np.errstate(invalid="ignore"):
        if node["cmp"] == "gt":
            return a > b
        if node["cmp"] == "lt":
            return a < b
        pa, pb = np.concatenate([[np.nan], a[:-1]]), np.concatenate([[np.nan], b[:-1]])
        if node["cmp"] == "cross_above":
            return (a > b) & (pa <= pb)
        return (a < b) & (pa >= pb)


def _computable(node, cache: FeatureCache) -> np.ndarray:
    n = len(cache.bars)
    ok = np.ones(n, bool)
    for m in iter_nodes(node):
        rs = [m["left"], m["right"]] if m["op"] == "compare" else [m["ref"]] if m["op"] == "event" else []
        for r in rs:
            if "feature" in r:
                v = _values(r, cache)
                ok &= np.isfinite(v)
                if m["op"] == "compare" and m["cmp"].startswith("cross"):
                    ok &= np.isfinite(np.concatenate([[np.nan], v[:-1]]))
    return ok


def signals(g: dict, cache: FeatureCache) -> tuple[np.ndarray, np.ndarray]:
    n = len(cache.bars)
    z = np.zeros(n, bool)
    lg = eval_node(g["entry"]["long"], cache) if g["entry"]["long"] else z
    sh = eval_node(g["entry"]["short"], cache) if g["entry"]["short"] else z
    return lg, sh
