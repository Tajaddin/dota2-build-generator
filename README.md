# dota2-build-generator

Embedding-based hero build recommender trained on 50K+ Dota 2 matches. Deployed as a production inference service with a TypeScript + Node.js backend API, Docker packaging, and a CI/CD release pipeline with automated regression tests.

## What It Does

Recommends item builds for Dota 2 heroes based on real match data. Combines PyTorch embedding models with an XGBoost matchup classifier, served through a live backend API with real-time Game State Integration (GSI) overlay.

**Key numbers:**
- 50K+ matches used for training
- Embedding model trained on hero/item co-occurrence patterns
- XGBoost classifier for enemy-draft-aware matchup adjustments
- Production inference API with automated regression tests on each release

## Architecture

**ML Pipeline**

1. Data collection from OpenDota API and Kaggle public datasets
2. PyTorch encoder trained on hero/item embeddings from match snapshots
3. XGBoost classifier trained on learned embeddings for matchup adjustment
4. Inference served via REST API with real-time GSI event ingestion

**Production Service**

- TypeScript + Node.js backend API for real-time inference requests
- Docker packaging for consistent deployment across environments
- CI/CD release pipeline with automated regression tests on each build
- GSI server receiving live game state events from Dota 2 client

**Application Modes**

- Browse Mode: select any hero and view recommended builds by game phase (early/mid/late)
- Live Overlay: auto-detects hero and draft via GSI, updates recommendations in real time

## Stack

Python · PyTorch · XGBoost · scikit-learn · TypeScript · Node.js · Docker · GitHub Actions · Pandas · NumPy

## Repository Structure

```
dota2-build-generator/
├── main.py                  # Application entry point
├── logic/
│   ├── ai_recommender.py    # Stats-first recommender with XGBoost matchup adjustment
│   ├── gsi_server.py        # HTTP server receiving Dota2 GSI events
│   ├── gsi_parser.py        # Parses GSI payloads into game state objects
│   └── match_lookup.py      # OpenDota API client
├── ml/
│   ├── embedding_model.py   # PyTorch hero/item embedding model
│   ├── train_embeddings.py  # Embedding training pipeline
│   ├── train_xgboost.py     # XGBoost training on learned embeddings
│   └── data_collector.py    # OpenDota match data collection
├── ui/
│   ├── hero_select.py       # Hero selection grid
│   ├── build_view.py        # Item build display by game phase
│   └── overlay.py           # Live in-game overlay window
├── tests/                   # Automated regression tests
└── models/                  # Trained model checkpoints (not tracked in git)
```

## Setup

```bash
pip install torch xgboost scikit-learn pandas numpy customtkinter requests
```

To enable the live overlay, configure Dota 2 Game State Integration by pointing it to the local GSI server (auto-configured via `logic/gsi_installer.py`).

## Running

```bash
# Browse mode
python main.py

# The GSI server starts automatically when the overlay is launched
```
