"""Train the hero/item embedding model from match snapshots."""
from pathlib import Path
from contextlib import nullcontext

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset, IterableDataset

from ml.embedding_model import DotaEmbeddingModel
from ml.id_mapper import IDMapper

SNAPSHOT_COLUMNS = [
    "hero_id",
    "ally_heroes",
    "enemy_heroes",
    "ally_items",
    "enemy_items",
    "my_items",
    "label_items",
    "game_time",
    "weight",
]


class SnapshotRowParser:
    """Convert a snapshot row into model tensors."""

    def __init__(self, max_hero_id: int, max_item_id: int, id_mapper: IDMapper):
        self.max_hero_id = max_hero_id
        self.max_item_id = max_item_id
        self.mapper = id_mapper

    def _pad_list(self, lst, length, pad_val=0):
        """Pad or truncate a list to fixed length."""
        # pandas can store lists, numpy arrays or NaN in these columns.
        # Avoid using truthiness on arrays/Series (ambiguous in NumPy).
        if lst is None or (isinstance(lst, float) and np.isnan(lst)):
            values = []
        elif isinstance(lst, (list, tuple)):
            values = list(lst)
        elif isinstance(lst, (np.ndarray, pd.Series)):
            values = lst.tolist()
        else:
            # Single scalar value - treat as one-element list
            values = [lst]

        if len(values) >= length:
            return values[:length]
        return values + [pad_val] * (length - len(values))

    def _item_name_to_id(self, name):
        """Convert item name string to numeric ID, clamped to valid range."""
        if isinstance(name, (int, float)):
            return min(int(name), self.max_item_id)
        item_id = self.mapper.item_name_to_id(str(name))
        return min(item_id, self.max_item_id)

    def parse(self, row):
        """Convert a row (dict/Series) into tensors."""
        row_get = row.get if hasattr(row, "get") else lambda k, d=None: row[k]

        # Hero IDs: [my_hero, ally1-4, enemy1-5]
        hero_id = min(int(row_get("hero_id", 0)), self.max_hero_id)
        allies = self._pad_list(row_get("ally_heroes", []), 5)
        enemies = self._pad_list(row_get("enemy_heroes", []), 5)
        allies = [min(int(h), self.max_hero_id) for h in allies]
        enemies = [min(int(h), self.max_hero_id) for h in enemies]
        hero_ids = torch.tensor([hero_id] + allies[:4] + enemies[:5], dtype=torch.long)

        # Player items (10 players x 6 slots)
        all_player_items = torch.zeros(10, 6, dtype=torch.long)
        ally_items = row_get("ally_items", [])
        enemy_items = row_get("enemy_items", [])
        if isinstance(ally_items, list):
            for pi, items in enumerate(ally_items[:5]):
                if isinstance(items, list):
                    for si, item in enumerate(items[:6]):
                        all_player_items[pi, si] = self._item_name_to_id(item)
        if isinstance(enemy_items, list):
            for pi, items in enumerate(enemy_items[:5]):
                if isinstance(items, list):
                    for si, item in enumerate(items[:6]):
                        all_player_items[5 + pi, si] = self._item_name_to_id(item)

        # My items (6 slots)
        my_items_raw = row_get("my_items", [])
        my_items = torch.zeros(6, dtype=torch.long)
        if isinstance(my_items_raw, list):
            for si, item in enumerate(my_items_raw[:6]):
                my_items[si] = self._item_name_to_id(item)

        # Game time one-hot
        game_time = int(row_get("game_time", 0))
        time_onehot = torch.zeros(3)
        if game_time < 900:
            time_onehot[0] = 1.0  # early
        elif game_time < 1800:
            time_onehot[1] = 1.0  # mid
        else:
            time_onehot[2] = 1.0  # late

        # Label: multi-hot vector of items to buy
        label = torch.zeros(self.max_item_id + 1)
        label_items = row_get("label_items", [])
        if isinstance(label_items, list):
            for item in label_items:
                item_id = self._item_name_to_id(item)
                if 0 < item_id <= self.max_item_id:
                    label[item_id] = 1.0

        # Sample weight
        weight = float(row_get("weight", 0.5))

        return hero_ids, all_player_items, my_items, time_onehot, label, weight


class SnapshotDataset(Dataset):
    """PyTorch dataset for match snapshots (in-memory)."""

    def __init__(self, parquet_path: str, max_hero_id: int, max_item_id: int,
                 id_mapper: IDMapper):
        self.df = pd.read_parquet(parquet_path)
        self.parser = SnapshotRowParser(max_hero_id, max_item_id, id_mapper)

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        return self.parser.parse(row)


def _lcg_rand(index: int, seed: int) -> float:
    """Deterministic pseudo-random in [0,1) based on index."""
    return ((index * 1103515245 + seed) & 0x7fffffff) / float(0x7fffffff)


class ParquetSnapshotIterableDataset(IterableDataset):
    """Streaming dataset that reads Parquet rows in batches."""

    def __init__(self, parquet_files: list[Path], parser: SnapshotRowParser,
                 split: str = "train", val_fraction: float = 0.1, seed: int = 13,
                 sample_frac: float = 1.0, max_samples: int | None = None,
                 batch_rows: int = 2048):
        self.parquet_files = parquet_files
        self.parser = parser
        self.split = split
        self.val_fraction = val_fraction
        self.seed = seed
        self.sample_frac = sample_frac
        self.max_samples = max_samples
        self.batch_rows = batch_rows

    def _accept_row(self, index: int) -> bool:
        if self.val_fraction > 0:
            is_val = _lcg_rand(index, self.seed) < self.val_fraction
            if self.split == "train" and is_val:
                return False
            if self.split == "val" and not is_val:
                return False

        if self.sample_frac < 1.0:
            if _lcg_rand(index, self.seed + 101) >= self.sample_frac:
                return False

        return True

    def __iter__(self):
        row_index = 0
        emitted = 0
        for pq_path in self.parquet_files:
            pf = pq.ParquetFile(pq_path)
            available = set(pf.schema_arrow.names)
            columns = [c for c in SNAPSHOT_COLUMNS if c in available]
            missing = [c for c in SNAPSHOT_COLUMNS if c not in available]

            for batch in pf.iter_batches(batch_size=self.batch_rows, columns=columns):
                data = batch.to_pydict()
                num_rows = batch.num_rows
                if missing:
                    for col in missing:
                        data[col] = [None] * num_rows

                for i in range(num_rows):
                    if not self._accept_row(row_index):
                        row_index += 1
                        continue

                    row = {col: data[col][i] for col in SNAPSHOT_COLUMNS}
                    yield self.parser.parse(row)
                    emitted += 1
                    row_index += 1

                    if self.max_samples is not None and emitted >= self.max_samples:
                        return


def _count_parquet_rows(parquet_files: list[Path]) -> int:
    total = 0
    for pq_path in parquet_files:
        try:
            pf = pq.ParquetFile(pq_path)
            total += pf.metadata.num_rows
        except Exception:
            continue
    return total


def train(data_dir: str = "ml/processed", model_dir: str = "models",
          epochs: int = 20, batch_size: int = 256, lr: float = 1e-3,
          sample_frac: float = 1.0, max_samples: int | None = None,
          val_fraction: float = 0.1, seed: int = 13, batch_rows: int = 2048,
          device: str = "auto", num_workers: int = 0,
          prefetch_factor: int = 2, persistent_workers: bool = False):
    """Train the embedding model."""
    data_path = Path(data_dir)
    model_path = Path(model_dir)
    model_path.mkdir(parents=True, exist_ok=True)

    sample_frac = max(0.0, min(1.0, sample_frac))
    val_fraction = max(0.0, min(1.0, val_fraction))
    if max_samples is not None and max_samples <= 0:
        max_samples = None

    if device == "auto":
        torch_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    elif device == "cuda":
        if torch.cuda.is_available():
            torch_device = torch.device("cuda")
        else:
            print("[Train] CUDA requested but not available; falling back to CPU")
            torch_device = torch.device("cpu")
    else:
        torch_device = torch.device("cpu")

    if torch_device.type == "cuda":
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"[Train] Using GPU: {gpu_name} ({gpu_mem:.1f} GB)")
        torch.backends.cudnn.benchmark = True
        torch.set_float32_matmul_precision("high")
    else:
        print("[Train] Using CPU")

    mapper = IDMapper("data")
    max_hero_id = mapper.max_hero_id
    max_item_id = mapper.max_item_id
    print(f"[Train] Heroes: {mapper.num_heroes} (max_id={max_hero_id}), "
          f"Items: {mapper.num_items} (max_id={max_item_id})")

    # Load all snapshot types (streamed; no full in-memory load)
    all_parquets = sorted(data_path.glob("snapshots_*.parquet"))
    if not all_parquets:
        print("[Train] No snapshot files found. Run data_processor.py first.")
        return

    total_rows = _count_parquet_rows(all_parquets)
    expected_total = int(total_rows * sample_frac) if sample_frac < 1.0 else total_rows
    expected_train = int(expected_total * (1 - val_fraction))
    expected_val = expected_total - expected_train
    if max_samples is not None:
        expected_train = min(expected_train, max_samples)
        expected_val = min(expected_val, max_samples)

    parser = SnapshotRowParser(max_hero_id, max_item_id, mapper)
    train_ds = ParquetSnapshotIterableDataset(
        all_parquets, parser, split="train", val_fraction=val_fraction,
        seed=seed, sample_frac=sample_frac, max_samples=max_samples,
        batch_rows=batch_rows,
    )
    val_ds = ParquetSnapshotIterableDataset(
        all_parquets, parser, split="val", val_fraction=val_fraction,
        seed=seed, sample_frac=sample_frac, max_samples=max_samples,
        batch_rows=batch_rows,
    )

    use_cuda = torch_device.type == "cuda"
    loader_kwargs = {
        "batch_size": batch_size,
        "shuffle": False,
        "num_workers": num_workers,
        "pin_memory": use_cuda,
    }
    if num_workers > 0:
        loader_kwargs["prefetch_factor"] = prefetch_factor
        loader_kwargs["persistent_workers"] = persistent_workers

    train_loader = DataLoader(train_ds, **loader_kwargs)
    val_loader = DataLoader(val_ds, **loader_kwargs)

    print(f"[Train] Files: {len(all_parquets)}")
    print(f"[Train] Rows: total={total_rows}, sample_frac={sample_frac:.2f}, "
          f"val_fraction={val_fraction:.2f}")
    print(f"[Train] Expected (approx): Train={expected_train}, Val={expected_val}")

    # Model
    model = DotaEmbeddingModel(max_hero_id, max_item_id).to(torch_device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.BCEWithLogitsLoss(reduction="none")
    use_amp = torch_device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    best_val_loss = float("inf")

    for epoch in range(epochs):
        # Training
        model.train()
        train_loss = 0.0
        train_samples = 0
        for batch in train_loader:
            hero_ids, player_items, my_items, time_oh, labels, weights = [
                t.to(torch_device, non_blocking=use_cuda) for t in batch
            ]

            optimizer.zero_grad(set_to_none=True)
            amp_ctx = torch.autocast(device_type="cuda", dtype=torch.float16) if use_amp else nullcontext()
            with amp_ctx:
                logits = model(hero_ids, player_items, my_items, time_oh)
                loss_per_sample = criterion(logits, labels).mean(dim=1)  # (batch,)
                weighted_loss = (loss_per_sample * weights).mean()

            scaler.scale(weighted_loss).backward()
            scaler.step(optimizer)
            scaler.update()

            batch_size_actual = hero_ids.size(0)
            train_loss += weighted_loss.item() * batch_size_actual
            train_samples += batch_size_actual

        avg_train = train_loss / max(train_samples, 1)

        # Validation
        model.eval()
        val_loss = 0.0
        val_samples = 0
        with torch.no_grad():
            for batch in val_loader:
                hero_ids, player_items, my_items, time_oh, labels, weights = [
                    t.to(torch_device, non_blocking=use_cuda) for t in batch
                ]
                amp_ctx = torch.autocast(device_type="cuda", dtype=torch.float16) if use_amp else nullcontext()
                with amp_ctx:
                    logits = model(hero_ids, player_items, my_items, time_oh)
                    loss_per_sample = criterion(logits, labels).mean(dim=1)
                batch_size_actual = hero_ids.size(0)
                val_loss += (loss_per_sample * weights).mean().item() * batch_size_actual
                val_samples += batch_size_actual

        if val_samples > 0:
            avg_val = val_loss / val_samples
            val_note = ""
        else:
            avg_val = avg_train
            val_note = " (train proxy)"

        print(f"[Train] Epoch {epoch + 1}/{epochs}  "
              f"train_loss={avg_train:.4f}  val_loss={avg_val:.4f}{val_note}")

        if avg_val < best_val_loss:
            best_val_loss = avg_val
            torch.save({
                "model_state": {k: v.detach().cpu() for k, v in model.state_dict().items()},
                "max_hero_id": max_hero_id,
                "max_item_id": max_item_id,
                "hero_embed_dim": model.hero_embed_dim,
                "item_embed_dim": model.item_embed_dim,
            }, model_path / "embeddings.pt")
            print(f"[Train] Saved best model (val_loss={avg_val:.4f})")

    print(f"[Train] Training complete. Best val_loss={best_val_loss:.4f}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Train Dota 2 embedding model")
    parser.add_argument("--data", default="ml/processed", help="Processed data directory")
    parser.add_argument("--output", default="models", help="Model output directory")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--sample-frac", type=float, default=1.0,
                        help="Fraction of rows to use (e.g., 0.2 for 20%%)")
    parser.add_argument("--max-samples", type=int, default=None,
                        help="Cap rows per split (train/val) to this number")
    parser.add_argument("--val-frac", type=float, default=0.1,
                        help="Fraction of rows reserved for validation")
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--batch-rows", type=int, default=2048,
                        help="Parquet batch rows to load at a time")
    parser.add_argument("--device", type=str, default="auto",
                        help="Training device: auto, cpu, or cuda")
    parser.add_argument("--workers", type=int, default=0,
                        help="DataLoader worker processes")
    parser.add_argument("--prefetch", type=int, default=2,
                        help="Batches prefetched per worker (workers>0)")
    parser.add_argument("--persistent-workers", action="store_true",
                        help="Keep DataLoader workers alive between epochs")
    args = parser.parse_args()
    train(
        args.data, args.output, args.epochs, args.batch_size, args.lr,
        sample_frac=args.sample_frac, max_samples=args.max_samples,
        val_fraction=args.val_frac, seed=args.seed, batch_rows=args.batch_rows,
        device=args.device, num_workers=args.workers,
        prefetch_factor=args.prefetch, persistent_workers=args.persistent_workers,
    )


if __name__ == "__main__":
    main()
