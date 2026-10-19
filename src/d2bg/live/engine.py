"""The live engine: turns each GSI payload into the state the Live page shows.

It keeps per-match memory (timer events, alerts, a gold and XP series) and a version counter that the
Server-Sent Events stream watches. Everything here is information for the player; nothing is sent back
to the game.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from d2bg.builds.benchmarks import compare, percentile_of, value_at
from d2bg.builds.guide import build_order, next_items
from d2bg.context import AppContext
from d2bg.draft.advisor import counters
from d2bg.gsi.state import GameState, parse, unspent_skill_points
from d2bg.knowledge.counters import situational_items
from d2bg.knowledge.timers import TimerState, fmt, upcoming

NOTABLE_ITEMS = frozenset(
    {
        "black_king_bar",
        "blink",
        "gem",
        "sphere",
        "aeon_disk",
        "ghost",
        "glimmer_cape",
        "force_staff",
        "manta",
        "satanic",
        "butterfly",
        "refresher",
        "ultimate_scepter",
        "sheepstick",
        "silver_edge",
        "monkey_king_bar",
        "nullifier",
        "lotus_orb",
        "blade_mail",
        "abyssal_blade",
        "bloodthorn",
        "radiance",
        "heart",
        "skadi",
        "assault",
        "shivas_guard",
        "travel_boots",
        "travel_boots_2",
        "invis_sword",
    }
)
PLAYER_NOTE = (
    "Dota does not send a player the other picks during the draft (its GSI draft block stays empty), so "
    "add allies and enemies by hand until the game loads. Your hero, your team and the bans fill in by "
    "themselves; after loading, allies fill in from the minimap, and enemies as soon as you see them."
)
SPECTATOR_NOTE = "Spectating: Dota sends the whole draft, so both teams fill in by themselves."
SERIES_EVERY = 30.0
MAX_ALERTS = 60
STALE_AFTER = 30.0


@dataclass
class Alert:
    id: int
    clock: float | None
    at: float
    kind: str
    text: str
    speak: str | None = None
    severity: str = "info"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "clock": self.clock,
            "clock_text": fmt(self.clock) if self.clock is not None else None,
            "at": self.at,
            "kind": self.kind,
            "text": self.text,
            "speak": self.speak,
            "severity": self.severity,
        }


class LiveEngine:
    def __init__(
        self,
        ctx: AppContext,
        clock: Callable[[], float] = time.time,
        on_post_game: Callable[[str], None] | None = None,
        on_account: Callable[[int], None] | None = None,
        on_payload: Callable[[Mapping[str, Any], str], None] | None = None,
    ) -> None:
        self.ctx = ctx
        self._clock = clock
        self._lock = threading.RLock()
        self.on_post_game = on_post_game
        self.on_account = on_account
        self.on_payload = on_payload
        hero_ids = {h.key: h.id for h in ctx.data.heroes}
        self._hero_ids = hero_ids
        self.version = 0
        self.packets = 0
        self.source = "none"
        self.blocks_seen: set[str] = set()
        self.last_packet_at: float | None = None
        self._reset_match(None)
        self._cached: tuple[int, dict[str, Any]] | None = None

    # ── per-match memory ───────────────────────────────────────────

    def _reset_match(self, match_id: str | None) -> None:
        self.match_id = match_id
        self.state: GameState | None = None
        self.timers = TimerState()
        self.alerts: deque[Alert] = deque(maxlen=MAX_ALERTS)
        self._alert_seq = getattr(self, "_alert_seq", 0)
        self._fired: set[str] = set()
        self.series: list[dict[str, Any]] = []
        self.event_log: list[dict[str, Any]] = []
        self._seen_events: set[tuple[str, str | None, int | None, float | None]] = set()
        self._enemy_items: dict[tuple[str, str], set[str]] = {}
        self._post_game_sent = False
        self.draft_seen: dict[str, list[int]] = {
            "radiant": [],
            "dire": [],
            "radiant_bans": [],
            "dire_bans": [],
            "bans": [],  # from the chat's ban announcements, which do not say which team banned
        }
        self.own_hero: int | None = None
        self.draft_sources: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._reset_match(None)
            self.version += 1

    def _alert(
        self, key: str, kind: str, text: str, speak: str | None = None, severity: str = "info"
    ) -> None:
        if key in self._fired:
            return
        self._fired.add(key)
        self._alert_seq += 1
        clock = self.state.clock if self.state else None
        self.alerts.appendleft(Alert(self._alert_seq, clock, self._clock(), kind, text, speak, severity))

    # ── input ──────────────────────────────────────────────────────

    def ingest(self, payload: Mapping[str, Any], source: str = "game") -> GameState:
        with self._lock:
            now = self._clock()
            state = parse(payload, now, self._hero_ids)
            if state.match_id and state.match_id != self.match_id:
                self._reset_match(state.match_id)
            self.packets += 1
            self.source = source
            self.last_packet_at = now
            self.blocks_seen.update(state.blocks)
            prev = self.state
            self.state = state
            self._track(prev, state)
            self.version += 1
            # Build now, not on first read, so alerts fire even with no browser open.
            self._cached = (self.version, self._build())
        if self.on_payload is not None:
            self.on_payload(payload, source)
        if state.account_id and self.on_account is not None and source == "game":
            self.on_account(state.account_id)
        return state

    def _track(self, prev: GameState | None, s: GameState) -> None:
        clock = s.clock
        # Day and night: remember the moment the flag flips.
        if (
            prev
            and prev.daytime is not None
            and s.daytime is not None
            and prev.daytime != s.daytime
            and clock is not None
        ):
            self.timers.day_flip_at = clock
        self.timers.daytime = s.daytime
        # Game events.
        for e in s.events:
            # Dota repeats recent events in every payload; several announcements can share a timestamp.
            key = (e.type, e.subtype, e.value, e.game_time)
            if key in self._seen_events:
                continue
            self._seen_events.add(key)
            t = e.game_time if e.game_time is not None else clock
            if e.subtype == "CHAT_MESSAGE_HERO_BANNED" and e.value and e.value not in self.draft_seen["bans"]:
                self.draft_seen["bans"].append(e.value)
                self.draft_sources["bans"] = "ban announcements in the game chat"
            if e.type == "generic_event":
                continue  # chat announcements (bans, purchases, kills) stay out of the event log
            self.event_log.append(
                {"type": e.type, "clock": t, "clock_text": fmt(t) if t is not None else None, "team": e.team}
            )
            if e.type == "roshan_killed" and t is not None:
                self.timers.roshan_killed_at = t
                self._alert(f"rosh:{t}", "event", f"Roshan killed at {fmt(t)}", "Roshan killed")
            elif e.type == "aegis_picked_up" and t is not None:
                self.timers.aegis_picked_at = t
            elif e.type == "aegis_denied" and t is not None:
                self.timers.aegis_picked_at = None
        # Draft (spectator, or whenever the game sends it).
        if s.draft:
            for side in ("radiant", "dire"):
                for h in getattr(s.draft, f"{side}_picks"):
                    if h not in self.draft_seen[side]:
                        self.draft_seen[side].append(h)
                for h in getattr(s.draft, f"{side}_bans"):
                    if h not in self.draft_seen[f"{side}_bans"]:
                        self.draft_seen[f"{side}_bans"].append(h)
        if s.spectating:
            for p in s.players:
                if p.hero_id and p.hero_id not in self.draft_seen[p.team]:
                    self.draft_seen[p.team].append(p.hero_id)
                have = {i.key for i in p.items}
                before = self._enemy_items.get((p.team, p.slot), set())
                for item_key in sorted((have - before) & NOTABLE_ITEMS):
                    if before or (clock or 0) > 60:
                        who = self.ctx.data.heroes.name(p.hero_id) if p.hero_id else p.slot
                        name = self.ctx.data.items.name(item_key)
                        self._alert(
                            f"item:{p.team}:{p.slot}:{item_key}",
                            "item",
                            f"{who} ({p.team}) has {name}",
                            f"{who} bought {name}",
                        )
                self._enemy_items[(p.team, p.slot)] = have
        else:
            self._track_player_draft(s)
        # Series for the chart.
        if (
            clock is not None
            and clock >= 0
            and s.stats
            and (not self.series or clock - self.series[-1]["t"] >= SERIES_EVERY)
        ):
            self.series.append(
                {
                    "t": clock,
                    "gold": s.stats.gold,
                    "net_worth": self._net_worth(s),
                    "last_hits": s.stats.last_hits,
                    "level": s.hero.level if s.hero else None,
                    "gpm": s.stats.gpm,
                    "xpm": s.stats.xpm,
                }
            )
        # Post-game.
        if s.phase == "post_game" and s.match_id and not self._post_game_sent:
            self._post_game_sent = True
            self._alert(f"end:{s.match_id}", "event", "Match over. The review opens once OpenDota has it.")
            if self.on_post_game is not None and self.source == "game":
                self.on_post_game(s.match_id)

    def _track_player_draft(self, s: GameState) -> None:
        """What a player's GSI tells about the draft (checked against his recorded ranked games).

        - his own hero and team: the ``hero`` and ``player`` blocks, as soon as he picks;
        - allies: the minimap after loading, drawn as ``minimap_herocircle`` with his team number;
        - enemies: the minimap after loading, ``minimap_enemyicon``, once he has seen them.
        During hero selection the minimap also lists draft-screen models with no team, so it is only
        read from pre-game on. Dota sends a player no ``draft`` block content at all.
        """
        if s.hero and s.hero.id:
            if self.own_hero != s.hero.id and self.own_hero is not None:
                for side in ("radiant", "dire"):  # a repick or swap replaces his old hero
                    if self.own_hero in self.draft_seen[side]:
                        self.draft_seen[side].remove(self.own_hero)
            self.own_hero = s.hero.id
            self.draft_sources["you"] = "your hero and team from the game"
        if s.phase not in ("pre_game", "in_game", "post_game") or s.team is None:
            return
        mine = 2 if s.team == "radiant" else 3
        their_side = "dire" if s.team == "radiant" else "radiant"
        for unit in s.minimap:
            if not unit.hero_id or unit.hero_id == self.own_hero:
                continue
            if unit.team == mine and unit.image.startswith("minimap_herocircle"):
                side = s.team
                self.draft_sources["allies"] = "allies from the minimap after loading"
            elif unit.team is not None and unit.team != mine and unit.image == "minimap_enemyicon":
                side = their_side
                self.draft_sources["enemies"] = "enemies from the minimap once you see them"
            else:
                continue
            if unit.hero_id not in self.draft_seen[side]:
                self.draft_seen[side].append(unit.hero_id)

    # ── actions from the UI ────────────────────────────────────────

    def mark(self, what: str, clock: float | None = None) -> None:
        with self._lock:
            t = (
                clock
                if clock is not None
                else (self.state.clock if self.state and self.state.clock is not None else 0.0)
            )
            if what == "roshan":
                self.timers.roshan_killed_at = t
            elif what == "aegis":
                self.timers.aegis_picked_at = t
            elif what == "tormentor":
                self.timers.tormentor_killed_at = t
            elif what == "clear_roshan":
                self.timers.roshan_killed_at = None
                self.timers.aegis_picked_at = None
            else:
                raise ValueError(f"unknown mark {what!r}")
            self.event_log.append({"type": f"marked_{what}", "clock": t, "clock_text": fmt(t), "team": None})
            self.version += 1
            self._cached = (self.version, self._build())

    # ── output ─────────────────────────────────────────────────────

    def _net_worth(self, s: GameState) -> int | None:
        if s.stats and s.stats.net_worth:
            return s.stats.net_worth
        if not s.stats:
            return None
        items = self.ctx.data.items
        return s.stats.gold + sum(items.cost(k) for k in s.owned_items)

    def connection(self) -> dict[str, Any]:
        age = None if self.last_packet_at is None else round(self._clock() - self.last_packet_at, 1)
        return {
            "packets": self.packets,
            "last_packet_age": age,
            "connected": age is not None and age < STALE_AFTER,
            "source": self.source,
            "blocks": sorted(self.blocks_seen),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._cached and self._cached[0] == self.version:
                return {**self._cached[1], "connection": self.connection()}
            snap = self._build()
            self._cached = (self.version, snap)
            return {**snap, "connection": self.connection()}

    def _build(self) -> dict[str, Any]:
        s = self.state
        ctx = self.ctx
        settings = ctx.settings.get()
        base: dict[str, Any] = {
            "version": self.version,
            "match_id": self.match_id,
            "demo": self.source == "demo",
            "timer_patch": ctx.timer_patch,
        }
        if s is None:
            return {**base, "phase": "waiting"}
        clock = s.clock
        out: dict[str, Any] = {
            **base,
            "phase": s.phase,
            "clock": clock,
            "clock_text": fmt(clock) if clock is not None else None,
            "daytime": s.daytime,
            "paused": s.paused,
            "team": s.team,
            "spectating": s.spectating,
            "score": {"radiant": s.radiant_score, "dire": s.dire_score},
            "win_team": s.win_team,
        }
        # Timers and their alerts.
        timer_views = (
            upcoming(ctx.timer_rules, clock, self.timers, settings.timers.enabled)
            if clock is not None
            else []
        )
        lead_override = settings.timers.lead_seconds
        for v in timer_views:
            if v.seconds_left is None or v.at is None:
                continue
            lead = max(v.lead, lead_override) if v.id in ("roshan", "tormentor") else v.lead
            if 0 < v.seconds_left <= lead and s.phase in ("pre_game", "in_game"):
                self._alert(
                    f"timer:{v.id}:{v.at}",
                    "timer",
                    f"{v.label}: {v.detail}",
                    f"{v.label} in {int(v.seconds_left)} seconds",
                )
        out["timers"] = [v.as_dict() for v in timer_views]

        hero = ctx.data.heroes.get(s.hero.id) if s.hero and s.hero.id else None
        if hero and s.hero and s.stats is not None:
            out["hero"] = {
                **hero.summary(),
                "level": s.hero.level,
                "alive": s.hero.alive,
                "respawn_seconds": s.hero.respawn_seconds,
                "health": s.hero.health,
                "max_health": s.hero.max_health,
                "mana": s.hero.mana,
                "max_mana": s.hero.max_mana,
                "scepter": s.hero.scepter,
                "shard": s.hero.shard,
            }
            st = s.stats
            team_kills = (s.radiant_score if s.team == "radiant" else s.dire_score) or 0
            nw = self._net_worth(s)
            out["stats"] = {
                "kills": st.kills,
                "deaths": st.deaths,
                "assists": st.assists,
                "last_hits": st.last_hits,
                "denies": st.denies,
                "gold": st.gold,
                "gold_reliable": st.gold_reliable,
                "gold_unreliable": st.gold_unreliable,
                "gpm": st.gpm,
                "xpm": st.xpm,
                "net_worth": nw,
                "kill_participation": round((st.kills + st.assists) / team_kills, 3) if team_kills else None,
                "buyback_cost": s.hero.buyback_cost,
                "buyback_cooldown": s.hero.buyback_cooldown,
            }
            owned = s.owned_items
            out["items"] = {
                "inventory": [
                    {"slot": i.slot, "key": i.key, "name": ctx.data.items.name(i.key)} for i in s.inventory
                ],
                "backpack": [
                    {"slot": i.slot, "key": i.key, "name": ctx.data.items.name(i.key)} for i in s.backpack
                ],
                "stash": [
                    {"slot": i.slot, "key": i.key, "name": ctx.data.items.name(i.key)} for i in s.stash
                ],
                "neutral": s.neutral.key if s.neutral else None,
            }
            pro = ctx.data.per_hero("pro_builds.json", hero.id) or {}
            order = build_order(ctx, hero.id)
            nxt = next_items(order, owned, ctx.data.items, n=3)
            for item in nxt:
                gpm = max(st.gpm, 1)
                missing = max(item["remaining"] - st.gold, 0)
                item["eta_seconds"] = round(missing / gpm * 60) if missing else 0
                median = next((o["median_time"] for o in order if o["key"] == item["item"]), None)
                item["pro_median"] = fmt(median) if median is not None else None
            out["next_items"] = nxt
            if (
                nxt
                and nxt[0]["remaining"] > 0
                and st.gold >= nxt[0]["remaining"]
                and (s.hero.alive is not False)
            ):
                self._alert(
                    f"afford:{nxt[0]['item']}",
                    "item",
                    f"You can buy {nxt[0]['name']} now",
                    f"{nxt[0]['name']} ready to buy",
                )
            bb = s.hero.buyback_cost
            if (
                nxt
                and bb
                and clock is not None
                and clock >= 30 * 60
                and st.gold >= nxt[0]["remaining"] > 0
                and st.gold - nxt[0]["remaining"] < bb
            ):
                out["buyback_warning"] = (
                    f"Buying {nxt[0]['name']} leaves {st.gold - nxt[0]['remaining']} gold; "
                    f"buyback costs {bb}."
                )
            else:
                out["buyback_warning"] = None
            # Skills.
            points = unspent_skill_points(s)
            skills = (pro.get("skills") or {}).get("by_level", [])
            spent = sum(a.level for a in s.abilities)
            suggestion = skills[spent] if spent < len(skills) else None
            ability_names = {a.key: a.name for a in hero.abilities}
            out["skills"] = {
                "unspent": points,
                "next": {
                    "ability": suggestion["ability"],
                    "name": ability_names.get(suggestion["ability"], suggestion["ability"]),
                    "share": suggestion["share"],
                }
                if suggestion
                else None,
                "abilities": [
                    {
                        "key": a.key,
                        "name": ability_names.get(a.key, a.key),
                        "level": a.level,
                        "cooldown": a.cooldown,
                        "ultimate": a.ultimate,
                    }
                    for a in s.abilities
                ],
            }
            if points and points > 0 and suggestion and s.hero.level:
                self._alert(
                    f"skill:{s.hero.level}",
                    "skill",
                    f"Skill point ready: pros take {out['skills']['next']['name']} next",
                    f"Skill point: {out['skills']['next']['name']}",
                )
            # Benchmarks pace.
            bench = ctx.data.per_hero("benchmarks.json", hero.id)
            if clock and clock >= 120:
                minutes = clock / 60
                values = {
                    "gold_per_min": float(st.gpm),
                    "xp_per_min": float(st.xpm),
                    "last_hits_per_min": st.last_hits / minutes,
                }
                out["benchmarks"] = compare(values, bench)
                if bench and "last_hits_per_min" in bench:
                    median_lhpm = value_at(0.5, bench["last_hits_per_min"]) or 0
                    out["lh_target"] = {
                        "at_10": round(median_lhpm * 10),
                        "now": round(median_lhpm * minutes),
                        "you": st.last_hits,
                        "percentile": percentile_of(values["last_hits_per_min"], bench["last_hits_per_min"]),
                    }
        # Draft and counters.
        our_side = s.team or "radiant"
        their_side = "dire" if our_side == "radiant" else "radiant"
        own = [self.own_hero] if self.own_hero and not s.spectating else []
        allies = own + [h for h in self.draft_seen[our_side] if h not in own]
        enemies = [h for h in self.draft_seen[their_side] if h not in own]
        bans: list[int] = []
        for h in self.draft_seen["radiant_bans"] + self.draft_seen["dire_bans"] + self.draft_seen["bans"]:
            if h not in bans and h not in allies and h not in enemies:
                bans.append(h)
        out["draft"] = {
            "allies": allies[:5],
            "enemies": enemies[:5],
            "side": our_side,
            "side_known": s.team is not None or s.spectating,
            "bans": bans,
            "sources": dict(self.draft_sources),
            "note": SPECTATOR_NOTE if s.spectating else PLAYER_NOTE,
        }
        if enemies:
            out["situational_items"] = situational_items(
                enemies, ctx.traits, ctx.counter_rules, ctx.data.items, ctx.data.heroes.name, s.owned_items
            )
            bucket = ctx.data.matchup_bucket(settings.rank_bucket)
            out["enemy_threats"] = [
                {
                    "hero": e,
                    "traits": ctx.traits.view(e)[:6],
                    "countered_by": [c for c, _ in counters(e, bucket, 3)],
                }
                for e in enemies
            ]
        if s.spectating:
            out["players"] = [
                {
                    "team": p.team,
                    "slot": p.slot,
                    "name": p.name,
                    "hero": p.hero_id,
                    "level": p.level,
                    "alive": p.alive,
                    "kills": p.stats.kills,
                    "deaths": p.stats.deaths,
                    "assists": p.stats.assists,
                    "last_hits": p.stats.last_hits,
                    "gpm": p.stats.gpm,
                    "net_worth": p.stats.net_worth,
                    "items": [{"key": i.key, "name": ctx.data.items.name(i.key)} for i in p.items],
                }
                for p in s.players
            ]
        out["series"] = self.series[-200:]
        out["events"] = self.event_log[-30:]
        out["alerts"] = [a.as_dict() for a in list(self.alerts)[:30]]
        return out
