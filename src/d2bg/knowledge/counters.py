"""Situational items against an enemy lineup, from the rules in ``data/knowledge/counter_items.json``."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from d2bg.knowledge.items import ItemIndex
from d2bg.knowledge.traits import DISABLES, Trait, TraitIndex


@dataclass(frozen=True)
class CounterRule:
    id: str
    trait: str
    min_heroes: int
    items: tuple[str, ...]
    reason: str

    @classmethod
    def load(cls, doc: Mapping[str, Any]) -> list[CounterRule]:
        return [
            cls(r["id"], r["trait"], int(r["min_heroes"]), tuple(r["items"]), r["reason"])
            for r in doc["rules"]
        ]


def _holders(rule: CounterRule, enemies: Iterable[int], traits: TraitIndex) -> list[int]:
    if rule.trait == "disables":
        return [e for e in enemies if any(traits.has(e, t) for t in DISABLES)]
    trait = Trait(rule.trait)
    return [e for e in enemies if traits.has(e, trait)]


def situational_items(
    enemies: Iterable[int],
    traits: TraitIndex,
    rules: Iterable[CounterRule],
    items: ItemIndex,
    hero_name: Any,
    owned: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Rules that fire for this lineup, most enemies covered first.

    Items you already own are marked so the UI can tick them off.
    """
    enemy_list = [int(e) for e in enemies]
    have = set(owned)
    out = []
    for rule in rules:
        holders = _holders(rule, enemy_list, traits)
        if len(holders) < rule.min_heroes:
            continue
        out.append(
            {
                "id": rule.id,
                "reason": rule.reason,
                "heroes": [hero_name(h) for h in holders],
                "items": [
                    {
                        "key": key,
                        "name": items.name(key),
                        "cost": item.cost,
                        "img": item.img,
                        "owned": key in have,
                    }
                    for key in rule.items
                    if (item := items.get(key)) is not None
                ],
            }
        )
    out.sort(key=lambda r: (-len(r["heroes"]), r["id"]))
    return out
