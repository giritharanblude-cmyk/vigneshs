"""Trend analysis engine.

Calculates YoY, MoM, rolling 12-month, skill share, and share change metrics.
"""
import pandas as pd
from datetime import datetime
from typing import Optional
from src.database.db import get_connection, get_evidence_for_skill, get_daily_scores
from src.models import TrendResult, EvidenceType, DailyScore
from src.calc import calculate_yoy, calculate_mom, calculate_rolling_change


def calculate_rolling_change_public(latest_12m, prev_12m):
    return calculate_rolling_change(latest_12m, prev_12m)


def demand_index(evidence: list[dict]) -> float:
    """Compute a normalized demand index from evidence records (public)."""
    return _demand_index(evidence)


def _demand_index(evidence: list[dict]) -> float:
    """Compute a normalized demand index from evidence records.

    To keep the index unit-consistent (so that longitudinal ratios and skill
    shares are meaningful rather than false-precision artifacts from mixing
    disparate units like 'thousands of jobs', 'percent', and 'mention count'),
    the demand index is the number of evidence observations for the skill.
    Each evidence record contributes 1.0. This is an honest, reproducible
    'volume of supporting evidence' measure.
    """
    if not evidence:
        return 0.0
    return float(len(evidence))


def _confidence(evidence: list[dict]) -> str:
    """Compute evidence confidence level (high/medium/low)."""
    tiers = [item.get("source_tier", 4) for item in evidence]
    values_present = sum(1 for item in evidence if item.get("value") is not None)

    if not evidence:
        return "low"

    avg_tier = sum(tiers) / len(tiers)
    has_report_date = sum(1 for item in evidence if item.get("period"))

    score = 0
    if avg_tier <= 2:
        score += 2
    elif avg_tier <= 3:
        score += 1

    if values_present > 0:
        score += 2
    if values_present >= 3:
        score += 1
    if has_report_date >= 3:
        score += 1

    if score >= 5:
        return "high"
    elif score >= 3:
        return "medium"
    return "low"


def analyze_trend(evidence: list[dict]) -> TrendResult:
    """Compute trend metrics for a single skill based on evidence."""
    if not evidence:
        return TrendResult(
            skill_id="",
            skill_name="",
            evidence_type=EvidenceType.QUALITATIVE,
            confidence="low",
        )

    skill_id = evidence[0]["skill_id"]

    # Extract metrics by type
    numerical = [e for e in evidence if e.get("value") is not None]
    qualitative = [e for e in evidence if e.get("value") is None]

    # Current metric value (latest period)
    current = 0.0
    if numerical:
        current = sum(e["value"] for e in numerical)

    # Split by date for YoY analysis
    current_period = [e for e in numerical if e.get("period", "")[:4] == str(datetime.now().year)]
    prev_period = [e for e in numerical if e.get("period", "")[:4] == str(datetime.now().year - 1)]

    yoy = None
    if current_period and prev_period:
        current_val = sum(e["value"] for e in current_period)
        prev_val = sum(e["value"] for e in prev_period)
        yoy = calculate_yoy(current_val, prev_val)

    return TrendResult(
        skill_id=skill_id,
        skill_name=_skill_name(skill_id),
        yoy_growth=yoy,
        demand_index=current,
        share=None,
        share_change=None,
        confidence=_confidence(evidence),
        evidence_type=EvidenceType.CALCULATED if numerical else EvidenceType.QUALITATIVE,
    )


def _skill_name(skill_id: str) -> str:
    from src.database import db
    conn = get_connection()
    for skill in db.get_all_skills(conn):
        if skill.skill_id == skill_id:
            conn.close()
            return skill.skill_name
    conn.close()
    return skill_id.replace("_", " ").title()


def compute_skill_share(evidence: list[dict], total_mentions: int) -> Optional[float]:
    """Skill share = skill observations / total relevant observations."""
    if total_mentions <= 0:
        return None
    skill_obs = sum(1 for e in evidence)
    return (skill_obs / total_mentions) * 100


def monthly_demand_index(conn, skill_id: str, months: int = 12) -> list[dict]:
    """Compute monthly demand index series for charting."""
    evidence = get_evidence_for_skill(conn, skill_id, months=months)

    if not evidence:
        return []

    df = pd.DataFrame(evidence)
    if "period" not in df.columns or df.empty:
        return []

    # Convert period to datetime
    df["month"] = pd.to_datetime(df["period"], format="%Y-%m", errors="coerce")
    df = df.dropna(subset=["month"])

    if df.empty:
        return []

    df["value"] = df["value"].apply(lambda v: v if isinstance(v, (int, float)) else 1.0)
    monthly = df.groupby(df["month"].dt.strftime("%Y-%m"))["value"].sum().reset_index()
    monthly.columns = ["month", "demand_index"]
    return monthly.to_dict("records")


def trend_comparison(conn, skill_id: str, current_date: str) -> dict:
    """Compare current evidence with previous period."""
    current = get_evidence_for_skill(conn, skill_id, months=1)
    prev = get_evidence_for_skill(conn, skill_id, months=2)
    prev = [e for e in prev if e["period"] < current_date]

    current_val = sum(e["value"] for e in current if e.get("value") is not None)
    prev_val = sum(e["value"] for e in prev if e.get("value") is not None)

    change = None
    if prev_val > 0:
        change = calculate_mom(current_val, prev_val)

    return {
        "current_value": current_val,
        "previous_value": prev_val,
        "change_pct": change,
        "current_count": len(current),
        "previous_count": len(prev),
    }


def generate_daily_scores_cmd(conn, date_str: str) -> None:
    """Compute and persist daily_scores for all skills."""
    from src.database import db

    skills = db.get_all_skills(conn)

    for skill in skills:
        evidence = get_evidence_for_skill(conn, skill.skill_id, months=12)
        if not evidence:
            continue

        # Demand score
        demand_index = _demand_index(evidence)

        # Trend analysis
        trend = analyze_trend(evidence)

        # Emerging score
        from src.scoring.scorer import EmergingSkillScore
        scorer = EmergingSkillScore()
        emerging = scorer.score(skill.skill_id, evidence)

        score = DailyScore(
            date=date_str,
            skill_id=skill.skill_id,
            demand_score=demand_index,
            growth_rate=trend.yoy_growth,
            emerging_score=emerging,
            confidence=_confidence(evidence),
        )
        db.upsert_daily_score(conn, score)

    conn.commit()


def backfill_historical_scores(conn, months: int = 24) -> int:
    """Seed monthly daily_scores snapshots from real evidence periods.

    The evidence table carries genuine period dates (e.g. World Bank 2023-2025,
    BLS 2026). We aggregate *observation counts* per (skill, month) — a
    unit-consistent measure — and insert a monthly snapshot dated 'YYYY-MM-15'
    so longitudinal windows (MoM, rolling 12M, share) have data from day one.

    Snapshot values derive from observed evidence counts, never fabricated,
    and are idempotent via upsert.

    Returns the number of monthly snapshots written.
    """
    from src.database import db as _db
    import pandas as _pd

    skills = _db.get_all_skills(conn)
    inserted = 0

    for skill in skills:
        evidence = get_evidence_for_skill(conn, skill.skill_id, months=months)
        if not evidence:
            continue

        rows = []
        for e in evidence:
            period = (e.get("period") or "")[:7]
            if len(period) != 7:
                continue
            rows.append({"period": period})

        if not rows:
            continue

        df = _pd.DataFrame(rows)
        df["month"] = _pd.to_datetime(df["period"], format="%Y-%m", errors="coerce")
        df = df.dropna(subset=["month"])
        if df.empty:
            continue

        monthly = df.groupby(df["month"].dt.strftime("%Y-%m")).size()
        for month_key, count in monthly.items():
            try:
                snap_date = _pd.to_datetime(month_key, format="%Y-%m").strftime("%Y-%m-15")
            except Exception:
                continue
            score = DailyScore(
                date=snap_date,
                skill_id=skill.skill_id,
                demand_score=float(count),
                growth_rate=None,
                emerging_score=0.0,
                confidence=_confidence(evidence),
            )
            _db.upsert_daily_score(conn, score)
            inserted += 1

    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Longitudinal metrics derived from the accumulated daily_scores table.
# These give genuine period-over-period comparison (spec sections 6, 19, 22).
# ---------------------------------------------------------------------------

def _avg_score_for_window(conn, skill_id: str, start: str, end: str) -> Optional[float]:
    """Average daily demand_score between two ISO dates (inclusive)."""
    row = conn.execute("""
        SELECT AVG(demand_score) AS avg FROM daily_scores
        WHERE skill_id = ? AND date >= ? AND date < ?
    """, (skill_id, start, end)).fetchone()
    if not row or row["avg"] is None:
        return None
    return float(row["avg"])


def _latest_score(conn, skill_id: str) -> Optional[dict]:
    return dict(conn.execute("""
        SELECT * FROM daily_scores WHERE skill_id = ? AND demand_score > 0
        ORDER BY date DESC LIMIT 1
    """, (skill_id,)).fetchone()) if conn.execute(
        "SELECT 1 FROM daily_scores WHERE skill_id = ? AND demand_score > 0",
        (skill_id,)).fetchone() else None


def _total_share_for_window(conn, start: str, end: str) -> float:
    row = conn.execute("""
        SELECT SUM(demand_score) AS total FROM daily_scores WHERE date >= ? AND date < ?
    """, (start, end)).fetchone()
    return float(row["total"]) if row and row["total"] else 0.0


def compute_longitudinal_trend(conn, skill_id: str, as_of: str) -> dict:
    """Compute period-over-period metrics for a skill.

    MoM / YoY / rolling-12M are derived from *complete-month* observation counts
    (via `_evidence_based_comparison`), which are unit-consistent and exclude the
    partial current month so day-one collection volume is not mistaken for a
    real decline. Skill share is derived from evidence observation counts.
    Returns a dict of metrics, or None where data is insufficient — never
    fabricates a statistic.
    """
    result = {
        "yoy_growth": None,
        "mom_growth": None,
        "rolling_12m_change": None,
        "skill_share": None,
        "share_change": None,
    }

    # Growth / change metrics from complete-month counts
    evidence = get_evidence_for_skill(conn, skill_id, months=24)
    if evidence:
        comparison = _evidence_based_comparison(evidence)
        result["yoy_growth"] = comparison.get("yoy_growth")
        result["mom_growth"] = comparison.get("mom_growth")
        result["rolling_12m_change"] = comparison.get("rolling_12m_change")

    # Skill share (observation-count based). share_change is intentionally left
    # None until genuine evidence older than 12 months accumulates; comparing
    # against a near-empty prior window (spec §20) would fabricate a misleading
    # "everything is rising" signal on day one.
    evidence_12 = get_evidence_for_skill(conn, skill_id, months=12)
    total_all = _evidence_total(conn)
    if evidence_12 and total_all > 0:
        result["skill_share"] = compute_skill_share(evidence_12, total_all)

    # ---- Sanity clamps (spec §7 / §20: never show impossible statistics) ----
    if result["skill_share"] is not None:
        result["skill_share"] = min(max(result["skill_share"], 0.0), 100.0)
    for key in ("mom_growth", "yoy_growth", "rolling_12m_change"):
        v = result.get(key)
        if v is not None:
            if abs(v) > 500.0:
                result[key] = None

    return result


def _evidence_total(conn) -> int:
    """Total evidence observation rows across all skills (for share calc)."""
    row = conn.execute("SELECT COUNT(*) AS c FROM evidence").fetchone()
    return int(row["c"]) if row else 0


def _evidence_based_comparison(evidence: list[dict]) -> dict:
    """Compute YoY/mom/rolling metrics from evidence periods.

    Aggregates numeric evidence values by period and compares adjacent
    periods. Falls back to observation-count growth where no numeric values
    exist (still a *calculated* count-based comparison, never fabricated).
    """
    import pandas as pd

    result = {"yoy_growth": None, "mom_growth": None, "rolling_12m_change": None}

    if not evidence:
        return result

    # Use observation counts (unit-consistent). Each evidence record counts 1.
    rows = []
    for e in evidence:
        period = (e.get("period") or "")[:7]
        if len(period) != 7:
            continue
        rows.append({"period": period})

    if not rows:
        return result

    df = pd.DataFrame(rows)
    df["month"] = pd.to_datetime(df["period"], format="%Y-%m", errors="coerce")
    df = df.dropna(subset=["month"])
    if df.empty:
        return result

    monthly = df.groupby(df["month"].dt.strftime("%Y-%m")).size()

    # Guard against false precision: only report a period comparison when the
    # evidence spans enough distinct *complete* periods with real volume.
    # Comparing a partial trailing month (we only have a few days of it) against
    # a full prior month makes every skill look like it is collapsing, which is
    # not a stable signal (spec §7, §22).
    current_month = datetime.now().strftime("%Y-%m")
    complete = {m: c for m, c in monthly.items() if m != current_month}
    if not complete or len(complete) < 3:
        return result

    # Use only up-to-the-previous-complete-month for MoM to avoid partial-month bias
    months = sorted(complete.keys())

    spans_months = len(months)
    total_obs = len(rows)

    # MoM: compare the two most recent complete months
    if spans_months >= 3 and total_obs >= 6:
        cur = complete[months[-1]]
        prev = complete[months[-2]]
        if prev > 0:
            result["mom_growth"] = calculate_mom(cur, prev)

    # YoY: current complete month vs the same month a year earlier (only if
    # we actually have a 12-month span).
    if spans_months >= 13:
        this = complete[months[-1]]
        # find same month 12 months earlier
        last_month = months[-1]  # e.g. 2026-08
        yy, mm = last_month.split("-")
        target = f"{int(yy) - 1}-{mm}"
        if target in complete:
            prior = complete[target]
            if prior > 0:
                result["yoy_growth"] = calculate_yoy(this, prior)

    # Rolling 12M: newest 12 complete months vs the 12 before them
    if spans_months >= 24 and total_obs >= 12:
        cutoff = len(months) - 12
        latest_win = sum(complete[m] for m in months[cutoff:])
        prior_win = sum(complete[m] for m in months[max(0, cutoff - 12):cutoff])
        if prior_win > 0:
            result["rolling_12m_change"] = calculate_rolling_change(latest_win, prior_win)

    return result
