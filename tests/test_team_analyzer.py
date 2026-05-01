"""Tests for team analyzer."""

from logic.team_analyzer import TeamAnalyzer


class TestTeamAnalyzer:
    def setup_method(self):
        self.analyzer = TeamAnalyzer("data")

    def test_analyze_team_strengths(self):
        result = self.analyzer.analyze_team(["axe", "lion", "tinker", "oracle", "drow_ranger"])
        assert "frontline" in result["has"]
        assert "waveclear" in result["has"]
        assert "save" in result["has"]
        assert "frontline" not in result["gaps"]

    def test_analyze_team_gaps(self):
        result = self.analyzer.analyze_team(["antimage", "drow_ranger", "tinker"])
        assert "frontline" in result["gaps"]
        assert "save" in result["gaps"]

    def test_summary_labels_are_human_readable(self):
        result = self.analyzer.analyze_team(["antimage", "drow_ranger", "tinker"])
        weaknesses = result["summary"]["weaknesses"]
        assert weaknesses
        assert all(w.startswith("No ") for w in weaknesses)
