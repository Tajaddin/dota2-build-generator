"""Train XGBoost models using neural embeddings + tactical features."""
from pathlib import Path
import pickle

import numpy as np
import pyarrow.parquet as pq
import torch
import xgboost as xgb
from sklearn.multioutput import MultiOutputClassifier

from ml.embedding_model import DotaEmbeddingModel
from ml.id_mapper import IDMapper
from ml.train_embeddings import ParquetSnapshotIterableDataset, SnapshotRowParser


def load_embedding_model(model_path: str) -> DotaEmbeddingModel:
    """Load a trained embedding model."""
    checkpoint = torch.load(model_path, map_location="cpu", weights_only=True)
    model = DotaEmbeddingModel(
        num_heroes=checkpoint["max_hero_id"],
        num_items=checkpoint["max_item_id"],
        hero_embed_dim=checkpoint.get("hero_embed_dim", 64),
        item_embed_dim=checkpoint.get("item_embed_dim", 32),
    )
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    return model


def _count_parquet_rows(pq_path: Path) -> int:
    try:
        pf = pq.ParquetFile(pq_path)
        return pf.metadata.num_rows
    except Exception:
        return 0


def collect_training_data(model: DotaEmbeddingModel, dataset,
                          batch_size: int = 512):
    """Encode snapshots and collect labels/weights."""
    loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=False)
    all_embeddings = []
    all_labels = []
    all_weights = []

    with torch.no_grad():
        for batch in loader:
            hero_ids, player_items, my_items, time_oh, labels, weights = batch
            # Use live encoder for snapshots with items, draft encoder otherwise
            has_items = player_items.sum(dim=(1, 2)) > 0
            embeddings = torch.zeros(hero_ids.size(0), 256)

            if has_items.any():
                live_ctx = model.encode_live(
                    hero_ids[has_items], player_items[has_items],
                    my_items[has_items], time_oh[has_items]
                )
                embeddings[has_items] = live_ctx

            if (~has_items).any():
                draft_ctx = model.encode_draft(hero_ids[~has_items])
                embeddings[~has_items, :128] = draft_ctx

            all_embeddings.append(embeddings.numpy().astype(np.float32, copy=False))
            all_labels.append(labels.numpy().astype(np.uint8, copy=False))
            all_weights.append(weights.numpy().astype(np.float32, copy=False))

    if not all_embeddings:
        return (
            np.empty((0, 256), dtype=np.float32),
            np.empty((0, 1), dtype=np.uint8),
            np.empty((0,), dtype=np.float32),
        )

    return (
        np.concatenate(all_embeddings, axis=0),
        np.concatenate(all_labels, axis=0),
        np.concatenate(all_weights, axis=0),
    )


def _build_xgb_params(use_gpu: bool) -> dict:
    params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": 6,
        "learning_rate": 0.1,
        "n_estimators": 200,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "tree_method": "hist",
        "n_jobs": -1,
    }
    if use_gpu:
        params["device"] = "cuda"
    return params


def _gpu_supported() -> bool:
    """Quick probe to see if this XGBoost build supports GPU."""
    try:
        dtrain = xgb.DMatrix(np.random.rand(10, 4), label=np.random.randint(0, 2, size=10))
        xgb.train(
            {
                "tree_method": "hist",
                "device": "cuda",
                "max_depth": 2,
                "eval_metric": "logloss",
                "objective": "binary:logistic",
            },
            dtrain,
            num_boost_round=1,
        )
        return True
    except xgb.core.XGBoostError as e:
        print(f"[XGBoost] GPU probe failed: {e}")
        return False
    except Exception as e:
        print(f"[XGBoost] GPU probe error: {e}")
        return False


def train_xgboost(data_dir: str = "ml/processed", model_dir: str = "models",
                  embedding_path: str = "models/embeddings.pt",
                  sample_frac: float = 1.0, max_samples: int | None = None,
                  seed: int = 13, batch_rows: int = 2048, batch_size: int = 512,
                  device: str = "auto", xgb_jobs: int = 1):
    """Train XGBoost models for item recommendation per game phase."""
    data_path = Path(data_dir)
    model_path = Path(model_dir)
    model_path.mkdir(parents=True, exist_ok=True)

    sample_frac = max(0.0, min(1.0, sample_frac))
    if max_samples is not None and max_samples <= 0:
        max_samples = None

    mapper = IDMapper("data")
    embedder = load_embedding_model(embedding_path)
    max_hero_id = mapper.max_hero_id
    max_item_id = mapper.max_item_id

    if device == "auto":
        use_gpu = torch.cuda.is_available() and _gpu_supported()
    elif device == "cuda":
        if not torch.cuda.is_available():
            print("[XGBoost] CUDA requested but not available; falling back to CPU")
            use_gpu = False
        else:
            use_gpu = _gpu_supported()
            if not use_gpu:
                print("[XGBoost] CUDA requested but this XGBoost build has no GPU support; falling back to CPU")
    else:
        use_gpu = False

    if use_gpu:
        print("[XGBoost] Using GPU (device=cuda)")
    else:
        print("[XGBoost] Using CPU")

    phases = ["draft", "early", "mid", "late"]

    for phase in phases:
        pq_file = data_path / f"snapshots_{phase}.parquet"
        if not pq_file.exists():
            print(f"[XGBoost] No data for {phase}, skipping")
            continue

        print(f"\n[XGBoost] Training {phase} model...")
        total_rows = _count_parquet_rows(pq_file)
        expected_rows = int(total_rows * sample_frac) if sample_frac < 1.0 else total_rows
        if max_samples is not None:
            expected_rows = min(expected_rows, max_samples)

        parser = SnapshotRowParser(max_hero_id, max_item_id, mapper)
        dataset = ParquetSnapshotIterableDataset(
            [pq_file], parser,
            split="train", val_fraction=0.0,
            seed=seed, sample_frac=sample_frac, max_samples=max_samples,
            batch_rows=batch_rows,
        )

        # Encode through embeddings + collect labels/weights
        embeddings, labels, weights = collect_training_data(
            embedder, dataset, batch_size=batch_size
        )

        if embeddings.shape[0] == 0:
            print(f"[XGBoost] {phase}: no samples after filtering, skipping")
            continue

        print(f"[XGBoost] {phase}: {embeddings.shape[0]} samples "
              f"(expected~{expected_rows}), embedding dim={embeddings.shape[1]}")

        # Split train/val
        n = len(embeddings)
        rng = np.random.default_rng(seed)
        idx = rng.permutation(n)
        split = int(0.9 * n)
        if split <= 0:
            split = max(1, n - 1)
        if split >= n:
            split = n - 1 if n > 1 else n
        train_idx, val_idx = idx[:split], idx[split:]

        X_train = embeddings[train_idx]
        y_train = labels[train_idx]
        w_train = weights[train_idx]

        X_val = embeddings[val_idx] if len(val_idx) else None
        y_val = labels[val_idx] if len(val_idx) else None

        if X_train.shape[0] == 0:
            print(f"[XGBoost] {phase}: not enough samples to train, skipping")
            continue

        # Train one XGBoost model (multi-label via multi-output regression)
        params = _build_xgb_params(use_gpu)

        # Train a model for the top 100 most common items in this phase
        item_freq = y_train.sum(axis=0)
        top_items = np.argsort(item_freq)[-100:]  # Top 100 items by frequency

        y_train_top = y_train[:, top_items]
        y_val_top = y_val[:, top_items] if y_val is not None else None

        # Use MultiOutputClassifier approach via XGBoost's native multi-output
        multi_model = MultiOutputClassifier(
            xgb.XGBClassifier(**params),
            n_jobs=xgb_jobs
        )
        try:
            multi_model.fit(X_train, y_train_top, sample_weight=w_train)
        except xgb.core.XGBoostError as e:
            if use_gpu:
                print(f"[XGBoost] GPU training failed: {e}")
                print("[XGBoost] Falling back to CPU for this phase")
                params = _build_xgb_params(False)
                multi_model = MultiOutputClassifier(
                    xgb.XGBClassifier(**params),
                    n_jobs=xgb_jobs
                )
                multi_model.fit(X_train, y_train_top, sample_weight=w_train)
            else:
                raise

        # Evaluate
        if X_val is not None and y_val_top is not None and len(X_val):
            y_pred = multi_model.predict_proba(X_val)
            # Calculate mean accuracy (top-5 hit rate)
            hits = 0
            total = 0
            for i in range(len(X_val)):
                true_items = set(np.where(y_val_top[i] > 0)[0])
                if not true_items:
                    continue
                pred_scores = np.array([p[i][1] if len(p[i]) > 1 else 0 for p in y_pred])
                top5_pred = set(np.argsort(pred_scores)[-5:])
                hits += len(true_items & top5_pred)
                total += len(true_items)

            accuracy = hits / max(total, 1)
            print(f"[XGBoost] {phase} top-5 hit rate: {accuracy:.2%}")
        else:
            print(f"[XGBoost] {phase} validation skipped (insufficient samples)")

        # Save model and item mapping
        save_data = {
            "model": multi_model,
            "top_item_indices": top_items.tolist(),
            "max_hero_id": max_hero_id,
            "max_item_id": max_item_id,
            "phase": phase,
        }
        out_file = model_path / f"xgb_{phase}.pkl"
        with open(out_file, "wb") as f:
            pickle.dump(save_data, f)
        print(f"[XGBoost] Saved {phase} model to {out_file}")

    print("\n[XGBoost] All models trained!")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Train XGBoost models")
    parser.add_argument("--data", default="ml/processed")
    parser.add_argument("--models", default="models")
    parser.add_argument("--embeddings", default="models/embeddings.pt")
    parser.add_argument("--sample-frac", type=float, default=1.0)
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--batch-rows", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--device", type=str, default="auto",
                        help="Training device: auto, cpu, or cuda")
    parser.add_argument("--xgb-jobs", type=int, default=1,
                        help="MultiOutputClassifier parallel jobs (1 avoids joblib spawn issues)")
    args = parser.parse_args()
    train_xgboost(
        args.data, args.models, args.embeddings,
        sample_frac=args.sample_frac, max_samples=args.max_samples,
        seed=args.seed, batch_rows=args.batch_rows, batch_size=args.batch_size,
        device=args.device, xgb_jobs=args.xgb_jobs,
    )


if __name__ == "__main__":
    main()
