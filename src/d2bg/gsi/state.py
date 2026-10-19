"""Parse a Dota 2 Game State Integration payload into a typed snapshot.

While playing, GSI sends only the local player's blocks (``map``, ``player``, ``hero``, ``abilities``,
``items``, ``events``, sometimes ``draft``). When spectating it nests ``player``, ``hero``, ``items`` and
``abilities`` by team and slot (``team2.player0`` ...). Both shapes are handled here, and every field is
optional: the game leaves blocks out depending on the moment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

PHASES = {
    "DOTA_GAMERULES_STATE_INIT": "init",
    "DOTA_GAMERULES_STATE_WAIT_FOR_PLAYERS_TO_LOAD": "loading",
    "DOTA_GAMERULES_STATE_HERO_SELECTION": "hero_selection",
    "DOTA_GAMERULES_STATE_STRATEGY_TIME": "strategy",
    "DOTA_GAMERULES_STATE_TEAM_SHOWCASE": "showcase",
    "DOTA_GAMERULES_STATE_WAIT_FOR_MAP_TO_LOAD": "loading",
    "DOTA_GAMERULES_STATE_PRE_GAME": "pre_game",
    "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS": "in_game",
    "DOTA_GAMERULES_STATE_POST_GAME": "post_game",
    "DOTA_GAMERULES_STATE_DISCONNECT": "disconnect",
    "DOTA_GAMERULES_STATE_CUSTOM_GAME_SETUP": "custom_setup",
}
TEAMS = {"team2": "radiant", "team3": "dire"}
INVENTORY = tuple(f"slot{i}" for i in range(6))
BACKPACK = ("slot6", "slot7", "slot8")
STASH = tuple(f"stash{i}" for i in range(6))


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bool(v: Any) -> bool | None:
    return v if isinstance(v, bool) else None


def _dict(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}


@dataclass
class ItemSlot:
    slot: str
    key: str
    charges: int | None = None
    cooldown: float | None = None
    can_cast: bool | None = None


@dataclass
class AbilityState:
    key: str
    level: int
    can_cast: bool | None
    passive: bool | None
    ultimate: bool | None
    cooldown: float | None


@dataclass
class HeroState:
    id: int | None
    key: str | None
    level: int | None = None
    xp: int | None = None
    alive: bool | None = None
    respawn_seconds: int | None = None
    buyback_cost: int | None = None
    buyback_cooldown: float | None = None
    health: int | None = None
    max_health: int | None = None
    mana: int | None = None
    max_mana: int | None = None
    scepter: bool | None = None
    shard: bool | None = None
    smoked: bool | None = None
    attributes_level: int | None = None
    talents: list[bool] = field(default_factory=list)


@dataclass
class PlayerStats:
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    denies: int = 0
    gold: int = 0
    gold_reliable: int = 0
    gold_unreliable: int = 0
    gpm: int = 0
    xpm: int = 0
    net_worth: int | None = None
    hero_damage: int | None = None
    camps_stacked: int | None = None
    runes_activated: int | None = None
    wards_placed: int | None = None


@dataclass
class OtherPlayer:
    """One of the ten players, only filled in when spectating."""

    team: str
    slot: str
    name: str | None
    account_id: int | None
    hero_id: int | None
    hero_key: str | None
    level: int | None
    alive: bool | None
    stats: PlayerStats
    items: list[ItemSlot]


@dataclass
class DraftState:
    radiant_picks: list[int] = field(default_factory=list)
    dire_picks: list[int] = field(default_factory=list)
    radiant_bans: list[int] = field(default_factory=list)
    dire_bans: list[int] = field(default_factory=list)
    active_team: str | None = None
    time_remaining: float | None = None


@dataclass
class GameEvent:
    type: str
    game_time: float | None
    team: str | None
    data: dict[str, Any]


@dataclass
class GameState:
    received_at: float
    phase: str = "menu"
    raw_state: str | None = None
    match_id: str | None = None
    clock: float | None = None
    game_time: float | None = None
    daytime: bool | None = None
    paused: bool | None = None
    win_team: str | None = None
    radiant_score: int | None = None
    dire_score: int | None = None
    roshan_state: str | None = None
    roshan_state_end: float | None = None
    team: str | None = None
    account_id: int | None = None
    player_name: str | None = None
    activity: str | None = None
    hero: HeroState | None = None
    stats: PlayerStats | None = None
    inventory: list[ItemSlot] = field(default_factory=list)
    backpack: list[ItemSlot] = field(default_factory=list)
    stash: list[ItemSlot] = field(default_factory=list)
    teleport: ItemSlot | None = None
    neutral: ItemSlot | None = None
    abilities: list[AbilityState] = field(default_factory=list)
    draft: DraftState | None = None
    spectating: bool = False
    players: list[OtherPlayer] = field(default_factory=list)
    events: list[GameEvent] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)

    @property
    def owned_items(self) -> list[str]:
        return [i.key for i in [*self.inventory, *self.backpack, *self.stash]]

    @property
    def in_match(self) -> bool:
        return self.phase in ("hero_selection", "strategy", "showcase", "pre_game", "in_game", "post_game")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _item(slot: str, raw: Mapping[str, Any]) -> ItemSlot | None:
    name = raw.get("name")
    if not isinstance(name, str) or name in ("", "empty"):
        return None
    return ItemSlot(
        slot=slot,
        key=name.removeprefix("item_"),
        charges=_int(raw.get("charges")),
        cooldown=_float(raw.get("cooldown")),
        can_cast=_bool(raw.get("can_cast")),
    )


def _items(block: Mapping[str, Any], slots: tuple[str, ...]) -> list[ItemSlot]:
    return [i for s in slots if (i := _item(s, _dict(block.get(s)))) is not None]


def _hero(raw: Mapping[str, Any], hero_ids: Mapping[str, int]) -> HeroState | None:
    if not raw:
        return None
    name = raw.get("name")
    key = name.removeprefix("npc_dota_hero_") if isinstance(name, str) and name else None
    hero_id = _int(raw.get("id"))
    if (hero_id is None or hero_id <= 0) and key:
        hero_id = hero_ids.get(key)
    if hero_id is not None and hero_id <= 0:
        hero_id = None
    return HeroState(
        id=hero_id,
        key=key,
        level=_int(raw.get("level")),
        xp=_int(raw.get("xp")),
        alive=_bool(raw.get("alive")),
        respawn_seconds=_int(raw.get("respawn_seconds")),
        buyback_cost=_int(raw.get("buyback_cost")),
        buyback_cooldown=_float(raw.get("buyback_cooldown")),
        health=_int(raw.get("health")),
        max_health=_int(raw.get("max_health")),
        mana=_int(raw.get("mana")),
        max_mana=_int(raw.get("max_mana")),
        scepter=_bool(raw.get("aghanims_scepter")),
        shard=_bool(raw.get("aghanims_shard")),
        smoked=_bool(raw.get("smoked")),
        attributes_level=_int(raw.get("attributes_level")),
        talents=[bool(raw.get(f"talent_{i}")) for i in range(1, 9) if f"talent_{i}" in raw],
    )


def _stats(raw: Mapping[str, Any]) -> PlayerStats:
    return PlayerStats(
        kills=_int(raw.get("kills")) or 0,
        deaths=_int(raw.get("deaths")) or 0,
        assists=_int(raw.get("assists")) or 0,
        last_hits=_int(raw.get("last_hits")) or 0,
        denies=_int(raw.get("denies")) or 0,
        gold=_int(raw.get("gold")) or 0,
        gold_reliable=_int(raw.get("gold_reliable")) or 0,
        gold_unreliable=_int(raw.get("gold_unreliable")) or 0,
        gpm=_int(raw.get("gpm")) or 0,
        xpm=_int(raw.get("xpm")) or 0,
        net_worth=_int(raw.get("net_worth")),
        hero_damage=_int(raw.get("hero_damage")),
        camps_stacked=_int(raw.get("camps_stacked")),
        runes_activated=_int(raw.get("runes_activated")),
        wards_placed=_int(raw.get("wards_placed")),
    )


def _draft(raw: Mapping[str, Any]) -> DraftState | None:
    if not raw:
        return None
    d = DraftState(
        active_team=TEAMS.get(f"team{raw.get('activeteam')}") if raw.get("activeteam") else None,
        time_remaining=_float(raw.get("activeteam_time_remaining")),
    )
    for team_key, side in TEAMS.items():
        team = _dict(raw.get(team_key))
        for i in range(10):
            pick, ban = _int(team.get(f"pick{i}_id")), _int(team.get(f"ban{i}_id"))
            if pick and pick > 0:
                getattr(d, f"{side}_picks").append(pick)
            if ban and ban > 0:
                getattr(d, f"{side}_bans").append(ban)
    if not (d.radiant_picks or d.dire_picks or d.radiant_bans or d.dire_bans or d.active_team):
        return None
    return d


def _spectated_players(payload: Mapping[str, Any], hero_ids: Mapping[str, int]) -> list[OtherPlayer]:
    players_block, heroes_block, items_block = (
        _dict(payload.get("player")),
        _dict(payload.get("hero")),
        _dict(payload.get("items")),
    )
    out = []
    for team_key, side in TEAMS.items():
        team = _dict(players_block.get(team_key))
        for slot in sorted(team, key=lambda s: _int("".join(c for c in s if c.isdigit())) or 0):
            p = _dict(team.get(slot))
            h = _hero(_dict(_dict(heroes_block.get(team_key)).get(slot)), hero_ids)
            inv = _dict(_dict(items_block.get(team_key)).get(slot))
            out.append(
                OtherPlayer(
                    team=side,
                    slot=slot,
                    name=p.get("name"),
                    account_id=_int(p.get("accountid")),
                    hero_id=h.id if h else None,
                    hero_key=h.key if h else None,
                    level=h.level if h else None,
                    alive=h.alive if h else None,
                    stats=_stats(p),
                    items=_items(inv, INVENTORY + BACKPACK),
                )
            )
    return out


def parse(
    payload: Mapping[str, Any], received_at: float, hero_ids: Mapping[str, int] | None = None
) -> GameState:
    hero_ids = hero_ids or {}
    m = _dict(payload.get("map"))
    player = _dict(payload.get("player"))
    spectating = any(k in player for k in TEAMS)
    raw_state = m.get("game_state") if isinstance(m.get("game_state"), str) else None
    state = GameState(
        received_at=received_at,
        phase=PHASES.get(raw_state or "", "menu" if not m else "unknown"),
        raw_state=raw_state,
        match_id=str(m["matchid"]) if m.get("matchid") not in (None, "", "0") else None,
        clock=_float(m.get("clock_time")),
        game_time=_float(m.get("game_time")),
        daytime=_bool(m.get("daytime")),
        paused=_bool(m.get("paused")),
        win_team=m.get("win_team") if m.get("win_team") not in (None, "none") else None,
        radiant_score=_int(m.get("radiant_score")),
        dire_score=_int(m.get("dire_score")),
        roshan_state=m.get("roshan_state"),
        roshan_state_end=_float(m.get("roshan_state_end_seconds")),
        spectating=spectating,
        draft=_draft(_dict(payload.get("draft"))),
        blocks=sorted(k for k in payload if k not in ("auth", "previously", "added")),
    )
    for e in payload.get("events") or []:
        if isinstance(e, Mapping) and isinstance(e.get("event_type"), str):
            state.events.append(
                GameEvent(
                    type=e["event_type"],
                    game_time=_float(e.get("game_time")),
                    team=e.get("team"),
                    data={k: v for k, v in e.items() if k not in ("event_type", "game_time", "team")},
                )
            )
    if spectating:
        state.players = _spectated_players(payload, hero_ids)
        return state
    state.team = player.get("team_name") if player.get("team_name") in ("radiant", "dire") else None
    state.account_id = _int(player.get("accountid"))
    state.player_name = player.get("name")
    state.activity = player.get("activity")
    state.stats = _stats(player) if player else None
    state.hero = _hero(_dict(payload.get("hero")), hero_ids)
    items = _dict(payload.get("items"))
    state.inventory = _items(items, INVENTORY)
    state.backpack = _items(items, BACKPACK)
    state.stash = _items(items, STASH)
    state.teleport = _item("teleport0", _dict(items.get("teleport0")))
    state.neutral = _item("neutral0", _dict(items.get("neutral0")))
    for key in sorted(_dict(payload.get("abilities")), key=lambda s: _int(s.removeprefix("ability")) or 0):
        a = _dict(_dict(payload.get("abilities")).get(key))
        if isinstance(a.get("name"), str):
            state.abilities.append(
                AbilityState(
                    key=a["name"],
                    level=_int(a.get("level")) or 0,
                    can_cast=_bool(a.get("can_cast")),
                    passive=_bool(a.get("passive")),
                    ultimate=_bool(a.get("ultimate")),
                    cooldown=_float(a.get("cooldown")),
                )
            )
    return state


def unspent_skill_points(state: GameState) -> int | None:
    """Skill points not yet spent: one per level, minus ability levels and attribute bonus levels.

    Since 7.40 talents use their own points, so they are not counted here. Returns None without data.
    """
    if not state.hero or state.hero.level is None or not state.abilities:
        return None
    spent = sum(a.level for a in state.abilities if not a.key.startswith("special_bonus"))
    spent += state.hero.attributes_level or 0
    return max(state.hero.level - spent, 0)
