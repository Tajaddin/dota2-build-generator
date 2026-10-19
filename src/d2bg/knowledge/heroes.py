"""Heroes and their abilities, with search that understands community shorthand ("am", "qop", "wr")."""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass(frozen=True)
class Talent:
    key: str
    level: int  # 1-4, i.e. hero levels 10, 15, 20, 25
    name: str


@dataclass(frozen=True)
class Ability:
    key: str
    name: str
    desc: str
    behavior: tuple[str, ...]
    dmg_type: str | None
    bkb_pierce: bool
    target_team: tuple[str, ...]
    cooldown: Any
    mana: Any
    img: str | None
    attrib: tuple[tuple[str, str, Any], ...]  # (header, key, value)

    @property
    def is_passive(self) -> bool:
        return "Passive" in self.behavior

    def text(self) -> str:
        parts = [self.name, self.desc] + [f"{h} {k}" for h, k, _ in self.attrib]
        return " ".join(p for p in parts if p).lower()

    @classmethod
    def from_doc(cls, key: str, raw: Mapping[str, Any]) -> Ability:
        def tup(value: Any) -> tuple[str, ...]:
            if value is None:
                return ()
            if isinstance(value, str):
                return (value,)
            return tuple(str(v) for v in value)

        return cls(
            key=key,
            name=str(raw.get("dname") or key),
            desc=str(raw.get("desc") or ""),
            behavior=tup(raw.get("behavior")),
            dmg_type=raw.get("dmg_type"),
            bkb_pierce=str(raw.get("bkbpierce", "")).lower() == "yes",
            target_team=tup(raw.get("target_team")),
            cooldown=raw.get("cd"),
            mana=raw.get("mc"),
            img=raw.get("img"),
            attrib=tuple(
                (str(a.get("header") or ""), str(a.get("key") or ""), a.get("value"))
                for a in raw.get("attrib", []) or []
            ),
        )


@dataclass(frozen=True)
class Hero:
    id: int
    key: str
    npc: str
    name: str
    primary_attr: str
    attack_type: str
    roles: tuple[str, ...]
    img: str | None
    icon: str | None
    stats: Mapping[str, Any]
    abilities: tuple[Ability, ...]
    talents: tuple[Talent, ...]
    scepter: Mapping[str, Any] | None
    shard: Mapping[str, Any] | None
    aliases: tuple[str, ...] = field(default=())

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "primary_attr": self.primary_attr,
            "attack_type": self.attack_type,
            "roles": list(self.roles),
            "img": self.img,
            "icon": self.icon,
            "aliases": list(self.aliases),
        }


class HeroIndex:
    def __init__(
        self,
        heroes_doc: Mapping[str, Any],
        abilities_doc: Mapping[str, Any],
        aliases: Mapping[str, Iterable[str]],
    ) -> None:
        self._by_id: dict[int, Hero] = {}
        self._by_key: dict[str, Hero] = {}
        self._alias: dict[str, int] = {}
        for raw in heroes_doc["heroes"]:
            abilities = tuple(
                Ability.from_doc(k, abilities_doc[k]) for k in raw["abilities"] if k in abilities_doc
            )
            talents = tuple(
                Talent(
                    t["key"], int(t["level"]), str(abilities_doc.get(t["key"], {}).get("dname") or t["key"])
                )
                for t in raw["talents"]
            )
            hero = Hero(
                id=int(raw["id"]),
                key=raw["key"],
                npc=raw["npc"],
                name=raw["name"],
                primary_attr=raw.get("primary_attr") or "all",
                attack_type=raw.get("attack_type") or "",
                roles=tuple(raw.get("roles") or ()),
                img=raw.get("img"),
                icon=raw.get("icon"),
                stats=raw.get("stats") or {},
                abilities=abilities,
                talents=talents,
                scepter=raw.get("scepter"),
                shard=raw.get("shard"),
                aliases=tuple(aliases.get(raw["key"], ())),
            )
            self._by_id[hero.id] = hero
            self._by_key[hero.key] = hero
            for a in hero.aliases:
                self._alias[norm(a)] = hero.id

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Any:
        return iter(sorted(self._by_id.values(), key=lambda h: h.name))

    def ids(self) -> list[int]:
        return sorted(self._by_id)

    def get(self, ref: int | str) -> Hero | None:
        """By numeric ID, key ("antimage"), npc name, localized name or alias."""
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            return self._by_id.get(int(ref))
        text = str(ref).removeprefix("npc_dota_hero_")
        if text in self._by_key:
            return self._by_key[text]
        n = norm(text)
        if n in self._alias:
            return self._by_id[self._alias[n]]
        for hero in self._by_id.values():
            if norm(hero.name) == n or norm(hero.key) == n:
                return hero
        return None

    def require(self, ref: int | str) -> Hero:
        hero = self.get(ref)
        if hero is None:
            raise KeyError(f"unknown hero {ref!r}")
        return hero

    def name(self, hero_id: int) -> str:
        hero = self._by_id.get(int(hero_id))
        return hero.name if hero else f"Hero {hero_id}"

    def search(self, query: str, limit: int = 10) -> list[Hero]:
        """Ranked matches: exact and alias first, then prefixes, initials, then fuzzy."""
        q = norm(query)
        if not q:
            return []
        scored: dict[int, float] = {}

        def bump(hero_id: int, score: float) -> None:
            scored[hero_id] = max(scored.get(hero_id, 0.0), score)

        if q in self._alias:
            bump(self._alias[q], 100)
        for hero in self._by_id.values():
            name, key = norm(hero.name), norm(hero.key)
            words = [norm(w) for w in re.split(r"[\s\-']+", hero.name) if w]
            initials = "".join(w[0] for w in words if w)
            if q in (name, key, str(hero.id)):
                bump(hero.id, 100)
            elif name.startswith(q) or key.startswith(q):
                bump(hero.id, 80 + len(q) / max(len(name), 1))
            elif any(w.startswith(q) for w in words):
                bump(hero.id, 70)
            elif len(q) >= 2 and initials.startswith(q):
                bump(hero.id, 60)
            elif q in name:
                bump(hero.id, 50)
            else:
                ratio = difflib.SequenceMatcher(None, q, name[: max(len(q) + 2, 4)]).ratio()
                full = difflib.SequenceMatcher(None, q, name).ratio()
                best = max(ratio, full)
                if best >= 0.75 and len(q) >= 3:
                    bump(hero.id, 40 * best)
            for alias in hero.aliases:
                if norm(alias).startswith(q) and len(q) >= 2:
                    bump(hero.id, 65)
        ranked = sorted(scored.items(), key=lambda kv: (-kv[1], self._by_id[kv[0]].name))
        return [self._by_id[h] for h, _ in ranked[:limit]]

    def parse_list(self, text: str) -> tuple[list[Hero], list[str]]:
        """Heroes from a comma, newline or slash separated list; unknown names are returned too."""
        found, unknown = [], []
        for raw in re.split(r"[,\n/;|]+", text):
            token = raw.strip()
            if not token:
                continue
            hero = self.get(token) or next(iter(self.search(token, 1)), None)
            if hero:
                found.append(hero)
            else:
                unknown.append(token)
        return found, unknown
