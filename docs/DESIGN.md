# Design: Dota 2 companion, version 2

Written 2026-10-19. This document is what the v2 build was planned from. `docs/ROADMAP.md` lists every
feature with its status, and `docs/SAFETY.md` states exactly what the app touches.

## Intent

Tajaddin plays ranked Dota 2 and wants one tool he actually uses, from the draft to the post-game,
without risking his account. The v1 repository had a good core (a GSI listener, an item recommender, a
match lookup and a draft advisor) but it did not run from a fresh clone: the hero data files it loads
(`data/items.json`, `data/hero_tags.json`, ...) were never committed, the ML models were never shipped,
and the draft advisor had no UI.

v2 keeps everything v1 had, rebuilds it on data that ships with the repository, and adds every feature
that the safe channels allow.

## Goals

1. **Works on a fresh clone with one command** on Windows (`.\run.cmd`), offline, using a committed
   data snapshot. Refreshing the data is one button.
2. **Covers the whole game**: account and meta before queueing, draft, laning, mid and late game,
   post-game review, and long-term progress.
3. **Ban-safe by construction**: Valve's Game State Integration (GSI), public HTTP APIs and static data,
   nothing else (see `docs/SAFETY.md`).
4. **Honest numbers**: every statistic shown says where it comes from (source, sample size, date or
   patch). Nothing is invented. When data is missing, the UI says so instead of guessing.
5. **Production standard**: typed and linted code, unit and integration tests, an end-to-end browser
   test, green CI, measured results in the README.

## Non-goals

- Live information about enemies that the game does not send to a player (their items, cooldowns,
  positions). GSI only sends the local player's own state while playing; full 10-player data arrives
  only when spectating. The app shows enemy items only in that case.
- Exact MMR. OpenDota exposes the rank medal, not MMR; the app shows the medal.
- Identifying the other players during a ranked draft. Ranked drafts are anonymous by Valve's design.
- A hosted, multi-user service. It is a local app for one player.

## Anti-goals (a failure even if it technically works)

- Anything that reads or writes the game process, patches game files, sniffs packets, draws into the
  game's render, or sends keyboard or mouse input. One of these could get the account banned.
- A number with no source, or a "tip" with no data behind it.
- Setup that needs a manual step every session, or a UI that needs a manual to read.
- Hammering public APIs: every client respects the published limits and caches responses.

## Constraints

- **Platform**: Windows 11 with Python and Node already installed; the repo also has to run on Linux CI.
- **OpenDota limits** (read from the response headers on 2026-10-19): 60 requests a minute and about
  3,000 a day without a key (`X-Rate-Limit-Remaining-Minute`, `X-Rate-Limit-Remaining-Day`). A key
  raises them; he can add his own.
- **Patch**: 7.41f (Valve patch list, 2026-09). Timer rules carry the patch they were verified against.
- **No accounts, keys or payments created for him.** Optional integrations (OpenDota key, STRATZ token,
  Steam Web API key) are fields he fills in himself.

## Decisions (builder's calls, made 2026-10-19)

| # | Decision | Why |
|---|---|---|
| D1 | New package `src/d2bg` (Python 3.12, FastAPI) serving a React + TypeScript UI in the browser, alongside the untouched v1 desktop app | Dozens of panels, a draft board and live timers are far easier to build, test (Playwright) and use in a browser than in Tk. A browser view also works on a second monitor or a phone. v1 stays runnable (`python main.py`); deleting it is his call. |
| D2 | One process: GSI receiver, REST API, Server-Sent Events stream and static UI on `127.0.0.1:4242` | One thing to start and stop. Loopback-only by default. |
| D3 | Committed data snapshot in `data/snapshot/`, refreshed by `d2bg data refresh` into the user data dir | Fresh clone works offline; refreshes never dirty the repo unless asked (`--to-snapshot`). |
| D4 | Data from OpenDota's public API only: constants, `/heroStats`, `/heroes/{id}/itemPopularity`, `/benchmarks`, `/scenarios/*`, `/publicMatches`, `/explorer` (pro matches), `/players/*`, `/matches/*` | Public, documented, free, and already what v1 used. STRATZ and the Steam Web API stay optional. |
| D5 | One rate-limited, caching HTTP client for every OpenDota call: token bucket at 1 request/s, honours the rate-limit headers, backs off on 429 and 5xx, disk cache with per-endpoint TTL, persistent daily call counter | Protects his IP from limits and keeps refreshes resumable. |
| D6 | No pickles. Models ship as JSON weights and run in pure Python | Pickle loading is code execution; v1 had to guard against it. |
| D7 | Draft win probability = logistic regression on hero one-hot (radiant minus dire) plus matchup-matrix features, trained on public ranked matches, evaluated on a time-ordered held-out split | Simple, explainable per hero, and its accuracy can be measured honestly. |
| D8 | Hero traits (stun, silence, invisibility, illusions, healing, ...) derived from public ability data, with a small reviewed override file | No hand-typed tags for 127 heroes; derivation is testable. |
| D9 | Timer rules in a JSON file per patch, each rule citing the official patch note it comes from | Patch changes become a data edit, and every timer is traceable. |
| D10 | GSI config written with a random per-install auth token; payloads with a wrong token are rejected | Stops other local programs from feeding the app fake state. |
| D11 | Every GSI session can be recorded to gzip JSONL and replayed; a synthetic demo match ships for trying the app and for CI | He can test the whole live UI without launching Dota. |
| D12 | UI response types written by hand in `web/src/api/types.ts`; the Playwright suite runs the built UI against the real server in CI, so drift fails the build | Most routes return composed dictionaries, so generated OpenAPI types would be empty shells; an end-to-end run catches what matters. (Changed during the build from generated types.) |
| D13 | Optional always-on-top compact window via `pywebview` (a separate OS window), never anything drawn inside the game | Same safety class as any window placed over a borderless game. |

## Architecture

```
Dota 2 client ──GSI HTTP POST──▶ /gsi ──▶ GsiParser ──▶ LiveEngine ──▶ SSE /api/live/stream ──▶ UI
                                   │                       │  timers, build tracker, alerts,
                                   └─▶ Recorder (gz JSONL)  │  benchmarks, post-game trigger
                                                            ▼
OpenDota API ◀── OpenDotaClient (rate limit, cache, budget) ◀── pipelines (refresh) and live lookups
                                                            │
data/snapshot (committed) ──▶ DataStore ◀── user data dir (refreshed data, settings, recordings)
                                   │
                    Draft, builds, knowledge, profile, match review (pure functions)
                                   │
                         FastAPI routers /api/* ──▶ React UI (Vite build served as static files)
```

Package layout (`src/d2bg/`):

| Module | Responsibility |
|---|---|
| `settings.py`, `paths.py` | User settings JSON, data directories (`platformdirs`) |
| `opendota.py` | The rate-limited caching client (D5) |
| `datastore.py` | Loads the snapshot and refreshed data, picks the newer, exposes typed views |
| `knowledge/` | Heroes, items, aliases, search, derived traits, counter-item rules, timers |
| `draft/` | Advisor (picks, counters, bans, meta, roles), composition, lanes, win model |
| `builds/` | Item and skill builds, starting items, item timings, component-aware gold remaining |
| `gsi/` | Payload models, parser, installer, recorder, replayer, demo generator |
| `live/` | LiveEngine: game state, timers, alerts, build tracker, benchmark tracker |
| `profile/`, `matches/` | Player profile analytics, match review, post-game fetcher |
| `pipeline/` | Refresh jobs and the snapshot builder, matchup matrix, model training |
| `api/` | FastAPI app and routers |
| `cli.py` | `d2bg serve | gsi | data | replay | demo | draft | build | train` |

UI (`web/`): Vite, React 19, TypeScript (strict), React Router, TanStack Query. Pages: Live, Draft,
Heroes, Hero detail, Items, Meta, Profile, Match review, Setup, Settings, and a compact `/compact` view.

## Data sources

| Data | Source | Refresh |
|---|---|---|
| Heroes, items, abilities, talents, Aghanim's text, patches | OpenDota `/constants/*` (dotaconstants, MIT) | each refresh |
| Pick and win rate by rank bracket, pro picks and bans | `/heroStats` | daily |
| Hero vs and with advantage by rank bucket | `/publicMatches` (ranked All Pick), our own smoothing | weekly |
| Item popularity by game phase | `/heroes/{id}/itemPopularity` | weekly |
| Skill orders, talents, starting items, purchase order and timings, lane roles | `/explorer` over recent pro matches | weekly |
| Performance percentiles | `/benchmarks?hero_id=` | weekly |
| Item timing win rates, lane role win rates | `/scenarios/itemTimings`, `/scenarios/laneRoles` | weekly |
| His profile and matches | `/players/{id}/*`, `/matches/{id}`, `POST /request/{id}` | on demand |
| Timer rules | Valve's official patch notes feed (`dota2.com/datafeed/patchnotes`) | per patch, by hand |

## Testing strategy

- **Unit**: every pure module (advisor, traits, timers, builds, parser, model inference, analytics) on
  small hand-checked fixtures.
- **Integration**: FastAPI `TestClient` end to end: GSI POSTs with and without the token, the live
  state and SSE stream, every API route against the committed snapshot; the OpenDota client against
  `respx` mocks (rate limiting, 429 back-off, caching, budget). No test touches the network.
- **UI**: Vitest for components and helpers; Playwright drives the built UI against `d2bg serve --demo`
  (the synthetic match) in CI.
- **Legacy**: the v1 tests keep running in their own CI job.

## Build order

1. Package skeleton, settings, OpenDota client, datastore, snapshot pipeline; commit the snapshot.
2. Knowledge: hero search and aliases, traits, counter items, timers.
3. Draft: advisor port and extensions, composition, lanes, win model.
4. Builds and hero pages.
5. GSI: models, parser, installer, recorder, replay, demo; LiveEngine with timers, tracker, alerts.
6. Profile and match review, post-game fetcher.
7. UI for all of the above; compact view; one-command run.
8. CI, README with measured results, PROJECT-FACTS update.

## Left to the builder

Visual design, exact API shapes, thresholds that tests can pin, and the order of panels within pages.
