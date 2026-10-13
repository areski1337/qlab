"""Révisions immuables de génomes, filiation et statuts de validation."""
from __future__ import annotations

import json

from ..core.ids import new_id
from ..core.timeutil import utc_now_iso
from ..core.versions import COMPONENT_VERSIONS
from ..storage.db import audit
from . import model

LADDER = ["unverified", "screened", "historically_tested", "robustness_tested", "oos_evaluated",
          "reference_matched", "mt5_validated", "demo_observed"]


class InvalidGenome(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class IllegalStatus(ValueError):
    pass


def create_revision(con, content: dict, parents: list[tuple[str, str, dict]] | None = None,
                    campaign_id: str | None = None) -> dict:
    """Valide puis enregistre une révision. parents = [(revision_id, opérateur, détail)].

    Mutation (1 parent) : révision suivante du même génome. Croisement / création : nouveau génome.
    """
    errs = model.validate(content)
    if errs:
        raise InvalidGenome(errs)
    content = model.renumber(content)
    parents = parents or []
    if len(parents) == 1:
        p = con.execute("SELECT genome_id FROM genome_revisions WHERE id=?", (parents[0][0],)).fetchone()
        gid = p["genome_id"]
        rev = con.execute("SELECT MAX(revision) FROM genome_revisions WHERE genome_id=?", (gid,)).fetchone()[0] + 1
    else:
        gid, rev = new_id("gen"), 1
    rid = new_id("rev")
    con.execute("INSERT INTO genome_revisions (id, genome_id, revision, content_json, semantic_hash, campaign_id, created_at) "
                "VALUES (?,?,?,?,?,?,?)", (rid, gid, rev, json.dumps(content, sort_keys=True),
                                           model.semantic_hash(content), campaign_id, utc_now_iso()))
    for pid, op, detail in parents:
        con.execute("INSERT INTO genealogy VALUES (?,?,?,?,?)",
                    (rid, pid, op, COMPONENT_VERSIONS["evolution_operators"], json.dumps(detail)))
    return get(con, rid)


def get(con, rid: str) -> dict:
    r = con.execute("SELECT * FROM genome_revisions WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise KeyError(rid)
    d = dict(r)
    d["content"] = json.loads(d.pop("content_json"))
    return d


def lineage(con, rid: str, depth: int = 50) -> list[dict]:
    """Ancêtres (parcours en largeur) avec opérateurs — vérifiable jusqu'aux racines (AT-003)."""
    out, frontier, seen = [], [rid], {rid}
    for _ in range(depth):
        nxt = []
        for c in frontier:
            for r in con.execute("SELECT * FROM genealogy WHERE child_id=?", (c,)):
                out.append(dict(r))
                if r["parent_id"] not in seen:
                    seen.add(r["parent_id"])
                    nxt.append(r["parent_id"])
        if not nxt:
            break
        frontier = nxt
    return out


def set_status(con, rid: str, to: str, criteria: dict, evidence: dict) -> None:
    """Transition contrôlée : un seul cran à la fois sur l'échelle, preuves obligatoires."""
    cur = get(con, rid)["status"]
    if to in ("rejected", "quarantined"):
        ok = cur not in ("rejected",)
    elif cur == "quarantined":
        ok = to == "unverified"
    elif cur == "rejected":
        ok = False
    else:
        ok = to in LADDER and LADDER.index(to) == LADDER.index(cur) + 1
    if not ok:
        raise IllegalStatus(f"transition de statut interdite {cur} → {to}")
    if not evidence:
        raise IllegalStatus("aucune transition de statut sans preuve")
    con.execute("UPDATE genome_revisions SET status=? WHERE id=?", (to, rid))
    con.execute("INSERT INTO status_transitions (revision_id, from_status, to_status, criteria_json, evidence_json, ts) "
                "VALUES (?,?,?,?,?,?)", (rid, cur, to, json.dumps(criteria), json.dumps(evidence), utc_now_iso()))
    audit(con, "genome.status", rid, frm=cur, to=to)


def transitions(con, rid: str) -> list[dict]:
    rows = con.execute("SELECT * FROM status_transitions WHERE revision_id=? ORDER BY id", (rid,))
    return [{**dict(r), "criteria": json.loads(r["criteria_json"]), "evidence": json.loads(r["evidence_json"])}
            for r in rows]
