"""Campagne génétique : tribus en parallèle (round-robin), fusion, checkpoints, reprise.

Déroulé : chaque tribu évolue `generations_per_tribe` générations sur le
segment TRAIN avec ses propres objectifs, puis une phase de fusion fait
évoluer l'union des archives avec des objectifs train + VALIDATION. Les
segments OOS et final ne sont jamais lus par une campagne.

Reprise : l'état complet (populations, archives, état du générateur aléatoire,
statistiques d'opérateurs) est sauvegardé atomiquement à chaque génération.
Les évaluations sont identifiées par une clé exacte : une génération rejouée
après un crash réutilise les évaluations existantes (AT-004).
"""
from __future__ import annotations

import json
import math
import random
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from ..backtest.costs import DEFAULT_COST_PROFILE
from ..core.hashing import sha256_json
from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..core.versions import COMPONENT_VERSIONS
from ..data.dataset import load_bars
from ..features import FeatureCache
from ..genome import model, store as gstore
from ..risk.controller import RiskController, load_limits
from ..storage.db import audit
from ..tasks import checkpoints, queue
from ..validation import protocol as proto
from . import nsga2, operators as ops

DEFAULT_CONFIG = {
    "name": "campagne",
    "dataset_version_id": None,
    "context_version_ids": {},
    "cost_profile": DEFAULT_COST_PROFILE,
    "protocol": proto.DEFAULT_PROTOCOL,
    "seed": 42,
    "population": 24,
    "generations_per_tribe": 20,
    "merge_generations": 8,
    "tribes": ["consistency", "growth", "exploration", "specialization"],
    "specialization_session": "london_kz",
    "constraints": {"min_trades": 30, "max_dd_pct": 30.0, "max_ambiguous_ratio": 0.3},
    "crossover_rate": 0.3,
    "sides": "both",
    "workers": 4,
    "initial_equity": 10_000.0,
    "stagnation_generations": 5,
}


def _v(x, worst=-1e6):
    return worst if x is None or not math.isfinite(x) else float(x)


def objectives(tribe: str, m: dict, novelty: float = 0.0, val: dict | None = None) -> tuple:
    if tribe == "consistency":
        return (_v(m["sharpe"]), -_v(m["max_dd_pct"], 1e6), _v(m["r2_equity"], -1), _v(m["positive_months_ratio"], 0))
    if tribe == "growth":
        return (_v(m["return_pct"]), _v(m["sharpe"]), -_v(m["max_dd_pct"], 1e6))
    if tribe == "exploration":
        return (novelty, _v(m["sharpe"]))
    if tribe == "specialization":
        return (_v(m["expectancy_r"]), _v(m["sharpe"]), -_v(m["max_dd_pct"], 1e6))
    if tribe == "merge":
        v = val or {}
        return (_v(m["sharpe"]), _v(v.get("sharpe")), -max(_v(m["max_dd_pct"], 1e6), _v(v.get("max_dd_pct"), 1e6)))
    raise ValueError(tribe)


def violation(m: dict, c: dict, g: dict | None = None, special: str | None = None) -> float:
    v = 0.0
    n = m["n_trades"]
    if n < c["min_trades"]:
        v += (c["min_trades"] - n) / c["min_trades"]
    if n and m["max_dd_pct"] is not None and m["max_dd_pct"] > c["max_dd_pct"]:
        v += (m["max_dd_pct"] - c["max_dd_pct"]) / c["max_dd_pct"]
    if n and m["ambiguous_ratio"] is not None and m["ambiguous_ratio"] > c["max_ambiguous_ratio"]:
        v += m["ambiguous_ratio"] - c["max_ambiguous_ratio"]
    if m.get("halted"):
        v += 1.0
    if special and g is not None and not has_session(g, special):
        v += 1.0
    return v


def has_session(g: dict, name: str) -> bool:
    for s in ("long", "short"):
        root = g["entry"][s]
        if root is None:
            continue
        found = any(n["op"] == "event" and n["ref"]["feature"] == "session" and n["ref"]["params"]["name"] == name
                    for n in model.iter_nodes(root))
        if not found:
            return False
    return True


def behavior(m: dict) -> np.ndarray:
    return np.array([math.log1p(m["n_trades"]), _v(m.get("win_rate"), 0), math.log1p(_v(m.get("avg_bars_held"), 0)),
                     _v(m.get("long_share"), 0.5), max(-2, min(2, _v(m.get("expectancy_r"), 0)))])


def novelty(b: np.ndarray, others: list[np.ndarray], k: int = 5) -> float:
    if not others:
        return 0.0
    d = np.sort([float(np.linalg.norm(b - o)) for o in others])
    return float(d[:k].mean())


# ---------- workers ----------

_W: dict = {}


def _init_worker(root, dsv, ctx_ids, costs, limits):
    from ..lab import Lab
    lab = Lab.open(root)
    bars = load_bars(lab, dsv)
    ctx = {tf: load_bars(lab, vid) for tf, vid in ctx_ids.items()}
    lab.close()
    _W.update(cache=FeatureCache(bars, ctx), costs=costs, risk=RiskController(limits))


def _eval(content: dict, window) -> dict:
    m, _ = proto.compute_metrics(content, _W["cache"], _W["costs"], _W["risk"], window)
    return m


# ---------- campagne ----------

class Campaign:
    def __init__(self, lab, task_id: str, campaign_id: str, config: dict):
        self.lab, self.task_id, self.cid, self.cfg = lab, task_id, campaign_id, config
        self.limits = load_limits(lab.paths.risk_limits)
        self.risk = RiskController(self.limits)
        self.bars = load_bars(lab, config["dataset_version_id"])
        self.ctx = {tf: load_bars(lab, vid) for tf, vid in config["context_version_ids"].items()}
        self.cache = FeatureCache(self.bars, self.ctx)
        seg = proto.segments(len(self.bars), config["protocol"])
        self.windows = {"train": seg["train"], "validation": seg["validation"]}
        self.symbol, self.tf = self.bars.symbol, self.bars.timeframe
        self.htfs = tuple(sorted(self.ctx))

    # -- persistance d'un candidat et de son évaluation --
    def revision(self, content: dict, parents=None) -> dict:
        h = model.semantic_hash(content)
        row = self.lab.con.execute("SELECT id FROM genome_revisions WHERE campaign_id=? AND semantic_hash=? LIMIT 1",
                                   (self.cid, h)).fetchone()
        if row:
            return gstore.get(self.lab.con, row["id"])
        return gstore.create_revision(self.lab.con, content, parents, self.cid)

    def evaluate_many(self, revs: list[dict], segment: str, pool) -> list[dict]:
        w = self.windows[segment]
        keys = [proto.cache_key(r["semantic_hash"], self.cache, self.cfg["cost_profile"], self.risk, segment, w,
                                self.cfg["protocol"]) for r in revs]
        out: list[dict | None] = [None] * len(revs)
        todo = []
        for i, k in enumerate(keys):
            hit = proto.find(self.lab, k)
            if hit:
                out[i] = hit["metrics"]
            elif k not in [keys[j] for j in todo]:
                todo.append(i)
        results = list(pool.map(_eval, [revs[i]["content"] for i in todo], [w] * len(todo))) if pool else \
            [_eval_local(self, revs[i]["content"], w) for i in todo]
        for i, m in zip(todo, results):
            proto.store(self.lab, keys[i], revs[i]["id"], self.cache, self.cfg["cost_profile"], self.risk, segment, w,
                        self.cfg["protocol"], m, None, self.cid, False)
        for i, k in enumerate(keys):
            if out[i] is None:
                out[i] = proto.find(self.lab, k)["metrics"]
        return out

    # -- état initial --
    def init_state(self) -> dict:
        rng = random.Random(self.cfg["seed"])
        pops = {}
        for t in self.cfg["tribes"]:
            pops[t] = []
            for _ in range(self.cfg["population"]):
                g = ops.random_genome(rng, self.symbol, self.tf, self.cfg["sides"], self.htfs)
                if t == "specialization":
                    g = specialize(g, self.cfg["specialization_session"])
                pops[t].append(self.revision(g)["id"])
        return {"phase": "tribes", "gen": 0, "pops": pops, "archives": {t: [] for t in self.cfg["tribes"]},
                "rng": _rng_dump(rng), "op_stats": {op: [0, 0] for op in ops.MUTATIONS} | {"crossover": [0, 0]},
                "stagnation": {t: {"best": None, "since": 0, "level": 0} for t in self.cfg["tribes"] + ["merge"]},
                "history": [], "behaviors": []}

    def run(self) -> dict:
        lab = self.lab
        st = checkpoints.latest(lab.con, lab.store, self.task_id) or self.init_state()
        rng = _rng_load(st["rng"])
        total = self.cfg["generations_per_tribe"] + self.cfg["merge_generations"]
        workers = max(0, int(self.cfg["workers"]))
        pool = ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(
            str(lab.paths.root), self.cfg["dataset_version_id"], self.cfg["context_version_ids"],
            self.cfg["cost_profile"], self.limits)) if workers > 0 else None
        try:
            while True:
                state = queue.get(lab.con, self.task_id)["state"]
                if state in ("paused", "cancelled"):
                    return {"stopped": state, "gen": st["gen"]}
                if st["phase"] == "tribes" and st["gen"] >= self.cfg["generations_per_tribe"]:
                    st = self.start_merge(st, pool)
                if st["phase"] == "merge" and st["gen"] >= total:
                    break
                tribes = self.cfg["tribes"] if st["phase"] == "tribes" else ["merge"]
                for t in tribes:
                    self.generation(st, t, rng, pool)
                st["gen"] += 1
                st["rng"] = _rng_dump(rng)
                checkpoints.save(lab.con, lab.store, self.task_id, st)
                queue.set_progress(lab.con, self.task_id, st["gen"] / total)
            return self.finish(st, pool)
        finally:
            if pool:
                pool.shutdown(cancel_futures=True)

    def generation(self, st: dict, tribe: str, rng: random.Random, pool) -> None:
        key = "merge" if tribe == "merge" else tribe
        pop_ids = st["pops"][key]
        parents = [gstore.get(self.lab.con, i) for i in pop_ids]
        pm = self.evaluate_many(parents, "train", pool)
        pv = self.evaluate_many(parents, "validation", pool) if tribe == "merge" else [None] * len(parents)
        stag = st["stagnation"][key]
        n = self.cfg["population"]
        p_obj, p_vio = self.score(tribe, parents, pm, pv, st)
        _, rank, crowd = nsga2.select(p_obj, p_vio, len(parents))
        idx = list(range(len(parents)))

        # descendants (taux d'exploration croissant en cas de stagnation)
        children, origin = [], []
        n_imm = int(n * 0.2) if stag["level"] > 0 else 0
        for _ in range(n_imm):
            g = ops.random_genome(rng, self.symbol, self.tf, self.cfg["sides"], self.htfs)
            if tribe == "specialization":
                g = specialize(g, self.cfg["specialization_session"])
            children.append(self.revision(g))
            origin.append(("immigrant", None))
        tries = 0
        while len(children) < n and tries < n * 6:
            tries += 1
            a = parents[nsga2.tournament(rng, idx, rank, crowd)]
            if rng.random() < self.cfg["crossover_rate"]:
                b = parents[nsga2.tournament(rng, idx, rank, crowd)]
                res = ops.crossover(rng, a["content"], b["content"])
                if res:
                    children.append(self.revision(res[0], [(a["id"], "crossover", res[1]), (b["id"], "crossover", res[1])]))
                    origin.append(("crossover", a["id"]))
                    continue
            op = self.pick_op(rng, st, stag["level"])
            res = ops.mutate(rng, a["content"], op, self.htfs)
            if res:
                children.append(self.revision(res[0], [(a["id"], op, res[1])]))
                origin.append((op, a["id"]))
        cm = self.evaluate_many(children, "train", pool)
        cv = self.evaluate_many(children, "validation", pool) if tribe == "merge" else [None] * len(children)

        allr, allm, allv = parents + children, pm + cm, pv + cv
        objs, vio = self.score(tribe, allr, allm, allv, st)
        chosen, rank2, _ = nsga2.select(objs, vio, n)
        # dédoublonnage : un même comportement sémantique n'occupe qu'une place
        seen, keep = set(), []
        for i in chosen:
            if allr[i]["semantic_hash"] not in seen:
                seen.add(allr[i]["semantic_hash"])
                keep.append(i)
        st["pops"][key] = [allr[i]["id"] for i in keep]

        # mémoire des opérateurs : succès = enfant présent dans le premier front
        for j, (op, _) in enumerate(origin):
            if op == "immigrant":
                continue
            ci = len(parents) + j
            s = st["op_stats"].setdefault(op, [0, 0])
            s[0] += 1
            s[1] += int(rank2.get(ci, 99) == 0 and vio[ci] == 0)
        # archive : premier front faisable
        front = [i for i in chosen if rank2[i] == 0 and vio[i] == 0]
        arch = list(dict.fromkeys(st["archives"].get(key, []) + [allr[i]["id"] for i in front]))[-60:]
        st["archives"][key] = arch
        st["behaviors"] = (st["behaviors"] + [behavior(allm[i]).tolist() for i in front])[-500:]

        # stagnation : meilleur premier objectif faisable
        feas = [objs[i][0] for i in chosen if vio[i] == 0]
        best = max(feas) if feas else None
        if best is not None and (stag["best"] is None or best > stag["best"] + 1e-6):
            stag.update(best=best, since=0, level=0)
        else:
            stag["since"] += 1
            if stag["since"] >= self.cfg["stagnation_generations"]:
                stag["level"] = min(stag["level"] + 1, 3)
                stag["since"] = 0
        st["history"].append({"gen": st["gen"], "tribe": tribe, "ts": utc_now_iso(),
                              "feasible": int(sum(1 for i in chosen if vio[i] == 0)),
                              "best_obj": best, "front": len(front), "stagnation_level": stag["level"],
                              "diversity": diversity([allr[i] for i in keep], [allm[i] for i in keep])})

    def score(self, tribe, revs, ms, vs, st):
        sp = self.cfg["specialization_session"] if tribe == "specialization" else None
        beh_arch = [np.array(b) for b in st["behaviors"]]
        objs, vio = [], []
        for r, m, v in zip(revs, ms, vs):
            nov = novelty(behavior(m), beh_arch) if tribe == "exploration" else 0.0
            objs.append(objectives(tribe, m, nov, v))
            viol = violation(m, self.cfg["constraints"], r["content"], sp)
            if v is not None:
                viol += violation(v, {**self.cfg["constraints"],
                                      "min_trades": max(5, self.cfg["constraints"]["min_trades"] // 3)})
            vio.append(viol)
        return objs, vio

    def pick_op(self, rng, st, level: int) -> str:
        names = list(ops.MUTATIONS)
        w = []
        for op in names:
            t, s = st["op_stats"].get(op, [0, 0])
            w.append((s + 1) / (t + 2))
        tot = sum(w)
        w = [max(x / tot, 0.03) for x in w]  # plancher : aucun opérateur n'est jamais banni
        if level > 0:  # stagnation : favoriser les opérateurs structurels
            w = [x * (1 + level) if op in ("replace_leaf", "add_leaf", "side", "logic") else x for op, x in zip(names, w)]
        return rng.choices(names, w)[0]

    def start_merge(self, st: dict, pool) -> dict:
        ids = list(dict.fromkeys(i for t in self.cfg["tribes"] for i in st["archives"][t]))
        if len(ids) < 4:  # archives trop pauvres : on complète par les populations finales
            ids = list(dict.fromkeys(ids + [i for t in self.cfg["tribes"] for i in st["pops"][t]]))
        st["pops"]["merge"] = ids[: self.cfg["population"] * 2]
        st["archives"]["merge"] = []
        st["phase"] = "merge"
        audit(self.lab.con, "campaign.merge_started", self.cid, n=len(st["pops"]["merge"]))
        return st

    def finish(self, st: dict, pool) -> dict:
        ids = st["pops"]["merge"]
        revs = [gstore.get(self.lab.con, i) for i in ids]
        tm = self.evaluate_many(revs, "train", pool)
        vm = self.evaluate_many(revs, "validation", pool)
        objs, vio = self.score("merge", revs, tm, vm, st)
        F = nsga2.fronts(objs, vio)
        front = [i for i in F[0] if vio[i] == 0] if F else []
        n_eval = self.lab.con.execute("SELECT COUNT(*) FROM evaluations WHERE campaign_id=?", (self.cid,)).fetchone()[0]
        n_rev = self.lab.con.execute("SELECT COUNT(*) FROM genome_revisions WHERE campaign_id=?", (self.cid,)).fetchone()[0]
        for i in front:
            r = revs[i]
            if r["status"] == "unverified":
                ev = proto.find(self.lab, proto.cache_key(r["semantic_hash"], self.cache, self.cfg["cost_profile"],
                                                          self.risk, "train", self.windows["train"], self.cfg["protocol"]))
                gstore.set_status(self.lab.con, r["id"], "screened",
                                  {"rule": "front de Pareto final faisable (contraintes éliminatoires respectées)",
                                   "constraints": self.cfg["constraints"]},
                                  {"train_evaluation": ev["id"], "campaign": self.cid})
        self.save_memory(st)
        return {"front": [{"revision_id": revs[i]["id"], "train": tm[i], "validation": vm[i],
                           "objectives": objs[i]} for i in front],
                "candidates_generated": n_rev, "evaluations": n_eval, "op_stats": st["op_stats"],
                "history": st["history"][-50:],
                "warning": "Le meilleur résultat observé parmi de nombreux candidats est biaisé à la hausse "
                           "(biais de sélection) : ce n'est pas une estimation de la performance future."}

    def save_memory(self, st: dict) -> None:
        for scope in ("global", f"campaign:{self.cid}"):
            for op, (t, s) in st["op_stats"].items():
                self.lab.con.execute(
                    "INSERT INTO evolution_memory VALUES (?,?,?,?,?) ON CONFLICT(scope,key) DO UPDATE SET "
                    "tries=tries+excluded.tries, successes=successes+excluded.successes, updated_at=excluded.updated_at",
                    (scope, f"operator:{op}", t, s, utc_now_iso()))


def _eval_local(c: Campaign, content, window):
    m, _ = proto.compute_metrics(content, c.cache, c.cfg["cost_profile"], c.risk, window)
    return m


def specialize(g: dict, session: str) -> dict:
    leaf = {"id": "n0", "op": "event", "ref": {"feature": "session", "params": {"name": session}, "output": "active"}}
    for s in ("long", "short"):
        if g["entry"][s] is not None and not has_session({"entry": {"long": g["entry"][s], "short": None}}, session):
            g["entry"][s] = {"id": "n0", "op": "and", "children": [leaf, g["entry"][s]]}
    return model.renumber(g)


def diversity(revs: list[dict], ms: list[dict]) -> dict:
    feats = [frozenset(r["feature"] for r in model.refs(x["content"])) for x in revs]
    jd = []
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            u = feats[i] | feats[j]
            jd.append(1 - len(feats[i] & feats[j]) / len(u) if u else 0.0)
    beh = [behavior(m) for m in ms]
    bd = [float(np.linalg.norm(beh[i] - beh[j])) for i in range(len(beh)) for j in range(i + 1, len(beh))]
    return {"structural": float(np.mean(jd)) if jd else 0.0, "behavioral": float(np.mean(bd)) if bd else 0.0,
            "lineages": len({r["genome_id"] for r in revs}), "size": len(revs)}


def _rng_dump(rng):
    v, s, g = rng.getstate()
    return [v, list(s), g]


def _rng_load(d):
    r = random.Random()
    r.setstate((d[0], tuple(d[1]), d[2]))
    return r


def create(lab, config: dict) -> tuple[str, str]:
    """Enregistre la campagne et sa tâche. Retourne (campaign_id, task_id)."""
    cfg = {**DEFAULT_CONFIG, **config}
    if not cfg["dataset_version_id"]:
        raise ValueError("dataset_version_id requis")
    if not cfg["tribes"]:
        raise ValueError("au moins une tribu requise")
    for t in cfg["tribes"]:
        objectives(t, {k: None for k in ("sharpe", "max_dd_pct", "r2_equity", "positive_months_ratio",
                                          "return_pct", "expectancy_r")})
    if cfg["cost_profile"].get("fixed_spread_points") is None:
        bars = load_bars(lab, cfg["dataset_version_id"])
        if (bars.spread <= 0).any():
            raise ValueError("spread historique inconnu sur ce dataset : renseigner cost_profile.fixed_spread_points")
    cid = new_id("camp")
    csha = sha256_json(cfg)
    tid = queue.submit(lab.con, "campaign", {"campaign_id": cid}, idempotency_key=f"campaign:{cid}")
    lab.con.execute("INSERT INTO campaigns VALUES (?,?,?,?,?,?,?)",
                    (cid, cfg["name"], json.dumps(cfg), csha, tid, "created", utc_now_iso()))
    audit(lab.con, "campaign.created", cid, config_sha256=csha, operators=COMPONENT_VERSIONS["evolution_operators"])
    return cid, tid


def run_task(lab, task: dict) -> dict:
    cid = task["payload"]["campaign_id"]
    cfg = json.loads(lab.con.execute("SELECT config_json FROM campaigns WHERE id=?", (cid,)).fetchone()[0])
    out = Campaign(lab, task["id"], cid, cfg).run()
    lab.con.execute("UPDATE campaigns SET state=? WHERE id=?", (out.get("stopped", "completed"), cid))
    return out
