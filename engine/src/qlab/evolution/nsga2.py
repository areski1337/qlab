"""NSGA-II (Deb et al., 2002) avec domination contrainte.

Tous les objectifs sont à MAXIMISER. Une solution faisable domine toute
solution infaisable ; deux infaisables se comparent par violation totale.
Les contraintes éliminatoires ne sont donc jamais compensées par un objectif.
"""
from __future__ import annotations

import math


def dominates(a: tuple, b: tuple, va: float, vb: float) -> bool:
    if va == 0 and vb > 0:
        return True
    if va > 0 or vb > 0:
        return va < vb
    return all(x >= y for x, y in zip(a, b)) and any(x > y for x, y in zip(a, b))


def fronts(objs: list[tuple], viol: list[float]) -> list[list[int]]:
    n = len(objs)
    S = [[] for _ in range(n)]
    cnt = [0] * n
    F = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if dominates(objs[p], objs[q], viol[p], viol[q]):
                S[p].append(q)
            elif dominates(objs[q], objs[p], viol[q], viol[p]):
                cnt[p] += 1
        if cnt[p] == 0:
            F[0].append(p)
    i = 0
    while F[i]:
        nxt = []
        for p in F[i]:
            for q in S[p]:
                cnt[q] -= 1
                if cnt[q] == 0:
                    nxt.append(q)
        i += 1
        F.append(nxt)
    return F[:-1]


def crowding(front: list[int], objs: list[tuple]) -> dict[int, float]:
    d = {i: 0.0 for i in front}
    if len(front) <= 2:
        return {i: math.inf for i in front}
    for m in range(len(objs[front[0]])):
        s = sorted(front, key=lambda i: objs[i][m])
        lo, hi = objs[s[0]][m], objs[s[-1]][m]
        d[s[0]] = d[s[-1]] = math.inf
        if hi == lo:
            continue
        for k in range(1, len(s) - 1):
            d[s[k]] += (objs[s[k + 1]][m] - objs[s[k - 1]][m]) / (hi - lo)
    return d


def select(objs: list[tuple], viol: list[float], k: int) -> tuple[list[int], dict[int, int], dict[int, float]]:
    """Retourne (indices retenus, rang par indice, distance de crowding par indice)."""
    rank, crowd, chosen = {}, {}, []
    for r, f in enumerate(fronts(objs, viol)):
        c = crowding(f, objs)
        for i in f:
            rank[i], crowd[i] = r, c[i]
        if len(chosen) + len(f) <= k:
            chosen += f
        else:
            chosen += sorted(f, key=lambda i: -c[i])[:k - len(chosen)]
            break
    return chosen, rank, crowd


def tournament(rng, idx: list[int], rank: dict, crowd: dict) -> int:
    a, b = rng.sample(idx, 2) if len(idx) > 1 else (idx[0], idx[0])
    if rank[a] != rank[b]:
        return a if rank[a] < rank[b] else b
    return a if crowd[a] >= crowd[b] else b
