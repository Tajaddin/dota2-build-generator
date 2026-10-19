"""Draft win probability from the JSON weights written by ``pipeline.train_draft``. Pure Python."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from d2bg.pipeline.train_draft import FEATURE_NAMES, matrix_features


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class WinModel:
    def __init__(self, doc: Mapping[str, Any]) -> None:
        self.intercept = float(doc["intercept"])
        self.hero_weights = {int(h): float(w) for h, w in doc["hero_weights"].items()}
        self.feature_weights = {k: float(v) for k, v in doc["feature_weights"].items()}
        self.report: Mapping[str, Any] = doc.get("report", {})

    def predict(
        self, radiant: Sequence[int], dire: Sequence[int], bucket: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Radiant's win probability and what moved it.

        ``contributions`` are in log-odds; ``matchups`` is the summed effect of the matrix features.
        """
        contributions: list[dict[str, Any]] = [
            {"hero": h, "side": "radiant", "logit": round(self.hero_weights.get(h, 0.0), 4)} for h in radiant
        ] + [{"hero": h, "side": "dire", "logit": round(-self.hero_weights.get(h, 0.0), 4)} for h in dire]
        feats = matrix_features(bucket, radiant, dire) if radiant and dire else [0.0] * len(FEATURE_NAMES)
        feature_logits = {
            n: self.feature_weights.get(n, 0.0) * v for n, v in zip(FEATURE_NAMES, feats, strict=True)
        }
        z = self.intercept + sum(c["logit"] for c in contributions) + sum(feature_logits.values())
        p = _sigmoid(z)
        return {
            "radiant": round(p, 4),
            "dire": round(1 - p, 4),
            "intercept": round(self.intercept, 4),
            "contributions": sorted(contributions, key=lambda c: -abs(c["logit"])),
            "features": {
                n: {"value": round(v, 3), "logit": round(feature_logits[n], 4)}
                for n, v in zip(FEATURE_NAMES, feats, strict=True)
            },
            "complete": len(radiant) == 5 and len(dire) == 5,
            "held_out_accuracy": (self.report.get("test") or {}).get("accuracy"),
        }
