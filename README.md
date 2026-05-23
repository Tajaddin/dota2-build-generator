# dota2-build-generator

Hero build recommender for Dota 2. PyTorch hero and item embeddings, XGBoost matchup classifier, live in-game overlay through the Dota 2 Game State Integration API. Trained on OpenDota match data.

## Hero numbers

| Metric | Value |
|---|---|
| Training data | 50K+ ranked matches from OpenDota + Kaggle bulk dumps |
| Embedding model | PyTorch, hero and item co-occurrence |
| Matchup classifier | XGBoost, three per-phase models (early, mid, late) |
| Eval metric | Top-5 hit rate per game phase, computed in `ml/train_xgboost.py` |
| Test files | 11, covering parser, server, recommender, threat analyzer |
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
  ml/
    embedding_model.py    PyTorch hero and item embedding
    train_embeddings.py   Embedding training entry point
    train_xgboost.py      Three phase models, top-5 hit rate reporter
    data_collector.py     OpenDota collector with daily cap
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
  tests/                  11 pytest files
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
pytest -q                       # logic tests (21 currently pass; some are dataset-gated)
python main.py                  # launches the overlay (Browse mode first run)
```

The first run launches in Browse mode. Live mode needs the GSI cfg, which the installer writes on first launch of the overlay.

## Limitations

1. Patch sensitivity. Item meta shifts every patch. A model trained on 7.36 will drift on 7.37.
2. Rank sensitivity. The training data skews to public ranked. Pro-game itemization differs.
3. No build-order signal. Item set is recommended, item order is not.
4. GSI does not expose enemy items reliably during live play. The enemy-draft signal is hero-only, not item-aware.
