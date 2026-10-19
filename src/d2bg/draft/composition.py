"""What a team brings and what it lacks, from derived traits and listed roles."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from d2bg.draft.advisor import _max_role_assignment
from d2bg.knowledge.heroes import Hero
from d2bg.knowledge.traits import DISABLES, LABELS, Trait, TraitIndex

ROLES = ("Carry", "Support", "Nuker", "Disabler", "Initiator", "Durable", "Escape", "Pusher")


def team_report(
    heroes: Sequence[Hero],
    traits: TraitIndex,
    positions: Mapping[int, set[int]] | None = None,
    name: Callable[[int], str] | None = None,
) -> dict[str, Any]:
    trait_heroes: dict[str, list[str]] = {}
    for h in heroes:
        for t in traits.of(h.id):
            trait_heroes.setdefault(t.value, []).append(h.name)
    roles = Counter(r for h in heroes for r in h.roles)
    attack = Counter(h.attack_type for h in heroes)
    magic = len(trait_heroes.get(Trait.MAGIC_DAMAGE.value, []))
    physical = len(trait_heroes.get(Trait.PHYSICAL_DAMAGE.value, []))
    hard_disable = [h.name for h in heroes if traits.has(h.id, Trait.STUN) or traits.has(h.id, Trait.HEX)]
    disablers = [h.name for h in heroes if any(traits.has(h.id, t) for t in DISABLES)]

    warnings: list[str] = []
    n = len(heroes)
    if n >= 3 and not hard_disable:
        warnings.append("No stun or hex")
    if n >= 3 and roles["Initiator"] == 0:
        warnings.append("No listed initiator")
    if n >= 4 and roles["Durable"] == 0:
        warnings.append("No durable frontline")
    if n >= 4 and magic == 0:
        warnings.append("Almost no magic damage: enemies can stack armor")
    if n >= 4 and physical == 0:
        warnings.append("No right-click damage dealer")
    if n >= 4 and attack["Melee"] >= 4:
        warnings.append(f"{attack['Melee']} melee heroes")
    if n >= 4 and roles["Pusher"] == 0:
        warnings.append("Little tower pushing")
    if n == 5 and roles["Support"] < 2:
        warnings.append("Fewer than two supports")
    covered: list[int] = []
    if positions is not None and heroes:
        ids = [str(h.id) for h in heroes]
        roles_map = {str(h.id): positions.get(h.id, set()) for h in heroes}
        if n == 5 and _max_role_assignment(ids, roles_map) < 5:
            warnings.append("No way to fill all five positions with these heroes")
        covered = sorted({p for h in heroes for p in positions.get(h.id, set())})
    return {
        "heroes": [h.id for h in heroes],
        "traits": {t: {"label": LABELS[Trait(t)], "heroes": hs} for t, hs in sorted(trait_heroes.items())},
        "roles": {r: roles[r] for r in ROLES},
        "melee": attack["Melee"],
        "ranged": attack["Ranged"],
        "damage": {
            "magic": magic,
            "physical": physical,
            "pure": len(trait_heroes.get(Trait.PURE_DAMAGE.value, [])),
        },
        "disablers": disablers,
        "positions_covered": covered,
        "warnings": warnings,
    }
