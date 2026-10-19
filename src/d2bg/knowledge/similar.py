"""Heroes with similar matchup profiles: cosine similarity of their vs rows."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


def _vector(bucket: Mapping[str, Any], hero: int) -> dict[str, float]:
    row = bucket["vs"].get(str(hero), {})
    return {k: float(v) for k, v in row.items() if v is not None}


def cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    keys = set(a) & set(b)
    if len(keys) < 10:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(a[k] ** 2 for k in keys))
    nb = math.sqrt(sum(b[k] ** 2 for k in keys))
    return dot / (na * nb) if na and nb else 0.0


def most_similar(bucket: Mapping[str, Any], hero: int, n: int = 6) -> list[tuple[int, float]]:
    base = _vector(bucket, hero)
    scores = [(int(h), cosine(base, _vector(bucket, int(h)))) for h in bucket["vs"] if int(h) != hero]
    scores.sort(key=lambda t: (-t[1], t[0]))
    return [(h, round(s, 3)) for h, s in scores[:n] if s > 0]


def similar_heroes(
    bucket: Mapping[str, Any], heroes: Iterable[int], exclude: Iterable[int] = (), n: int = 6
) -> list[tuple[int, list[int]]]:
    """Heroes most similar to any of ``heroes``, with which ones they resemble."""
    skip = set(exclude) | set(heroes)
    found: dict[int, tuple[float, list[int]]] = {}
    for h in heroes:
        for other, s in most_similar(bucket, h, 12):
            if other in skip:
                continue
            best, sources = found.get(other, (0.0, []))
            found[other] = (max(best, s), [*sources, h])
    ranked = sorted(found.items(), key=lambda kv: (-len(kv[1][1]), -kv[1][0], kv[0]))
    return [(h, srcs) for h, (_, srcs) in ranked[:n]]
