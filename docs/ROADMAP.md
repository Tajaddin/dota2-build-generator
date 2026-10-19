# Roadmap: every feature

Status key: **built** = shipped in v2 and covered by tests · **built, unverified** = the code is in but
could not be exercised here · **next** = designed, not built yet · rejected ideas are listed at the
end with the reason (mostly ban safety, see `SAFETY.md`).

Every feature uses only the channels in `SAFETY.md`: Valve's Game State Integration, public HTTP APIs
and static data.

Totals: 85 built (84 in v2 plus the v1 recommender), 1 built but unverified, 13 next, 10 rejected.

## A. Setup and platform

| # | Feature | Status |
|---|---|---|
| A1 | One command to install, build and start on Windows (`.\run.cmd`), opens the browser | built |
| A2 | Setup page: finds Dota through Steam's library list, writes the GSI config, shows when the first packet arrives | built |
| A3 | Random per-install GSI auth token; payloads with a wrong token are rejected | built |
| A4 | GSI health: packets received, last packet age, which data blocks the game is sending | built |
| A5 | Remove the GSI config (only the file this app wrote) | built |
| A6 | Settings saved to the user data folder: account ID, rank bracket, hero pool, blacklist, synergy weight, timers and voice, post-game options, theme | built |
| A7 | Account ID detected from the first GSI packet when not set | built |
| A8 | Data refresh job with progress, per-step call counts, and the OpenDota daily budget left | built |
| A9 | Optional OpenDota API key field (he enters it; never committed) | built |
| A10 | Works offline from the committed data snapshot | built |
| A11 | Disk cache with per-endpoint lifetimes for every API call | built |
| A12 | `/health` and `/api/version` | built |
| A13 | Compact view (`/compact`) for a second monitor or a phone | built |
| A14 | Optional always-on-top compact window (`d2bg window`, a separate OS window via pywebview) | built, unverified |
| A15 | LAN mode for a phone: opt-in, needs an access token; GSI still accepted from this PC only | built |
| A16 | Record every GSI session to gzip JSONL, keep the newest 20 | built |
| A17 | Replay a recording into the live UI at up to 64x | built |
| A18 | Synthetic demo match to try every live feature without Dota | built |
| A19 | Keyboard shortcuts across pages | built |
| A20 | Dark and light themes | built |
| A21 | Docker image | next |
| A22 | Update check against GitHub releases | next |
| A23 | Diagnostics export (settings without secrets, recent logs, GSI coverage) and structured logs | next |

## B. Data and knowledge

| # | Feature | Status |
|---|---|---|
| B1 | Heroes, items, abilities, talents, Aghanim's Scepter and Shard text from OpenDota constants | built |
| B2 | Hero search with community aliases (am, wr, sf, cm, qop, ...) and typo tolerance | built |
| B3 | Hero traits derived from ability data: stuns, silences, hexes, roots, taunts, invisibility, illusions, summons, healing, saves, evasion, damage types, BKB-piercing spells, mobility, global reach | built |
| B4 | Hero positions from pro lane and GPM data, then public lane roles, then listed roles | built |
| B5 | Meta by medal (Herald to Immortal) from `/heroStats`, plus pro, Turbo and ranked-sample views | built |
| B6 | Hero vs and with advantage matrices per rank bucket, smoothed, with minimum sample sizes | built |
| B7 | Item popularity by game phase per hero | built |
| B8 | Pro build corpus: skill orders, talents, starting items, purchase order, item timings, positions | built |
| B9 | Performance benchmarks (percentiles) per hero | built |
| B10 | Item timing win rates per hero | built |
| B11 | Timer rules per patch, each citing the official patch note | built |
| B12 | Item component trees and "builds into" | built |
| B13 | Snapshot manifest: source, date, row count and API calls for every data file | built |
| B14 | STRATZ as a second source with his own token | next |

## C. Draft

| # | Feature | Status |
|---|---|---|
| C1 | Draft board: 5 v 5 plus bans, search, keyboard entry, undo, clear, swap sides | built |
| C2 | "Fill from game": your hero and side from GSI, the whole draft when GSI sends it (spectating) | built |
| C3 | Suggested picks overall and per position, each with the matchups that drive its score | built |
| C4 | Counter picks per enemy, and heroes that counter two or more enemies | built |
| C5 | Ban suggestions: heroes that beat your picks, weighted by meta strength | built |
| C6 | Meta picks for your rank bracket (Meta page; the draft API returns them too) | built |
| C7 | Win probability for the current draft, with each hero's contribution | built |
| C8 | Team composition: traits covered, damage-type split, melee or ranged, gaps and warnings for both teams | built |
| C9 | Lane matchups from each hero's most likely position | built |
| C10 | Pick order advice: a "counter risk" for every suggestion | built |
| C11 | Hero pool mode: suggestions limited to or boosted for heroes you play | built |
| C12 | Blacklist, synergy weight and rank bracket controls (whitelist through the API) | built |
| C13 | Compare up to 3 candidates side by side | built |
| C14 | Copy the draft as text; paste a hero list to fill it | built |
| C15 | Situational items to plan for against the enemy draft | built |
| C16 | Save drafts and see their results after the match | next |
| C17 | Captains Mode phase order hints | next |

## D. Builds and hero guides

| # | Feature | Status |
|---|---|---|
| D1 | Hero page: roles, attributes, base stats, abilities, talents, Aghanim's text | built |
| D2 | Skill build: most common pro skill at each point, top orders with win rates, talent pick rates | built |
| D3 | Item build: starting items, build order with median pro timings, popularity by phase | built |
| D4 | Situational items against an enemy draft, each with its reason (Draft and Live pages) | built |
| D5 | Win rate by item timing | built |
| D6 | Best and worst matchups and allies per rank bucket | built |
| D7 | Benchmarks table (GPM, XPM, last hits, damage, healing, tower damage) | built |
| D8 | Position split and public lane split | built |
| D9 | Item pages: cost, recipe, components, builds into, pro heroes that build it | built |
| D10 | Copy a build as text | built |
| D11 | Neutral items by tier | built |
| D12 | Similar heroes (matchup-profile similarity) | built |
| D13 | Compare two heroes | next |

## E. Live game (GSI)

| # | Feature | Status |
|---|---|---|
| E1 | Live panel: hero, level, K/D/A, last hits and denies, GPM and XPM, gold, net worth, buyback, inventory | built |
| E2 | Next-item tracker: gold still needed after components you own, time to afford at your GPM, the pro median | built |
| E3 | "You can buy it now" alerts | built |
| E4 | Unspent skill point reminder with the skill pros usually take next | built |
| E5 | Timers: bounty, water and power runes, wisdom shrines, lotus pools, Tormentor, Roshan (from game events or one click), Aegis expiry, day and night, neutral item tiers, camp stacking, extra siege creeps | built |
| E6 | Voice callouts for alerts, with per-timer switches | built |
| E7 | Last-hit, GPM and XPM pace against the hero's benchmark percentiles | built |
| E8 | Buyback guard after 30:00: warns when the next purchase leaves less gold than buyback costs | built |
| E9 | Kill participation from the team score | built |
| E10 | Game event log (Roshan, Aegis and clicks) | built |
| E11 | Spectator mode: all ten players with net worth and items | built |
| E12 | Item alerts for other players' notable purchases (only when GSI sends them, i.e. spectating) | built |
| E13 | Gold and last-hit chart over game time | built |
| E14 | Death summary: time dead, gold lost | next |
| E15 | Ward and smoke reminders from ward stock cooldowns | next |

## F. Post-game and profile

| # | Feature | Status |
|---|---|---|
| F1 | Post-game: when a match ends, fetch it from OpenDota with back-off; optional replay parse request | built |
| F2 | Match review: scoreboard, your benchmark percentiles, item timings against pro medians, notes drawn only from those numbers | built |
| F3 | Match lookup by ID (v1 feature, rebuilt) | built |
| F4 | Profile: rank medal, wins and losses, recent matches, rolling win rate | built |
| F5 | Hero pool: win rate with a 95% lower bound, comfort heroes, heroes worth adding | built |
| F6 | Sessions, streaks and win rate by hour | built |
| F7 | Look up any player by account ID or name | built |
| F8 | Players you queue with (peers) | built |
| F9 | Export matches to CSV | next |
| F10 | Personal records | next |

## G. Models

| # | Feature | Status |
|---|---|---|
| G1 | Draft win-probability model, JSON weights, measured on a held-out time split | built |
| G2 | Hero similarity from matchup profiles | built |
| G3 | v1 XGBoost item recommender (needs his trained models; v1 app only) | built (v1) |
| G4 | Retrain the draft model from refreshed matches (`d2bg train`) | built |

## H. Optional integrations (his own keys)

| # | Feature | Status |
|---|---|---|
| H1 | OpenDota API key for higher limits | built |
| H2 | STRATZ token | next |
| H3 | Steam Web API key (persona names) | next |

## Rejected for safety or policy

| Idea | Why not |
|---|---|
| Reading `dota2.exe` memory (enemy cooldowns, hidden info) | Valve banned 40,000+ accounts in 2023 for software that read client data; never |
| DLL injection or an overlay drawn inside the game | Modifies the game process; VAC territory |
| Packet sniffing | Reads traffic Valve does not publish; same class as memory reading |
| Auto-accept, auto-buy, macros, any synthetic key or mouse input | Automated input is botting |
| Writing `coreinit.lua`, autoexec or any game file except the GSI config | Game-file modification (DotaPlus does this for MMR; we do not) |
| Editing Steam launch options or `localconfig.vdf` | His settings; we only read the Steam library list |
| Tailing `console.log` (needs `-condebug`) | Passive, but adds a launch option and parses game-coordinator traffic; not worth the risk |
| Screen capture or OCR of the game during matches | Reads the game client's output in a way Valve has not sanctioned |
| Scraping sites whose terms forbid it | We use documented APIs only |
| DotaPlus or Overwolf backends and data | Not ours; clean-room rule |
