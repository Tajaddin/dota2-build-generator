# Training the AI (within free-tier limits)

## Options that avoid or respect API limits

### 1. **OpenDota API key (higher rate limit)**

Put your key in `data/config.json`:

```json
{
  "opendota_api_key": "your-key-here",
  "stratz_token": "..."
}
```

Get a key at [OpenDota API](https://www.opendota.com/api-keys). The collector will use it automatically for higher request limits.

### 2. **Daily cap (e.g. 3000/day free tier)**

Stay under a daily limit by capping how many *new* matches are fetched per day:

```bash
python -m ml.train --matches 5000 --max-per-day 3000
```

Run the same command again on following days; it will add up to 3000 new matches each day until you reach 5000 total. State is stored in `ml/raw_data/.collect_daily.json`.

### 3. **Import from file (no API calls)**

Use a JSONL file of matches (e.g. from Kaggle, bulk dumps, or saved API responses):

```bash
# Import into ml/raw_data/matches.jsonl (skips duplicate match_id)
python -m ml.import_matches path/to/matches.jsonl

# Then train on existing + imported data (skip API collection)
python -m ml.train --skip-collect --epochs 20
```

Or in one go:

```bash
python -m ml.train --from-file path/to/matches.jsonl --epochs 20
```

Each line of the file should be one match in our format or in OpenDota API format (we convert automatically).

### 4. **More snapshots per match (no extra API calls)**

The pipeline now creates training snapshots for **both winning and losing** players. Losers get a lower sample weight (0.35×) but add more variety, so you get roughly twice as many snapshots from the same number of matches.

## Suggested workflow on free tier

- **Option A:** Use `--max-per-day 3000` and run `python -m ml.train --matches 10000 --max-per-day 3000` for several days to build 10k matches.
- **Option B:** Find a Dota 2 match dataset (e.g. Kaggle, or OpenDota bulk dumps), convert to JSONL, then `--from-file` + `--skip-collect` to train without hitting the API.
- **Option C:** Add an OpenDota API key in `data/config.json` if you have one, then run with higher limits.
