"""Train the draft win-probability model and measure it on a held-out, time-ordered split.

Features for one match, from Radiant's side:

- one value per hero: +1 if it is on Radiant, -1 if on Dire, 0 otherwise;
- ``counter``: mean over Radiant x Dire pairs of vs(r, d) - vs(d, r), in percentage points;
- ``synergy``: mean with(a, b) over Radiant pairs minus the same over Dire pairs;
- ``base``: summed (WR - 0.5) of Radiant heroes minus that of Dire heroes.

The intercept carries the Radiant-side advantage. The matrix features of each training match come from
a matrix built on the *other* folds (out of fold), and test features from a matrix built on the whole
training period, so no feature has seen the result it is used to predict.

Needs numpy and scikit-learn (``pip install -e .[train]``). The output is plain JSON weights, read by
``d2bg.draft.model`` without either library.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from d2bg.pipeline import matchups

FOLDS = 5
TEST_SHARE = 0.2
C_GRID = (0.01, 0.03, 0.1, 0.3, 1.0)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def matrix_features(bucket: Mapping[str, Any], radiant: Sequence[int], dire: Sequence[int]) -> list[float]:
    vs, with_, heroes = bucket["vs"], bucket["with"], bucket["heroes"]

    def get(table: Mapping[str, Any], a: int, b: int) -> float | None:
        v = table.get(str(a), {}).get(str(b))
        return None if v is None else float(v)

    counter = []
    for r in radiant:
        for d in dire:
            a, b = get(vs, r, d), get(vs, d, r)
            if a is not None and b is not None:
                counter.append(a - b)

    def syn(team: Sequence[int]) -> float:
        vals = [v for a in team for b in team if a != b if (v := get(with_, a, b)) is not None]
        return _mean(vals)

    def base(team: Sequence[int]) -> float:
        return sum(float(heroes[str(h)]["wr"]) - 0.5 for h in team if str(h) in heroes)

    return [_mean(counter), syn(radiant) - syn(dire), 100 * (base(radiant) - base(dire))]


FEATURE_NAMES = ("counter", "synergy", "base")


def _design(
    matches: Sequence[Mapping[str, Any]], buckets: Sequence[Mapping[str, Any]], hero_index: Mapping[int, int]
) -> Any:
    import numpy as np

    x = np.zeros((len(matches), len(hero_index) + len(FEATURE_NAMES)))
    for i, (m, bucket) in enumerate(zip(matches, buckets, strict=True)):
        for h in m["radiant"]:
            if h in hero_index:
                x[i, hero_index[h]] = 1.0
        for h in m["dire"]:
            if h in hero_index:
                x[i, hero_index[h]] = -1.0
        x[i, len(hero_index) :] = matrix_features(bucket, m["radiant"], m["dire"])
    return x


def _metrics(y: Any, p: Any) -> dict[str, float]:
    import numpy as np
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    return {
        "accuracy": round(float(np.mean((p >= 0.5) == (y == 1))), 4),
        "log_loss": round(float(log_loss(y, p, labels=[0, 1])), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "auc": round(float(roc_auc_score(y, p)), 4),
    }


def train(
    matches: Sequence[Mapping[str, Any]],
    hero_ids: Sequence[int],
    k: float = matchups.SMOOTHING_K,
    min_pair_games: int = matchups.MIN_PAIR_GAMES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    rows = sorted((m for m in matches if m.get("radiant") and m.get("dire")), key=lambda m: m["match_id"])
    if len(rows) < 200:
        raise ValueError(f"need at least 200 matches to train, got {len(rows)}")
    split = int(len(rows) * (1 - TEST_SHARE))
    train_rows, test_rows = rows[:split], rows[split:]
    hero_index = {h: i for i, h in enumerate(sorted(hero_ids))}

    # Out-of-fold matrix features for training rows.
    fold_of = [i % FOLDS for i in range(len(train_rows))]
    fold_buckets = []
    for f in range(FOLDS):
        others = [m for m, g in zip(train_rows, fold_of, strict=True) if g != f]
        fold_buckets.append(matchups.compute_bucket(others, k, min_pair_games))
    train_buckets = [fold_buckets[g] for g in fold_of]
    full_bucket = matchups.compute_bucket(train_rows, k, min_pair_games)

    x_train = _design(train_rows, train_buckets, hero_index)
    y_train = np.array([int(m["radiant_win"]) for m in train_rows])
    x_test = _design(test_rows, [full_bucket] * len(test_rows), hero_index)
    y_test = np.array([int(m["radiant_win"]) for m in test_rows])

    # Pick C on the last 20% of the training period, then refit on all of it.
    inner = int(len(train_rows) * 0.8)
    best_c, best_loss = C_GRID[0], math.inf
    for c in C_GRID:
        clf = LogisticRegression(C=c, max_iter=2000)
        clf.fit(x_train[:inner], y_train[:inner])
        loss = _metrics(y_train[inner:], clf.predict_proba(x_train[inner:])[:, 1])["log_loss"]
        if loss < best_loss:
            best_c, best_loss = c, loss
    clf = LogisticRegression(C=best_c, max_iter=2000)
    clf.fit(x_train, y_train)
    p_test = clf.predict_proba(x_test)[:, 1]

    heroes_only = LogisticRegression(C=best_c, max_iter=2000)
    heroes_only.fit(x_train[:, : len(hero_index)], y_train)
    p_heroes = heroes_only.predict_proba(x_test[:, : len(hero_index)])[:, 1]

    radiant_rate = float(y_train.mean())
    p_base = np.full(len(y_test), radiant_rate)
    coef = clf.coef_[0]
    report = {
        "n_train": len(train_rows),
        "n_test": len(test_rows),
        "split": "time-ordered by match_id, newest 20% held out",
        "C": best_c,
        "train_radiant_win_rate": round(radiant_rate, 4),
        "test": _metrics(y_test, p_test),
        "test_heroes_only": _metrics(y_test, p_heroes),
        "test_baseline_radiant_rate": _metrics(y_test, p_base)
        | {"accuracy": round(float(np.mean(y_test == int(radiant_rate >= 0.5))), 4)},
        "first_match_id": rows[0]["match_id"],
        "last_match_id": rows[-1]["match_id"],
    }
    model = {
        "version": 1,
        "intercept": round(float(clf.intercept_[0]), 6),
        "hero_weights": {str(h): round(float(coef[i]), 6) for h, i in hero_index.items()},
        "feature_weights": {
            name: round(float(coef[len(hero_index) + j]), 6) for j, name in enumerate(FEATURE_NAMES)
        },
        "report": report,
    }
    return model, report
