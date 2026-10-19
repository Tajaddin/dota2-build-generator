"""Hero traits derived from public ability data, with the abilities that justify each one.

The rules read each visible ability's name, description and attribute headers (from dotaconstants).
They are heuristics, so every trait carries its evidence, and ``data/knowledge/trait_overrides.json``
can add or remove a trait for a hero after review. Hidden abilities (Aghanim's or Shard upgrades,
sub-casts) are ignored so that a trait means "the hero has this from the start".
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any

from d2bg.knowledge.heroes import Ability, Hero


class Trait(StrEnum):
    STUN = "stun"
    SILENCE = "silence"
    HEX = "hex"
    ROOT = "root"
    INVISIBILITY = "invisibility"
    ILLUSIONS = "illusions"
    SUMMONS = "summons"
    HEAL = "heal"
    SAVE = "save"
    EVASION = "evasion"
    BREAK = "break"
    PASSIVES = "passives"
    MAGIC_DAMAGE = "magic_damage"
    PHYSICAL_DAMAGE = "physical_damage"
    PURE_DAMAGE = "pure_damage"
    BKB_PIERCE = "bkb_pierce"
    MOBILITY = "mobility"
    GLOBAL = "global"
    SLOW = "slow"
    ARMOR_REDUCTION = "armor_reduction"
    MANA_BURN = "mana_burn"
    LIFESTEAL = "lifesteal"
    TAUNT = "taunt"


LABELS: dict[Trait, str] = {
    Trait.STUN: "Stun",
    Trait.SILENCE: "Silence",
    Trait.HEX: "Hex",
    Trait.ROOT: "Root",
    Trait.INVISIBILITY: "Invisibility",
    Trait.ILLUSIONS: "Illusions",
    Trait.SUMMONS: "Summons",
    Trait.HEAL: "Heals allies",
    Trait.SAVE: "Saves allies",
    Trait.EVASION: "Evasion",
    Trait.BREAK: "Applies Break",
    Trait.PASSIVES: "Relies on passives",
    Trait.MAGIC_DAMAGE: "Magic damage",
    Trait.PHYSICAL_DAMAGE: "Physical damage",
    Trait.PURE_DAMAGE: "Pure damage",
    Trait.BKB_PIERCE: "Pierces spell immunity",
    Trait.MOBILITY: "Mobility",
    Trait.GLOBAL: "Global presence",
    Trait.SLOW: "Slow",
    Trait.ARMOR_REDUCTION: "Armor reduction",
    Trait.MANA_BURN: "Mana burn",
    Trait.LIFESTEAL: "Lifesteal",
    Trait.TAUNT: "Taunt",
}

DISABLES = (Trait.STUN, Trait.HEX, Trait.SILENCE, Trait.ROOT, Trait.TAUNT)

_ALLY = r"all(?:y|ies|ied)|friendly|teammate"
PATTERNS: dict[Trait, re.Pattern[str]] = {
    Trait.STUN: re.compile(r"\bstun"),
    Trait.HEX: re.compile(r"\bhex(?:es|ed)?\b|harmless (?:beast|critter)"),
    Trait.ROOT: re.compile(
        r"\broot(?:s|ed|ing)?\b|ensnar|entangl|in place|(?:prevent|prohibit)\w* (?:them from )?mov|cannot move"
    ),
    Trait.INVISIBILITY: re.compile(
        r"\b(?:becom\w*|turns?|render\w*|grants?)\b[^.]{0,40}invisib|moves invisibly|invisible until"
        r"|stationary[^.]{0,40}invisible|out of (?:visibility|sight)|fades? into the shadows"
    ),
    Trait.ILLUSIONS: re.compile(
        r"(?:creat|summon|conjur|spawn|fractur|split|send)\w*[^.]{0,40}"
        r"(?:illusion|illusory|images?\b|copies|nemesis)"
    ),
    Trait.SUMMONS: re.compile(
        r"summon\w*[^.]{0,40}(?:creature|wolves|wolf|golem|treant|eidolon|zombie|spiderling|"
        r"skeleton|ward|familiar|boar|hawk|bear|clone|serpent|minion|phantom|imp|beetle|lizard|undead)"
        r"|\bspiderlings?\b|\beidolons?\b|\bzombies?\b|\bskeletons?\b|\bwards?\b|\btreants?\b"
        r"|\bfamiliars?\b|\bwolves\b|\bgolems?\b|units? summoned|summoned units?"
    ),
    Trait.EVASION: re.compile(r"\bevasion\b|\bevade\b"),
    Trait.BREAK: re.compile(r"appl\w* break|\bbreak (?:effect|duration)|disabl\w* (?:their |all )?passive"),
    Trait.MOBILITY: re.compile(
        r"\b(?:blink|teleport|leap|jump|dash|charg|rush|surge|swap|fly|flies|reappear|travel|warp)\w*"
    ),
    Trait.GLOBAL: re.compile(r"\bglobal\b|anywhere on the map|any point on the map|no matter where"),
    Trait.SLOW: re.compile(r"\bslow"),
    Trait.ARMOR_REDUCTION: re.compile(
        r"armor (?:loss|reduction)|reduc\w*[^.]{0,20}armor|minus armor|negative armor"
    ),
    Trait.MANA_BURN: re.compile(r"mana (?:burn|break|void)|burns?[^.]{0,20}mana|drain\w* mana|taking mana"),
    Trait.LIFESTEAL: re.compile(r"lifesteal|life steal"),
}
_HEAL = re.compile(
    rf"heal\w*[^.]{{0,40}}(?:{_ALLY})|(?:{_ALLY})[^.]{{0,40}}heal|restores?[^.]{{0,30}}health[^.]{{0,30}}(?:{_ALLY})"
)
_SAVE = re.compile(
    r"cannot die|invulnerab|banish|untargetable|delay\w* (?:any |all )?(?:healing or )?damage"
    r"|absorbs?[^.]{0,30}damage|freez\w* them solid|immune to (?:physical|magic|all)"
)
_SILENCE = re.compile(r"\bsilenc|prevent\w* (?:them )?from casting|cannot cast spells")
_TAUNT = re.compile(r"\btaunt|forc\w* (?:them )?to attack|forced to attack")
# Invoker, Doom and Rubick have empty passive slots that other abilities replace; they are not passives.
_PLACEHOLDER = re.compile(r"replace this slot|slot will be replaced")


def _visible(hero: Hero) -> list[Ability]:
    return [
        a for a in hero.abilities if "Hidden" not in a.behavior and not _PLACEHOLDER.search(a.desc.lower())
    ]


def _affects_allies(a: Ability) -> bool:
    return any(t in ("Friendly", "Both") for t in a.target_team) or bool(re.search(_ALLY, a.desc.lower()))


def derive(hero: Hero) -> dict[Trait, list[str]]:
    """Trait -> names of the abilities that show it."""
    found: dict[Trait, list[str]] = {}

    def add(trait: Trait, ability: Ability) -> None:
        names = found.setdefault(trait, [])
        if ability.name not in names:
            names.append(ability.name)

    visible = _visible(hero)
    for a in visible:
        text = a.text()
        for trait, pattern in PATTERNS.items():
            if not pattern.search(text):
                continue
            if trait is Trait.SUMMONS and PATTERNS[Trait.ILLUSIONS].search(text):
                continue  # illusion copies are counted as illusions, not summons
            if trait in (Trait.STUN, Trait.HEX, Trait.ROOT) and a.is_passive and "Enemy" not in a.target_team:
                continue  # e.g. "deals more damage to stunned targets" on a passive
            add(trait, a)
        if _SILENCE.search(text) and (not a.is_passive or any("SILENCE" in h for h, _, _ in a.attrib)):
            add(Trait.SILENCE, a)
        if _TAUNT.search(text) and not a.is_passive:
            add(Trait.TAUNT, a)
        if _HEAL.search(text) and _affects_allies(a):
            add(Trait.HEAL, a)
        if (
            _SAVE.search(text)
            and any(t in ("Friendly", "Both") for t in a.target_team)
            and not PATTERNS[Trait.SUMMONS].search(text)
        ):
            add(Trait.SAVE, a)
        if a.bkb_pierce and "Enemy" in a.target_team and not a.is_passive:
            add(Trait.BKB_PIERCE, a)
        if a.dmg_type == "Pure" and not a.is_passive:
            add(Trait.PURE_DAMAGE, a)

    magical = [a for a in visible if a.dmg_type == "Magical" and not a.is_passive]
    physical = [a for a in visible if a.dmg_type == "Physical"]
    if len(magical) >= 3 or (len(magical) >= 2 and "Nuker" in hero.roles):
        for a in magical:
            add(Trait.MAGIC_DAMAGE, a)
    if "Carry" in hero.roles and hero.primary_attr in ("agi", "str", "all"):
        found.setdefault(Trait.PHYSICAL_DAMAGE, []).append("Right-click carry")
    elif len(physical) >= 2:
        for a in physical:
            add(Trait.PHYSICAL_DAMAGE, a)
    passives = [a for a in visible if a.is_passive]
    if len(passives) >= 2:
        for a in passives:
            add(Trait.PASSIVES, a)
    return found


def apply_overrides(
    hero: Hero, traits: dict[Trait, list[str]], overrides: Mapping[str, Any]
) -> dict[Trait, list[str]]:
    rule = overrides.get(hero.key) or {}
    out = dict(traits)
    for t in rule.get("remove", []):
        out.pop(Trait(t), None)
    for t in rule.get("add", []):
        out.setdefault(Trait(t), []).append("reviewed")
    return out


class TraitIndex:
    def __init__(self, heroes: Iterable[Hero], overrides: Mapping[str, Any]) -> None:
        self._traits = {h.id: apply_overrides(h, derive(h), overrides) for h in heroes}

    def of(self, hero_id: int) -> dict[Trait, list[str]]:
        return self._traits.get(int(hero_id), {})

    def has(self, hero_id: int, trait: Trait) -> bool:
        return trait in self.of(hero_id)

    def disable_count(self, hero_id: int) -> int:
        return sum(1 for t in DISABLES if t in self.of(hero_id))

    def view(self, hero_id: int) -> list[dict[str, Any]]:
        return [
            {"trait": t.value, "label": LABELS[t], "evidence": ev}
            for t, ev in sorted(self.of(hero_id).items(), key=lambda kv: kv[0].value)
        ]
