"""Tests for AI recommender normalization and filtering."""

from logic.ai_recommender import AIRecommender


class _FakeBooster:
    def __init__(self):
        self.params = []

    def set_param(self, params):
        self.params.append(params)


class _FakeEstimator:
    def __init__(self):
        self.device = "cuda"
        self.booster = _FakeBooster()

    def set_params(self, **kwargs):
        self.device = kwargs.get("device", self.device)
        return self

    def get_booster(self):
        return self.booster


class _FakeMultiModel:
    def __init__(self):
        self.estimators_ = [_FakeEstimator(), _FakeEstimator()]


class TestAIRecommender:
    def setup_method(self):
        self.recommender = AIRecommender("data", model_dir="missing-models")

    def test_normalize_hero_name_maps_valve_ids(self):
        assert self.recommender._normalize_hero_name("life_stealer") == "lifestealer"
        assert self.recommender._normalize_hero_name("nevermore") == "shadow_fiend"

    def test_normalize_hero_list_removes_self_and_duplicates(self):
        normalized = self.recommender._normalize_hero_list(
            ["life_stealer", "lifestealer", "zuus", "nevermore"],
            limit=4,
            exclude={"lifestealer"},
        )
        assert normalized == ["zeus", "shadow_fiend"]

    def test_item_filter_blocks_components_support_and_scrolls(self):
        assert not self.recommender._is_valid_phase_item("staff_of_wizardry", "mid")
        assert not self.recommender._is_valid_phase_item("ward_sentry", "mid")
        assert not self.recommender._is_valid_phase_item("tpscroll", "late")
        assert self.recommender._is_valid_phase_item("blink", "mid")

    def test_merge_with_fallback_backfills_to_six_items(self):
        selected = [
            {"item": "phase_boots", "score": 0.7, "note": "AI predicted"},
            {"item": "blink", "score": 0.6, "note": "AI predicted"},
        ]
        fallback = [
            {"item": "armlet"},
            {"item": "desolator"},
            {"item": "black_king_bar"},
            {"item": "assault"},
        ]

        merged, ai_count = self.recommender._merge_with_fallback(selected, fallback)

        assert ai_count == 2
        assert len(merged) == 6
        assert [item["item"] for item in merged[:2]] == ["phase_boots", "blink"]
        assert "assault" in [item["item"] for item in merged]

    def test_force_xgb_cpu_inference_reconfigures_loaded_estimators(self):
        self.recommender._xgb_models = {
            "draft": {"model": _FakeMultiModel()},
            "early": {"model": _FakeMultiModel()},
        }

        self.recommender._force_xgb_cpu_inference()

        for model_data in self.recommender._xgb_models.values():
            for estimator in model_data["model"].estimators_:
                assert estimator.device == "cpu"
                assert estimator.booster.params[-1] == {"device": "cpu"}
