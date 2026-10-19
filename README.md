# dota2-build-generator

Hero build recommender for Dota 2. PyTorch hero and item embeddings, XGBoost matchup classifier, live in-game overlay through the Dota 2 Game State Integration API. Trained on OpenDota match data.

## Hero numbers

| Metric | Value |
|---|---|
| Training data | 50K+ ranked matches from OpenDota + Kaggle bulk dumps |
| Embedding model | PyTorch, hero and item co-occurrence |
| Matchup classifier | XGBoost, three per-phase models (early, mid, late) |
| Eval metric | Top-5 hit rate per game phase, computed in `ml/train_xgboost.py` |
| Test files | 13, covering parser, server, recommender, threat analyzer, matchup matrix, draft advisor |
| Live overlay | GSI HTTP server with auto-installer for the Dota 2 cfg |

## Three modes

| Mode | What it does |
|---|---|
| Browse | Pick a hero from the grid. Get recommended items split by early, mid, late phase |
| Live | GSI auto-detects your hero and the enemy draft. Builds update each tick |
| Match lookup | Paste a match ID. Show what items the winning player bought and when |

## Algorithm

1. Data collection: `ml/data_collector.py` pulls match snapshots from OpenDota with a daily request cap. `ml/kaggle_ingest.py` imports bulk JSONL.
2. Embedding training: `ml/train_embeddings.py` learns hero and item vectors from co-occurrence in winning builds. Both winners and losers go into the training set, losers down-weighted to 0.35 so you get more snapshots per match without flipping the signal.
3. Matchup classifier: `ml/train_xgboost.py` trains three XGBoost models (early, mid, late phase). Input is the concatenated friendly-team and enemy-team hero embedding. Output is a per-item probability. Reports top-5 hit rate per phase on a held-out split.
4. Inference: `logic/ai_recommender.py` blends a stats-first baseline with the XGBoost matchup adjustment. The stats-first baseline alone gives a reasonable build, the XGBoost layer shifts items based on the enemy draft.

## Live overlay

`logic/gsi_server.py` listens on localhost for GSI events. `logic/gsi_installer.py` writes the cfg file into the Dota 2 install directory so the game starts sending events on its own. `ui/overlay.py` paints a borderless always-on-top window with the current recommendation.

## Stack

Python, PyTorch, XGBoost, scikit-learn, pandas, numpy, customtkinter (UI), Flask (GSI HTTP server), requests (OpenDota client).

## Repository layout

```
dota2-build-generator/
  main.py
  logic/
    ai_recommender.py     Stats-first plus XGBoost matchup adjustment
    gsi_server.py         HTTP server, receives Dota 2 GSI events
    gsi_parser.py         Parses GSI payloads into game state
    gsi_installer.py      Writes the GSI cfg into the Dota 2 install dir
    match_lookup.py       OpenDota match client
    draft_advisor.py      Draft suggestions: counters, hot counters, meta picks
  ml/
    embedding_model.py    PyTorch hero and item embedding
    train_embeddings.py   Embedding training entry point
    train_xgboost.py      Three phase models, top-5 hit rate reporter
    data_collector.py     OpenDota collector with daily cap
    build_matchup_matrix.py  Weekly hero vs/with advantage matrices per rank bucket
    import_matches.py     JSONL ingest (Kaggle, bulk dumps)
    kaggle_ingest.py      Kaggle dataset adapter
    TRAINING.md           Free-tier workflow guide
  ui/
    hero_select.py        Hero grid
    build_view.py         Phase-split item display
    overlay.py            Live in-game overlay
  scripts/
    fetch_opendota.py     Bulk fetch helper
    validate_data.py      Snapshot integrity checks
  tests/                  13 pytest files
  models/
    hero_item_stats.json  Stats-first lookup table
```

## Training on a free OpenDota tier

```
python -m ml.train --matches 10000 --max-per-day 3000
```

Run the same command on consecutive days. State lives in `ml/raw_data/.collect_daily.json` so each day adds another 3K matches without re-fetching. Full workflow in `ml/TRAINING.md`.

Skip the API entirely with a JSONL file:

```
python -m ml.train --from-file path/to/matches.jsonl --skip-collect --epochs 20
```

## How to run

Prerequisites: Python 3.11+ (CPU works for inference; trained pickle artifacts are loaded with SHA256 verification, see `MODEL_HASHES` in `logic/ai_recommender.py`).

```bash
pip install -r requirements.txt
pip install pytest
pytest -q                       # 43 pass on a fresh clone; 31 skip until data/ has the local hero dataset
python main.py                  # launches the overlay (Browse mode first run)
```

The first run launches in Browse mode. Live mode needs the GSI cfg, which the installer writes on first launch of the overlay.

## Draft suggestions

`ml/build_matchup_matrix.py` builds, once a week, how much each hero's win rate moves against (`vs`) and alongside (`with`) every other hero, separately for rank buckets Herald-Guardian, Crusader-Archon, Legend-Ancient, Divine-Immortal and all ranks. Win rates are smoothed with 20 pseudo-games at the hero's base rate, and any pair seen in fewer than 50 games is stored as `null` rather than a guessed number. Output goes to `data/matchups/<YYYY-MM-DD>.json`.

```
python -m ml.build_matchup_matrix --calls 1500                          # OpenDota, ~25 min at 60 req/min
python -m ml.build_matchup_matrix --from-jsonl ml/raw_data/matches.jsonl  # no API calls
```

`logic/draft_advisor.py` turns one bucket into suggestions. A candidate's score is its mean `vs` advantage over the enemy picks, plus a user weight times its mean `with` advantage over ally picks, minus a penalty when it can only fill a role the allies already cover. It also lists each enemy's top 10 counters, "hot" counters that beat two or more enemies, and meta picks by smoothed win rate (pick rate at least 1%). Bans, picks, a blacklist and a whitelist are respected. The advisor is pure functions with no I/O.

## Data sources and rules

| Source | Used for | Limits |
|---|---|---|
| [OpenDota API](https://docs.opendota.com/) | `/publicMatches` for the matchup matrix; item popularity and hero matchups | Free tier is about 60 requests a minute; the builder waits 1.05 s between requests, backs off on 429, and caches every page in `data/cache/` |
| Kaggle OpenDota dumps | Bulk training and matrix input via `ml/kaggle_ingest.py` | Offline |
| [STRATZ API](https://stratz.com/api) | Optional, with your own token | Its own rate limits and terms |
| Dota 2 Game State Integration | Your hero, items and the draft, sent by the game to `localhost` | Valve's documented interface; only what the game chooses to send |

Hard rules for this project:

- **No memory reading.** Nothing here opens, reads or injects into the Dota 2 process.
- **No game-file edits.** The only file written into the Dota 2 folder is the GSI config (`game/dota/cfg/gamestate_integration/gamestate_integration_buildgen.cfg`), which is how Valve's Game State Integration is meant to be enabled. Nothing is written under `dota/scripts`, and Steam launch options are left to you.
- **Public data only.** No third-party app's backend, data or code is used.

## Limitations

1. Patch sensitivity. Item meta shifts every patch. A model trained on 7.36 will drift on 7.37.
2. Rank sensitivity. The training data skews to public ranked. Pro-game itemization differs.
3. No build-order signal. Item set is recommended, item order is not.
4. GSI does not expose enemy items reliably during live play. The enemy-draft signal is hero-only, not item-aware.
