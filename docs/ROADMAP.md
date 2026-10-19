# Roadmap: every feature

Status key: **built** = shipped and tested in v2 · **next** = designed, not built yet ·
**no** = rejected, with the reason (mostly ban safety, see `SAFETY.md`).

Every feature uses only the channels in `SAFETY.md`: Valve's Game State Integration, public HTTP APIs
and static data.

## A. Setup and platform

| # | Feature | Status |
|---|---|---|
| A1 | One command to install, build and start on Windows (`.\run.cmd`), opens the browser | v2 |
| A2 | Setup page: finds Dota through Steam's library list, writes the GSI config, shows when the first packet arrives | v2 |
| A3 | Random per-install GSI auth token; payloads with a wrong token are rejected | v2 |
| A4 | GSI health: packets received, last packet age, which data blocks the game is sending | v2 |
| A5 | Remove the GSI config (only the file this app wrote) | v2 |
| A6 | Settings saved to the user data folder: account ID, rank bracket, roles, hero pool, blacklist, synergy weight, timers and voice | v2 |
| A7 | Account ID detected from the first GSI packet when not set | v2 |
| A8 | Data refresh job with progress, per-step call counts, and the OpenDota daily budget left | v2 |
| A9 | Optional OpenDota API key field (he enters it; never committed) | v2 |
| A10 | Works offline from the committed data snapshot | v2 |
| A11 | Disk cache with per-endpoint lifetimes for every API call | v2 |
| A12 | `/health` and `/api/version`, structured logs | v2 |
| A13 | Compact view (`/compact`) for a second monitor or a phone | v2 |
| A14 | Optional always-on-top compact window (`d2bg window`, separate OS window via pywebview) | v2 |
| A15 | LAN mode for a phone: opt-in, needs an access token | v2 |
| A16 | Record every GSI session to gzip JSONL, keep the newest 20 | v2 |
| A17 | Replay a recording at 1x to 32x into the live UI | v2 |
| A18 | Synthetic demo match to try every live feature without Dota | v2 |
| A19 | Keyboard shortcuts across pages | v2 |
| A20 | Dark and light themes | v2 |
| A21 | Docker image | next |
| A22 | Update check against GitHub releases | next |
| A23 | Diagnostics export (settings without secrets, recent logs, GSI coverage) | next |

## B. Data and knowledge

| # | Feature | Status |
|---|---|---|
| B1 | Heroes, items, abilities, talents, Aghanim's Scepter and Shard text from OpenDota constants | v2 |
| B2 | Hero search with community aliases (am, wr, sf, cm, qop, ...) and typo tolerance | v2 |
| B3 | Hero traits derived from ability data: stuns, silences, hexes, roots, invisibility, illusions, summons, healing, evasion, dispels, damage types, BKB-piercing spells, mobility | v2 |
| B4 | Hero positions from lane-role statistics | v2 |
| B5 | Meta by rank bracket (Herald to Immortal) from `/heroStats`, plus pro and Turbo views | v2 |
| B6 | Hero vs and with advantage matrices per rank bucket, smoothed, with minimum sample sizes | v2 |
| B7 | Item popularity by game phase per hero | v2 |
| B8 | Pro build corpus: skill orders, talents, starting items, purchase order, item timings, lane roles | v2 |
| B9 | Performance benchmarks (percentiles) per hero | v2 |
| B10 | Item timing win rates per hero | v2 |
| B11 | Timer rules per patch, each citing the official patch note | v2 |
| B12 | Item component trees and "builds into" | v2 |
| B13 | Snapshot manifest: source, date, sample size and patch for every data file | v2 |
| B14 | STRATZ as a second source with his own token | next |

## C. Draft

| # | Feature | Status |
|---|---|---|
| C1 | Draft board: 5 v 5 plus bans, search, keyboard entry, undo, clear, swap sides | v2 |
| C2 | Fills in your hero and side from GSI; fills the whole draft when GSI sends draft data (spectating) | v2 |
| C3 | Suggested picks overall and per position, each with the matchups that drive its score | v2 |
| C4 | Counter picks per enemy, and "hot" counters that beat two or more enemies | v2 |
| C5 | Ban suggestions: heroes that beat your picks, weighted by meta strength | v2 |
| C6 | Meta picks for your rank bracket | v2 |
| C7 | Win probability for the current draft, with each hero's contribution | v2 |
| C8 | Team composition: traits covered, damage-type split, melee or ranged, gaps and warnings for both teams | v2 |
| C9 | Lane matchups: assign heroes to lanes, see each lane's advantage | v2 |
| C10 | Pick order advice: safe early picks vs heroes that are easy to counter | v2 |
| C11 | Hero pool mode: suggestions limited to or boosted for heroes you play | v2 |
| C12 | Blacklist, whitelist, synergy weight and rank bracket controls | v2 |
| C13 | Compare 2 or 3 candidates side by side | v2 |
| C14 | Copy the draft as text; paste a hero list to fill it | v2 |
| C15 | Situational items to plan for against the enemy draft | v2 |
| C16 | Save drafts and see their results after the match | next |
| C17 | Captains Mode phase order hints | next |

## D. Builds and hero guides

| # | Feature | Status |
|---|---|---|
| D1 | Hero page: roles, attributes, base stats, abilities, talents, Aghanim's text | v2 |
| D2 | Skill build: most common pro order by level, with talent pick rates | v2 |
| D3 | Item build: starting items, build order with median pro timings, popularity by phase | v2 |
| D4 | Situational items against a chosen enemy draft, each with its reason | v2 |
| D5 | Item timing targets and win rate by timing | v2 |
| D6 | Best and worst matchups and allies per rank bucket | v2 |
| D7 | Benchmarks table (GPM, XPM, last hits, damage, healing, tower damage) | v2 |
| D8 | Lane and position split | v2 |
| D9 | Item pages: cost, components, builds into, who buys it | v2 |
| D10 | Copy a build as text | v2 |
| D11 | Neutral items by tier for the current patch | v2 |
| D12 | Similar heroes (matchup-profile similarity) | v2 |
| D13 | Compare two heroes | next |

## E. Live game (GSI)

| # | Feature | Status |
|---|---|---|
| E1 | Live panel: hero, level, K/D/A, last hits and denies, GPM and XPM, gold, net worth, buyback | v2 |
| E2 | Next-item tracker: gold still needed after components you own, and time to afford at your GPM | v2 |
| E3 | "You can buy it now" alerts | v2 |
| E4 | Unspent skill point reminder with the next recommended skill | v2 |
| E5 | Timers: bounty, water and power runes, wisdom shrines, lotus pools, Tormentor, Roshan (from game events or one click), Aegis expiry, day and night, neutral item tiers, camp stacking, siege creeps | v2 |
| E6 | Voice callouts with lead times and per-timer switches | v2 |
| E7 | Last-hit and GPM pace against the hero's benchmark percentiles | v2 |
| E8 | Buyback guard: warns when a purchase would leave you without buyback gold | v2 |
| E9 | Kill participation from the team score | v2 |
| E10 | Game event log (Roshan, Aegis, Tormentor, runes) | v2 |
| E11 | Spectator mode: all ten players with net worth and items | v2 |
| E12 | Enemy item alerts (only when GSI sends enemy items, i.e. spectating) | v2 |
| E13 | Gold and experience chart over game time | v2 |
| E14 | Death summary: time dead, gold lost | next |
| E15 | Ward and smoke reminders from ward stock cooldowns | next |

## F. Post-game and profile

| # | Feature | Status |
|---|---|---|
| F1 | Post-game: when a match ends, fetch it from OpenDota with back-off and offer a replay parse request | v2 |
| F2 | Match review: scoreboard, your benchmarks percentiles, item timings against pro medians | v2 |
| F3 | Match lookup by ID (v1 feature, rebuilt) | v2 |
| F4 | Profile: rank medal, wins and losses, recent matches, trends | v2 |
| F5 | Hero pool: win rate with a confidence bound, comfort heroes, heroes worth adding | v2 |
| F6 | Sessions: today's results, streaks, win rate by hour | v2 |
| F7 | Look up any player by account ID or name | v2 |
| F8 | Players you queue with (peers) | v2 |
| F9 | Export matches to CSV | next |
| F10 | Personal records | next |

## G. Models

| # | Feature | Status |
|---|---|---|
| G1 | Draft win-probability model, JSON weights, measured on a held-out time split | v2 |
| G2 | Hero similarity from matchup profiles | v2 |
| G3 | v1 XGBoost item recommender (needs his trained models; v1 app only) | built (v1) |
| G4 | Retrain the draft model from refreshed matches (`d2bg train draft`) | v2 |

## H. Optional integrations (his own keys)

| # | Feature | Status |
|---|---|---|
| H1 | OpenDota API key for higher limits | v2 |
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
