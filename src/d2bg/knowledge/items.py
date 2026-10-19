"""Items: costs, component trees, and how much gold an item still needs given what you own."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Item:
    key: str
    id: int
    name: str
    cost: int
    components: tuple[str, ...]
    img: str | None
    quality: str | None
    tier: int | None  # neutral item tier, if any
    abilities: tuple[Mapping[str, Any], ...]
    attrib: tuple[str, ...]
    cooldown: Any
    notes: str | None

    @property
    def is_neutral(self) -> bool:
        return self.tier is not None

    def summary(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "id": self.id,
            "name": self.name,
            "cost": self.cost,
            "img": self.img,
            "tier": self.tier,
            "components": list(self.components),
        }


def strip_item_prefix(name: str) -> str:
    return name.removeprefix("item_")


class ItemIndex:
    def __init__(self, items_doc: Mapping[str, Any]) -> None:
        self._items: dict[str, Item] = {}
        for key, raw in items_doc.items():
            self._items[key] = Item(
                key=key,
                id=int(raw.get("id") or 0),
                name=str(raw.get("dname") or key),
                cost=int(raw.get("cost") or 0),
                components=tuple(raw.get("components") or ()),
                img=raw.get("img"),
                quality=raw.get("qual"),
                tier=int(raw["tier"]) if raw.get("tier") is not None else None,
                abilities=tuple(raw.get("abilities") or ()),
                attrib=tuple(raw.get("attrib") or ()),
                cooldown=raw.get("cd"),
                notes=raw.get("notes"),
            )
        self._by_id = {i.id: i for i in self._items.values() if i.id}
        self._builds_into: dict[str, list[str]] = {}
        for item in self._items.values():
            for comp in set(item.components):
                self._builds_into.setdefault(comp, []).append(item.key)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and strip_item_prefix(key) in self._items

    def __iter__(self) -> Any:
        return iter(sorted(self._items.values(), key=lambda i: i.name))

    def get(self, key: str) -> Item | None:
        return self._items.get(strip_item_prefix(key))

    def by_id(self, item_id: int) -> Item | None:
        return self._by_id.get(int(item_id))

    def name(self, key: str) -> str:
        item = self.get(key)
        return item.name if item else strip_item_prefix(key).replace("_", " ").title()

    def builds_into(self, key: str) -> list[str]:
        return sorted(self._builds_into.get(strip_item_prefix(key), []))

    def cost(self, key: str) -> int:
        """Gold cost, 0 for an unknown key."""
        item = self.get(key)
        return item.cost if item else 0

    def recipe_cost(self, key: str) -> int:
        item = self.get(key)
        if not item or not item.components:
            return 0
        return max(item.cost - sum(self.cost(c) for c in item.components), 0)

    def remaining_cost(self, target: str, owned: Iterable[str]) -> int:
        """Gold still needed for ``target`` when owned items count towards its components.

        Owned items are used at most once, the whole item before its parts.
        """
        pool = Counter(strip_item_prefix(o) for o in owned)
        return self._remaining(strip_item_prefix(target), pool, depth=0)

    def _remaining(self, key: str, pool: Counter[str], depth: int) -> int:
        if pool[key] > 0:
            pool[key] -= 1
            return 0
        item = self._items.get(key)
        if item is None:
            return 0
        if not item.components or depth > 6:
            return item.cost
        return self.recipe_cost(key) + sum(self._remaining(c, pool, depth + 1) for c in item.components)

    def owned_progress(self, target: str, owned: Iterable[str]) -> dict[str, Any]:
        item = self.get(target)
        total = item.cost if item else 0
        remaining = self.remaining_cost(target, owned)
        return {
            "item": strip_item_prefix(target),
            "name": self.name(target),
            "cost": total,
            "remaining": remaining,
            "progress": round(1 - remaining / total, 3) if total else 1.0,
        }
