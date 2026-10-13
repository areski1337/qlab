"""Génère un Expert Advisor MQL5 déterministe depuis un génome canonique.

Aucun code n'est lu depuis le génome : seules des constantes validées et des
appels aux fonctions versionnées de la bibliothèque (templates/qlab_core.mqh)
sont émis. Une fonctionnalité non supportée BLOQUE l'export (jamais de
substitution silencieuse).
"""
from __future__ import annotations

import re
import zlib
from importlib import resources

from ..core.hashing import sha256_bytes
from ..core.versions import COMPONENT_VERSIONS, ENGINE_VERSION
from ..features import REGISTRY
from ..features.sessions import SESSIONS
from ..genome import model
from .window import feature_window

GENERATOR_VERSION = COMPONENT_VERSIONS["mql5_generator"]
SUPPORTED = {n for n in REGISTRY} - {"regime"}  # régimes : médiane glissante trop coûteuse en testeur (v1)
TF_ENUM = {"M1": "PERIOD_M1", "M5": "PERIOD_M5", "M15": "PERIOD_M15", "M30": "PERIOD_M30", "H1": "PERIOD_H1",
           "H4": "PERIOD_H4", "D1": "PERIOD_D1"}
ZONE = {"America/New_York": 0, "Europe/London": 1, "Asia/Tokyo": 2}


class UnsupportedForExport(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _tpl(name: str) -> str:
    return (resources.files("qlab.mql5") / "templates" / name).read_text(encoding="utf-8")


def check_exportable(g: dict, tz_profile: str) -> list[str]:
    reasons = []
    for r in model.refs(g):
        if r["feature"] not in SUPPORTED:
            reasons.append(f"feature « {r['feature']} » non supportée par le générateur MQL5 v{GENERATOR_VERSION}")
        if r["feature"] == "vwap" and r["params"].get("volume") == "real":
            reasons.append("vwap(volume=real) non exporté : volume réel rarement fourni par le courtier")
    if not (tz_profile in ("UTC", "NY+7") or re.fullmatch(r"UTC[+-]\d{1,2}", tz_profile)):
        reasons.append(f"profil de fuseau « {tz_profile} » non supporté par l'EA (UTC, UTC±N, NY+7)")
    return reasons


class _Ctx:
    def __init__(self, base_tf: str):
        self.base_tf = base_tf
        self.instances: dict[tuple, tuple[str, dict]] = {}   # (feature, params, tf) -> (nom, params)
        self.tfs: list[str] = [base_tf]
        self.max_shift = 0
        self.windows: dict[str, int] = {base_tf: 3}

    def inst(self, r: dict) -> str:
        tf = r.get("tf") or self.base_tf
        key = (r["feature"], repr(sorted(r["params"].items())), tf)
        if key not in self.instances:
            self.instances[key] = (f"I{len(self.instances)}", r["params"])
            if tf not in self.tfs:
                self.tfs.append(tf)
            self.windows[tf] = max(self.windows.get(tf, 3), feature_window(r["feature"], r["params"], tf))
        self.max_shift = max(self.max_shift, r.get("shift", 0) + 1)
        return self.instances[key][0]

    def bars(self, tf: str) -> str:
        return f"g_b{self.tfs.index(tf)}"

    def value(self, r: dict, extra: int = 0) -> str:
        name = self.inst(r)
        s = r.get("shift", 0) + extra
        tf = r.get("tf") or self.base_tf
        arr = f"{name}_{r['output']}"
        if tf == self.base_tf:
            return f"QL_At({arr}, g_b0, {s})"
        return f"QL_HTF({arr}, {self.bars(tf)}, g_b0, {s})"


def _expr(n: dict, c: _Ctx) -> str:
    op = n["op"]
    if op in ("and", "or"):
        j = " && " if op == "and" else " || "
        return "(" + j.join(_expr(ch, c) for ch in n["children"]) + ")"
    if op == "not":
        ch = n["children"][0]
        return f"(!{_expr(ch, c)} && {_computable(ch, c)})"
    if op == "event":
        return f"QL_EV({c.value(n['ref'])})"
    a = c.value(n["left"])
    b = repr(float(n["right"]["const"])) if "const" in n["right"] else c.value(n["right"])
    if n["cmp"] == "gt":
        return f"QL_GT({a}, {b})"
    if n["cmp"] == "lt":
        return f"QL_LT({a}, {b})"
    a1 = c.value(n["left"], 1)
    b1 = repr(float(n["right"]["const"])) if "const" in n["right"] else c.value(n["right"], 1)
    if n["cmp"] == "cross_above":
        return f"(QL_GT({a}, {b}) && QL_LE({a1}, {b1}))"
    return f"(QL_LT({a}, {b}) && QL_GE({a1}, {b1}))"


def _computable(node: dict, c: _Ctx) -> str:
    parts = []
    for m in model.iter_nodes(node):
        rs = [m["left"], m["right"]] if m["op"] == "compare" else [m["ref"]] if m["op"] == "event" else []
        for r in rs:
            if "feature" in r:
                parts.append(f"QL_OK({c.value(r)})")
                if m["op"] == "compare" and m["cmp"].startswith("cross"):
                    parts.append(f"QL_OK({c.value(r, 1)})")
    return "(" + " && ".join(parts or ["true"]) + ")"


def _call(feature: str, params: dict, inst: str, bars: str) -> str:
    spec = REGISTRY[feature]
    outs = ", ".join(f"{inst}_{o}" for o in spec.outputs)
    if feature == "session":
        zone, a, b = SESSIONS[params["name"]]
        hm = lambda s: int(s[:2]) * 60 + int(s[3:])
        args = [str(ZONE[zone]), str(hm(a)), str(hm(b))]
    elif feature == "structure":
        args = [str(params["left"]), str(params["right"]), "1" if params["break_on"] == "close" else "0",
                repr(float(params["disp_atr"]))]
    elif feature == "vwap":
        args = ["1" if params["anchor"] == "week" else "0", "0", repr(float(params["dev"]))]
    else:
        args = []
        for k, p in spec.params.items():
            v = params[k]
            args.append(repr(float(v)) if p.kind == "float" else str(int(v)))
    return f"   F_{feature}({', '.join([bars] + args + ([outs] if outs else []))});"


def generate(rev: dict, symbol: str, tz_profile: str, limits: dict, limits_sha: str, deviation_points: int = 10) -> dict:
    """Retourne {'source': str, 'sha256': str, 'meta': dict}. Lève UnsupportedForExport."""
    g = rev["content"]
    reasons = check_exportable(g, tz_profile)
    if reasons:
        raise UnsupportedForExport(reasons)
    c = _Ctx(g["market"]["timeframe"])
    long_expr = _expr(g["entry"]["long"], c) if g["entry"]["long"] else "false"
    short_expr = _expr(g["entry"]["short"], c) if g["entry"]["short"] else "false"

    ex = g["exit"]
    st = ex["stop"]
    if st["type"] == "atr":
        stop_atr_ref = {"feature": "atr", "params": {"period": st["period"]}, "output": "value"}
        stop_code = f"   double a = {c.value(stop_atr_ref)};\n   return {repr(float(st['mult']))} * a;"
    elif st["type"] == "points":
        stop_code = f"   return {int(st['points'])} * SymbolInfoDouble(_Symbol, SYMBOL_POINT);"
    else:
        sw = {"feature": "swings", "params": {"left": st["left"], "right": st["right"]}}
        a14 = {"feature": "atr", "params": {"period": 14}, "output": "value"}
        lo, hi, a = c.value({**sw, "output": "last_low"}), c.value({**sw, "output": "last_high"}), c.value(a14)
        stop_code = (f"   double a = {a};\n   double lvl = d == 1 ? {lo} - {repr(float(st['buffer_atr']))} * a"
                     f" : {hi} + {repr(float(st['buffer_atr']))} * a;\n   return (entry - lvl) * d;")
    tg = ex["target"]
    if tg is None:
        target_code, tkind = "   return QL_NAN;", 0
    elif tg["type"] == "rr":
        target_code, tkind = f"   return entry + d * {repr(float(tg['rr']))} * dist;", 1
    else:
        ta = {"feature": "atr", "params": {"period": tg["period"]}, "output": "value"}
        target_code, tkind = f"   double a = {c.value(ta)};\n   return QL_OK(a) ? entry + d * {repr(float(tg['mult']))} * a : QL_NAN;", 2
    tr = ex["trailing"]
    trail_code = "   return QL_NAN;"
    if tr:
        trr = {"feature": "atr", "params": {"period": tr["period"]}, "output": "value"}
        trail_code = f"   return {c.value(trr)};"

    # déclarations et calculs des instances
    decls, calls = [], []
    for (feat, _, tf), (inst, params) in c.instances.items():
        decls.append(f"double {', '.join(f'{inst}_{o}[]' for o in REGISTRY[feat].outputs)};   // {feat}{params} [{tf}]")
        calls.append(_call(feat, params, inst, c.bars(tf)))
    loads = "\n".join(f"   if(!QL_Load(_Symbol, {TF_ENUM[tf]}, {c.windows[tf]}, {c.bars(tf)})) return false;"
                      for tf in c.tfs)
    bars_decl = "QLBars " + ", ".join(c.bars(tf) for tf in c.tfs) + ";"
    tz_mode, tz_fixed = (0, 0) if tz_profile == "UTC" else (2, 0) if tz_profile == "NY+7" else (1, int(tz_profile[3:]) * 3600)
    magic = zlib.crc32(rev["semantic_hash"].encode()) & 0x7FFFFFFF
    W = max(c.windows.values())
    consts = {
        "QL_GEN_SYMBOL": f'"{symbol}"', "QL_GEN_TF": TF_ENUM[c.base_tf], "QL_GEN_K": str(c.max_shift + 2),
        "QL_GEN_TZ_MODE": str(tz_mode), "QL_GEN_TZ_FIXED": str(tz_fixed), "QL_GEN_MAGIC": str(magic),
        "QL_GEN_DEVIATION": str(int(deviation_points)), "QL_GEN_GENOME_HASH": f'"{rev["semantic_hash"]}"',
        "QL_GEN_REVISION": f'"{rev["id"]}"', "QL_GEN_W": str(W),
        "QL_GEN_EXIT_ON_OPPOSITE": "true" if ex["exit_on_opposite"] else "false",
        "QL_GEN_TIME_STOP": str(ex["time_stop_bars"] or 0),
        "QL_GEN_BE_AT_R": repr(float(ex["break_even"]["at_r"])) if ex["break_even"] else "0.0",
        "QL_GEN_TRAIL_MULT": repr(float(tr["mult"])) if tr else "0.0",
        "QL_GEN_TRAIL_ACTIVATE_R": repr(float(tr["activate_r"])) if tr else "0.0",
        "QL_GEN_COOLDOWN": str(g["management"]["cooldown_bars"]),
        "QL_GEN_MAX_TRADES_PER_DAY": str(g["management"]["max_trades_per_day"]),
        "QL_GEN_TARGET_KIND": str(tkind), "QL_GEN_RISK_PCT": repr(float(g["sizing"]["risk_pct"])),
        "QL_LIM_MAX_RISK_PCT": repr(float(limits["max_risk_per_trade_pct"])),
        "QL_LIM_MAX_DAILY_LOSS_PCT": repr(float(limits["max_daily_loss_pct"])),
        "QL_LIM_MAX_DD_PCT": repr(float(limits["max_drawdown_pct"])),
        "QL_LIM_MAX_LOTS": repr(float(limits["max_lots"])),
        "QL_LIM_MAX_ORDERS_PER_DAY": str(int(limits["max_orders_per_day"])),
        "QL_LIM_MAX_SPREAD_POINTS": repr(float(limits["max_spread_points"] or 0)),
        "QL_LIM_DAILY_PROFIT_TARGET_PCT": repr(float(limits.get("daily_profit_target_pct") or 0)),
        "QL_LIM_WEEKEND_MIN": repr(float(limits.get("close_before_weekend_minutes") or 0)),
        "QL_LIM_NEWS_ENABLED": "true" if (limits.get("news_filter") or {}).get("enabled") else "false",
    }
    desc = model.describe(g)
    header = [
        "//+------------------------------------------------------------------+",
        "//| EA généré par QLab — NE PAS MODIFIER À LA MAIN                     |",
        "//+------------------------------------------------------------------+",
        f"// genome_revision : {rev['id']}",
        f"// semantic_hash   : {rev['semantic_hash']}",
        f"// generator       : qlab.mql5_generator {GENERATOR_VERSION} (engine {ENGINE_VERSION})",
        f"// risk_limits     : sha256 {limits_sha} (limites absolues figées, non modifiables par input)",
        f"// timezone serveur: {tz_profile}",
        "// Hypothèses d'exécution : signal à la clôture, ordre au marché à l'ouverture suivante ;",
        "//   stop/objectif côté serveur ; une position à la fois ; refus sur compte réel.",
        "// Règles :",
    ] + [f"//   {k} : {v}" for k, v in desc.items()] + [
        "#property copyright \"QLab (recherche) — aucune garantie de performance\"",
        "#property version   \"1.0\"",
        "",
    ]
    defines = [f"#define {k} {v}" for k, v in consts.items()]
    body = "\n".join([
        *header, *defines, "", _tpl("qlab_core.mqh"), "",
        "// ===================== Instances de features (génome) =====================",
        bars_decl, *decls, "",
        "double QL_At(const double &a[], QLBars &b, const int s) { int i = b.n - 1 - s; return i < 0 ? QL_NAN : a[i]; }",
        "double QL_HTF(const double &a[], QLBars &h, QLBars &b, const int s)",
        "{",
        "   int i = b.n - 1 - s; if(i < 0) return QL_NAN;",
        "   int k = QL_AlignAt(h, b.t[i] + b.tfsec);",
        "   return k < 0 ? QL_NAN : a[k];",
        "}",
        "bool QL_LoadAll()", "{", loads, "   return true;", "}",
        "void QL_ComputeAll()", "{", *calls, "}",
        f"bool QL_LongSignal()  {{ return {long_expr}; }}",
        f"bool QL_ShortSignal() {{ return {short_expr}; }}",
        "double QL_StopDistance(const int d, const double entry)", "{", stop_code, "}",
        "double QL_Target(const int d, const double entry, const double dist)", "{", target_code, "}",
        "double QL_TrailATR()", "{", trail_code, "}",
        "", _tpl("ea_body.mq5"),
    ])
    body = body.replace("\r\n", "\n").replace("\n", "\r\n")
    data = body.encode("utf-8")
    return {"source": body, "sha256": sha256_bytes(data),
            "meta": {"generator": GENERATOR_VERSION, "window": W, "magic": magic, "timeframes": c.tfs,
                     "instances": len(c.instances), "tz_profile": tz_profile, "risk_limits_sha256": limits_sha}}
