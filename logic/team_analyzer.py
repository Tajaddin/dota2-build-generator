"""Analyze allied team composition and identify gaps."""
import json
from pathlib import Path


class TeamAnalyzer:
    """Analyzes your team composition for strengths and gaps.

    Reads team_roles.json which defines what capabilities a team needs
    and what each hero provides.
    """

    def __init__(self, data_dir: str):
        data_path = Path(data_dir)
        roles_path = data_path / "team_roles.json"
        if roles_path.exists():
            with open(roles_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._capabilities = data.get("team_capabilities", {})
            self._hero_provides = data.get("hero_provides", {})
        else:
            self._capabilities = {}
            self._hero_provides = {}

    def analyze_team(self, ally_hero_ids: list[str]) -> dict:
        """Analyze team composition and return strengths/gaps.

        Args:
            ally_hero_ids: List of Valve hero IDs for your team

        Returns:
            Dict with 'has' (capabilities present), 'gaps' (missing capabilities),
            and 'summary' (human-readable labels).
        """
        has = set()
        capability_count = {}

        for hero_id in ally_hero_ids:
            provides = self._hero_provides.get(hero_id, [])
            for cap in provides:
                has.add(cap)
                capability_count[cap] = capability_count.get(cap, 0) + 1

        gaps = []
        for cap_id, cap_info in self._capabilities.items():
            count = capability_count.get(cap_id, 0)
            if count < cap_info.get("min_desired", 1):
                gaps.append(cap_id)

        # Build human-readable summary
        has_labels = []
        for h in sorted(has):
            cap_info = self._capabilities.get(h, {})
            label = cap_info.get("label", h.replace("_", " ").title())
            has_labels.append(label)

        gap_labels = []
        for g in gaps:
            cap_info = self._capabilities.get(g, {})
            label = cap_info.get("label", g.replace("_", " ").title())
            gap_labels.append(f"No {label}")

        return {
            "has": list(has),
            "gaps": gaps,
            "capability_counts": capability_count,
            "summary": {
                "strengths": has_labels,
                "weaknesses": gap_labels,
            }
        }
