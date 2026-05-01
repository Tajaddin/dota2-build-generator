"""Tests for threat analyzer."""

from logic.threat_analyzer import ThreatAnalyzer


class TestThreatAnalyzer:
    def setup_method(self):
        self.analyzer = ThreatAnalyzer("data")

    def test_analyze_single_magic_hero(self):
        result = self.analyzer.analyze_enemies(["lion"])
        assert "magic_burst" in result["threat_summary"]
        assert result["magic_threat_count"] >= 1
        assert result["disable_count"] >= 1

    def test_analyze_heavy_magic_team(self):
        result = self.analyzer.analyze_enemies(["crystal_maiden", "lion", "tinker"])
        assert result["magic_threat_count"] >= 3
        assert "magic_burst" in result["threat_summary"]

    def test_analyze_gap_closer(self):
        result = self.analyzer.analyze_enemies(["antimage"])
        assert result["gap_closer_count"] >= 1
        assert "gap_closer" in result["threat_summary"]

    def test_analyze_mixed_team(self):
        result = self.analyzer.analyze_enemies(
            ["slardar", "antimage", "crystal_maiden", "lion", "tinker"]
        )
        assert len(result["hero_details"]) >= 5
        assert result["disable_count"] >= 2
        assert result["physical_threat_count"] >= 1
