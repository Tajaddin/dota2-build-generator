"""Full training pipeline: collect -> process -> train embeddings -> train XGBoost."""
import argparse
import sys
from pathlib import Path


def run_full_pipeline(match_count: int = 1000, epochs: int = 20,
                      skip_collect: bool = False, from_file: str | None = None,
                      max_per_day: int | None = None, data_dir: str = "data",
                      embed_sample_frac: float = 1.0, embed_max_samples: int | None = None,
                      embed_val_frac: float = 0.1, embed_seed: int = 13,
                      embed_batch_rows: int = 2048, embed_device: str = "auto",
                      embed_workers: int = 0, embed_prefetch: int = 2,
                      embed_persistent_workers: bool = False,
                      xgb_sample_frac: float = 1.0, xgb_max_samples: int | None = None,
                      xgb_seed: int = 13, xgb_batch_rows: int = 2048, xgb_batch_size: int = 512,
                      xgb_device: str = "auto"):
    """Run the complete training pipeline."""
    print("=" * 60)
    print("DOTA 2 AI TRAINING PIPELINE")
    print("=" * 60)

    raw_dir = "ml/raw_data"
    processed_dir = "ml/processed"
    model_dir = "models"
    matches_file = Path(raw_dir) / "matches.jsonl"

    # Step 1: Collect or import matches
    if from_file:
        print("\n[1/4] Importing match data from file (no API calls)...")
        from ml.import_matches import import_from_file
        import_from_file(from_file, raw_dir)
    elif not skip_collect:
        print("\n[1/4] Collecting match data from OpenDota...")
        from ml.data_collector import OpenDotaCollector
        collector = OpenDotaCollector(raw_dir, data_dir=data_dir)
        collector.collect_matches(target_count=match_count, max_per_day=max_per_day)
    else:
        print("\n[1/4] Skipping collection (--skip-collect). Using existing matches.")

    if not matches_file.exists():
        print("ERROR: No matches.jsonl found. Run without --skip-collect, or use --from-file.")
        sys.exit(1)

    # Step 2: Fetch item ID mapping
    print("\n[2/4] Setting up ID mappings...")
    from ml.id_mapper import IDMapper
    mapper = IDMapper("data")
    print(f"  Heroes: {mapper.num_heroes}, Items: {mapper.num_items}")

    # Step 3: Process into snapshots
    print("\n[3/4] Processing matches into training snapshots...")
    from ml.data_processor import DataProcessor
    processor = DataProcessor("data")
    processor.process_matches(str(matches_file), processed_dir)

    # Step 4: Train embeddings
    print("\n[4a/4] Training neural embeddings...")
    from ml.train_embeddings import train as train_embeddings
    train_embeddings(
        data_dir=processed_dir, model_dir=model_dir, epochs=epochs,
        sample_frac=embed_sample_frac, max_samples=embed_max_samples,
        val_fraction=embed_val_frac, seed=embed_seed, batch_rows=embed_batch_rows,
        device=embed_device, num_workers=embed_workers,
        prefetch_factor=embed_prefetch, persistent_workers=embed_persistent_workers,
    )

    # Step 5: Train XGBoost
    print("\n[4b/4] Training XGBoost decision models...")
    from ml.train_xgboost import train_xgboost
    train_xgboost(
        data_dir=processed_dir, model_dir=model_dir,
        embedding_path=f"{model_dir}/embeddings.pt",
        sample_frac=xgb_sample_frac, max_samples=xgb_max_samples,
        seed=xgb_seed, batch_rows=xgb_batch_rows, batch_size=xgb_batch_size,
        device=xgb_device,
    )

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE!")
    print(f"Models saved to {model_dir}/")
    print("Restart the app to use AI recommendations.")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Train Dota 2 AI recommendation system")
    parser.add_argument("--matches", type=int, default=1000,
                        help="Number of matches to collect (default: 1000)")
    parser.add_argument("--epochs", type=int, default=20,
                        help="Embedding training epochs (default: 20)")
    parser.add_argument("--skip-collect", action="store_true",
                        help="Skip API collection; use existing ml/raw_data/matches.jsonl")
    parser.add_argument("--from-file", type=str, default=None, metavar="PATH",
                        help="Import matches from a JSONL file instead of OpenDota (no API calls)")
    parser.add_argument("--max-per-day", type=int, default=None, metavar="N",
                        help="Cap new API collects at N per day (e.g. 3000 for free tier). Run daily to accumulate.")
    parser.add_argument("--data-dir", type=str, default="data",
                        help="Directory for config.json (opendota_api_key)")
    parser.add_argument("--embed-sample-frac", type=float, default=1.0,
                        help="Embedding train: fraction of rows to use")
    parser.add_argument("--embed-max-samples", type=int, default=None,
                        help="Embedding train: cap rows per split (train/val)")
    parser.add_argument("--embed-val-frac", type=float, default=0.1,
                        help="Embedding train: validation fraction")
    parser.add_argument("--embed-seed", type=int, default=13,
                        help="Embedding train: split seed")
    parser.add_argument("--embed-batch-rows", type=int, default=2048,
                        help="Embedding train: parquet batch rows to read")
    parser.add_argument("--embed-device", type=str, default="auto",
                        help="Embedding train: device auto, cpu, or cuda")
    parser.add_argument("--embed-workers", type=int, default=0,
                        help="Embedding train: DataLoader workers")
    parser.add_argument("--embed-prefetch", type=int, default=2,
                        help="Embedding train: prefetch factor (workers>0)")
    parser.add_argument("--embed-persistent-workers", action="store_true",
                        help="Embedding train: persistent DataLoader workers")
    parser.add_argument("--xgb-sample-frac", type=float, default=1.0,
                        help="XGBoost train: fraction of rows to use")
    parser.add_argument("--xgb-max-samples", type=int, default=None,
                        help="XGBoost train: cap rows to this number per phase")
    parser.add_argument("--xgb-seed", type=int, default=13,
                        help="XGBoost train: split seed")
    parser.add_argument("--xgb-batch-rows", type=int, default=2048,
                        help="XGBoost train: parquet batch rows to read")
    parser.add_argument("--xgb-batch-size", type=int, default=512,
                        help="XGBoost train: embedding batch size")
    parser.add_argument("--xgb-device", type=str, default="auto",
                        help="XGBoost train: device auto, cpu, or cuda")
    args = parser.parse_args()
    run_full_pipeline(
        match_count=args.matches,
        epochs=args.epochs,
        skip_collect=args.skip_collect,
        from_file=args.from_file,
        max_per_day=args.max_per_day,
        data_dir=args.data_dir,
        embed_sample_frac=args.embed_sample_frac,
        embed_max_samples=args.embed_max_samples,
        embed_val_frac=args.embed_val_frac,
        embed_seed=args.embed_seed,
        embed_batch_rows=args.embed_batch_rows,
        embed_device=args.embed_device,
        embed_workers=args.embed_workers,
        embed_prefetch=args.embed_prefetch,
        embed_persistent_workers=args.embed_persistent_workers,
        xgb_sample_frac=args.xgb_sample_frac,
        xgb_max_samples=args.xgb_max_samples,
        xgb_seed=args.xgb_seed,
        xgb_batch_rows=args.xgb_batch_rows,
        xgb_batch_size=args.xgb_batch_size,
        xgb_device=args.xgb_device,
    )


if __name__ == "__main__":
    main()
