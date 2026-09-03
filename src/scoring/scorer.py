"""Emerging skill scoring engine.

Computes the Emerging Skill Score from normalized evidence components:
- Demand growth: 30%
- Hiring/job-posting frequency: 25%
- Cross-industry spread: 15%
- Cross-country spread: 10%
- Employer/research evidence: 10%
- Recency: 5%
- Source reliability: 5%
"""
from datetime import datetime, timedelta
from typing import Optional
from src.calc import calculate_yoy, calculate_mom
from src.database import db
from src.database.db import get_connection, get_evidence_for_skill, get_daily_scores


DEFAULT_WEIGHTS = {
    "demand_growth": 0.30,
    "hiring_frequency": 0.25,
    "cross_industry": 0.15,
    "cross_country": 0.10,
    "employer_evidence": 0.10,
    "recency": 0.05,
    "source_reliability": 0.05,
}


class EmergingSkillScore:
    def __init__(self, weights: Optional[dict] = None):
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.components: dict = {}

    def score(self, skill_id: str, evidence: list[dict]) -> float:
        """Compute the emerging skill score for a skill."""
        if not evidence:
            return 0.0

        components = {
            "demand_growth": self._demand_growth(evidence),
            "hiring_frequency": self._hiring_frequency(evidence),
            "cross_industry": self._cross_industry(evidence),
            "cross_country": self._cross_country(evidence),
            "employer_evidence": self._employer_evidence(evidence),
            "recency": self._recency(evidence),
            "source_reliability": self._source_reliability(evidence),
        }
        self.components = components

        total = 0.0
        for key, weight in self.weights.items():
            total += components.get(key, 0.0) * weight

        return round(min(max(total, 0.0), 1.0), 4)

    def _normalize(self, value: float, max_value: float) -> float:
        if max_value <= 0:
            return 0.0
        return min(max(value / max_value, 0.0), 1.0)

    def _demand_growth(self, evidence: list[dict]) -> float:
        """Score based on YoY/MoM growth evidence."""
        numerical = [e for e in evidence if e.get("value") is not None]
        if not numerical:
            # Use observation volume as a proxy
            return self._normalize(len(evidence), 20.0) * 0.5

        current_year = str(datetime.now().year)
        current = [e for e in numerical if e["period"][:4] == current_year]
        prev = [e for e in numerical if e["period"][:4] != current_year]

        if current and prev:
            current_val = sum(e["value"] for e in current)
            prev_val = sum(e["value"] for e in prev)
            yoy = calculate_yoy(current_val, prev_val)
            if yoy is not None:
                if yoy >= 100:
                    return 1.0
                if yoy > 0:
                    return self._normalize(yoy, 100.0)
                return 0.2  # declining

        return self._normalize(len(evidence), 20.0) * 0.5

    def _hiring_frequency(self, evidence: list[dict]) -> float:
        """Score based on evidence claiming hiring/job-posting frequency."""
        hiring_evidence = [
            e for e in evidence
            if any(kw in e.get("metric", "").lower() for kw in
                   ["mention_frequency", "demand", "hiring", "job"] )
        ]
        if not hiring_evidence:
            return 0.0
        freq = sum(1 for e in hiring_evidence)
        return self._normalize(freq, 5.0)

    def _cross_industry(self, evidence: list[dict]) -> float:
        """Score based on number of distinct industries covered."""
        industries = set(e["industry"] for e in evidence if e.get("industry"))
        return self._normalize(len(industries), 5.0)

    def _cross_country(self, evidence: list[dict]) -> float:
        """Score based on number of distinct geographies covered."""
        countries = set(e["geography"] for e in evidence if e.get("geography"))
        return self._normalize(len(countries), 5.0)

    def _employer_evidence(self, evidence: list[dict]) -> float:
        """Score based on Tier 3 employer/research evidence."""
        tier3 = [e for e in evidence if e.get("source_tier") == 3]
        tier2 = [e for e in evidence if e.get("source_tier") == 2]
        if tier3:
            return 1.0
        if tier2:
            return 0.6
        return 0.0

    def _recency(self, evidence: list[dict]) -> float:
        """Score based on how recent the evidence is."""
        if not evidence:
            return 0.0
        now = datetime.now()
        days_total = 0.0
        count = 0
        for e in evidence:
            date_str = e.get("period", "")
            if len(date_str) >= 7:
                try:
                    d = datetime.strptime(date_str, "%Y-%m")
                    days = (now - d).days
                    days_total += max(days, 0)
                    count += 1
                except ValueError:
                    continue
        if count == 0:
            return 0.0
        avg_days = days_total / count
        # Within last 30 days => 1.0, within 365 => scaled down
        return self._normalize(365 - avg_days, 365.0)

    def _source_reliability(self, evidence: list[dict]) -> float:
        """Score based on source tier quality."""
        if not evidence:
            return 0.0
        tiers = [e.get("source_tier", 4) for e in evidence]
        avg_tier = sum(tiers) / len(tiers)
        # Tier 1 => 1.0, Tier 4 => 0.25
        return 1.0 - ((avg_tier - 1) * 0.25)


def compute_all_scores(conn) -> dict[str, dict]:
    """Compute emerging scores for all tracked skills."""
    skills = db.get_all_skills(conn)
    scorer = EmergingSkillScore()

    results = {}
    for skill in skills:
        evidence = get_evidence_for_skill(conn, skill.skill_id, months=12)
        score = scorer.score(skill.skill_id, evidence)
        results[skill.skill_id] = {
            "skill_id": skill.skill_id,
            "skill_name": skill.skill_name,
            "score": score,
            "components": scorer.components,
            "evidence_count": len(evidence),
            "confidence": _confidence_level(evidence),
        }

    # First-pass: normalize scores against the max observed
    return results


def _confidence_level(evidence: list[dict]) -> str:
    if not evidence:
        return "low"
    tiers = [e.get("source_tier", 4) for e in evidence]
    numerical = sum(1 for e in evidence if e.get("value") is not None)
    avg = sum(tiers) / len(tiers)
    if avg <= 2 and numerical >= 3:
        return "high"
    if avg <= 3 and numerical >= 1:
        return "medium"
    return "low"
