# Dota 2 Build Generator

A desktop application that recommends item builds for Dota 2 heroes using machine learning. Combines hero embedding models trained on real match data with a live game state integration (GSI) overlay that updates recommendations in real time as your match progresses.

## Features

- **Browse Mode** — select any hero and instantly view recommended item builds by game phase (early / mid / late), with win-rate and pick-rate statistics pulled from real match data
- **Live Overlay** — connects to Dota 2's Game State Integration (GSI) to auto-detect your hero and enemy draft, then updates item recommendations dynamically as the game evolves
- **ML-Powered Recommendations** — XGBoost classifier trained on neural hero/item embeddings adjusts suggestions based on the enemy draft (counter-item recommendations)
- **Stats-First Approach** — primary recommendations come from aggregated match statistics (item frequency + win rate per hero); the ML model provides matchup-specific adjustments on top

## Tech Stack

- **Python** — application and ML pipeline
- **PyTorch** — hero and item embedding model (trained on match snapshots)
- **XGBoost** — matchup adjustment classifier (trained on hero-item embeddings)
- **scikit-learn** — preprocessing and multi-output classification
- **customtkinter** — modern desktop UI
- **OpenDota API** — real match data collection
- **Pandas / NumPy / PyArrow** — data processing pipeline

## Architecture

```
dota2-build-generator/
├── main.py                  # Application entry point
├── logic/
│   ├── ai_recommender.py    # Stats-first recommender with XGBoost matchup adjustment
│   ├── item_recommender.py  # Base item frequency/winrate recommender
│   ├── gsi_server.py        # HTTP server receiving Dota2 GSI events
│   ├── gsi_parser.py        # Parses GSI payloads into game state objects
│   ├── gsi_installer.py     # Auto-installs GSI config into Dota2 directory
│   ├── threat_analyzer.py   # Analyzes enemy hero threat levels
│   └── match_lookup.py      # OpenDota API client
├── ml/
│   ├── embedding_model.py   # PyTorch hero/item embedding model
│   ├── train_embeddings.py  # Embedding training pipeline
│   ├── train_xgboost.py     # XGBoost training on learned embeddings
│   ├── data_collector.py    # OpenDota match data collection
│   ├── data_processor.py    # Feature engineering and dataset construction
│   └── kaggle_ingest.py     # Bulk match ingestion from Kaggle datasets
├── ui/
│   ├── hero_select.py       # Hero selection grid with search
│   ├── build_view.py        # Item build display by game phase
│   └── overlay.py           # Live in-game overlay window
├── data/                    # Match statistics and hero/item metadata
├── models/                  # Trained model checkpoints (not tracked in git)
└── tests/                   # Unit tests
```

## ML Pipeline

### 1. Data Collection
Match data is collected from the OpenDota API and Kaggle public datasets. Each match record includes hero picks, item purchase logs with timestamps, and match outcome.

### 2. Embedding Model (PyTorch)
A custom embedding model learns dense vector representations for each hero and item combination. Two encoders are trained:
- **Draft encoder** — encodes hero lineup (5v5 picks) for pre-game recommendations
- **Live encoder** — encodes hero lineup + current item inventories for mid-game recommendations

### 3. XGBoost Classifier
A multi-output XGBoost classifier is trained on the frozen embeddings to predict which items are effective given the current draft context. Provides per-item score adjustments on top of the base frequency statistics.

### 4. Stats Aggregation
`hero_item_stats.json` is built from raw match data and stores per-hero item frequencies, win rates, and purchase timing — used as the primary recommendation source.

## Installation

```bash
# Clone the repository
git clone https://github.com/tajaddin-gafarov/dota2-build-generator.git
cd dota2-build-generator

# Install dependencies
pip install -r requirements.txt
```

**Requirements:** Python 3.10+, CUDA-capable GPU recommended for model training (CPU inference is supported)

## Usage

### Browse Mode
```bash
python main.py
```
Click **Browse Builds**, select a hero, and view recommended items organized by game phase.

### Live Overlay
1. Run the app and click **Live Overlay**
2. The app auto-installs the GSI config into your Dota 2 directory (requires Steam path detection)
3. Launch Dota 2 and start a match — the overlay will auto-detect your hero and update recommendations live

### Training Your Own Model
```bash
# Collect match data
python ml/data_collector.py

# Train embeddings
python ml/train_embeddings.py

# Train XGBoost on embeddings
python ml/train_xgboost.py

# Build hero item stats
python ml/build_hero_stats.py
```

## Results

Models trained on 500K+ parsed matches from OpenDota:
- Hero embedding model converges within ~10 epochs on match snapshot data
- XGBoost matchup classifier achieves measurable improvement over frequency-only baseline on held-out matches
- Live overlay latency: <100ms from GSI event to UI update

## License

MIT
