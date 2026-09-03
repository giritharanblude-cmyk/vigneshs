"""Report generator — produces daily markdown report, JSON data, CSV, and run log."""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.models import DashboardData, TrendResult
from src.scoring.scorer import compute_all_scores
from src.database import db
from src.database.db import get_connection

REPORTS_DIR = Path(__file__).parent.parent.parent / "reports" / "daily"
DATA_DIR = Path(__file__).parent.parent.parent / "data"


def generate_daily_report(conn, date_str: str) -> Path:
    """Generate the daily markdown report."""
    from src.analyzers.analyzer import compute_longitudinal_trend

    score_results = compute_all_scores(conn)

    # Convert to TrendResults (with longitudinal metrics) and sort by emerging score
    trends = []
    for skill_id, data in score_results.items():
        if data["evidence_count"] == 0:
            continue
        long = compute_longitudinal_trend(conn, skill_id, date_str)
        trends.append(TrendResult(
            skill_id=skill_id,
            skill_name=data["skill_name"],
            yoy_growth=long.get("yoy_growth"),
            mom_growth=long.get("mom_growth"),
            rolling_12m_change=long.get("rolling_12m_change"),
            skill_share=long.get("skill_share"),
            share_change=long.get("share_change"),
            emerging_score=data["score"],
            confidence=data["confidence"],
        ))
    trends.sort(key=lambda t: t.emerging_score, reverse=True)

    declining = [t for t in trends if t.emerging_score < 0.5]
    rising = [t for t in trends if t.emerging_score >= 0.5]

    lines = [
        "AI SOFT-SKILLS DAILY INTELLIGENCE",
        "=" * 45,
        "",
        f"Date: {date_str}",
        "",
        "TOP EMERGING SKILLS",
        "-" * 20,
    ]

    for i, trend in enumerate(rising[:5], 1):
        growth = f"  YoY {trend.yoy_growth:+.1f}%" if trend.yoy_growth is not None else ""
        rolling = f"  12M {trend.rolling_12m_change:+.1f}%" if trend.rolling_12m_change is not None else ""
        lines.append(f"{i}. {trend.skill_name} - emerging {trend.emerging_score:.3f}{growth}{rolling}")

    lines += ["", "BIGGEST MOVEMENTS", "-" * 17]
    # Genuine period-over-period movements (calculated or observed only).
    movers = sorted(
        [t for t in trends if t.yoy_growth is not None or t.share_change is not None],
        key=lambda t: (t.yoy_growth if t.yoy_growth is not None else t.share_change or 0),
        reverse=True,
    )
    if not movers:
        lines.append("Insufficient period history for reliable YoY/comparison movements yet.")
        lines.append("Figures will appear as longitudinal data accumulates across daily runs.")
    else:
        for trend in movers[:5]:
            if trend.yoy_growth is not None:
                lines.append(f"+ {trend.skill_name}: {trend.yoy_growth:+.1f}% YoY")
            elif trend.share_change is not None:
                lines.append(f"+ {trend.skill_name}: share {trend.share_change:+.1f}pp")
        for trend in movers[-3:]:
            if trend is movers[0]:
                continue
            if trend.yoy_growth is not None:
                lines.append(f"- {trend.skill_name}: {trend.yoy_growth:+.1f}% YoY")
            elif trend.share_change is not None and trend.share_change < 0:
                lines.append(f"- {trend.skill_name}: share {trend.share_change:+.1f}pp")

    lines += ["", "KEY EVIDENCE (counting)", "-" * 23]
    for skill in score_results.values():
        if skill["evidence_count"] > 0:
            lines.append(f"* {skill['skill_name']}: {skill['evidence_count']} evidence records, "
                         f"{skill['confidence']} confidence")

    lines += [
        "",
        "TRAINER IMPLICATION",
        "-" * 18,
        "Focus training on the emerging skills above. Incorporate AI collaboration,",
        "critical thinking, and adaptability exercises into daily sessions.",
        "",
        "DASHBOARD",
        "-" * 8,
        "See the full interactive dashboard for charts and filtering.",
        "",
    ]

    report_dir = REPORTS_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"daily_report_{date_str}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def generate_dashboard_data(conn, date_str: str) -> dict:
    """Generate the JSON data consumed by the HTML dashboard."""
    score_results = compute_all_scores(conn)

    skills = db.get_all_skills(conn)
    evidence_count = sum(s["evidence_count"] for s in score_results.values())

    # Monthly trend data across skills
    from src.analyzers.analyzer import monthly_demand_index
    monthly_data = []
    for skill in skills:
        series = monthly_demand_index(conn, skill.skill_id, months=12)
        if series:
            monthly_data.append({
                "skill": skill.skill_name,
                "series": series,
            })

    # Industry comparison
    all_evidence = conn.execute("""
        SELECT industry, COUNT(*) as cnt FROM evidence
        WHERE industry != '' AND industry IS NOT NULL
        GROUP BY industry ORDER BY cnt DESC
    """).fetchall()
    total_industry = sum(r["cnt"] for r in all_evidence) or 1
    industry_comparison = [
        {"industry": r["industry"], "count": r["cnt"],
         "percentage": round(r["cnt"] / total_industry * 100, 1)}
        for r in all_evidence
    ]

    # Counts
    emerging = [s for s in score_results.values() if s["score"] >= 0.5]
    increasing = [s for s in score_results.values() if s["score"] > 0.3]
    declining = [s for s in score_results.values() if 0 < s["score"] <= 0.3]

    # Longitudinal period-over-period metrics from daily_scores history
    from src.analyzers.analyzer import compute_longitudinal_trend
    long_trends = {}
    for skill in skills:
        long_trends[skill.skill_id] = compute_longitudinal_trend(conn, skill.skill_id, date_str)

    trends = []
    for s in score_results.values():
        long = long_trends.get(s["skill_id"], {})
        if s.get("evidence_count", 0) == 0:
            continue
        trends.append(TrendResult(
            skill_id=s["skill_id"],
            skill_name=s["skill_name"],
            yoy_growth=long.get("yoy_growth"),
            mom_growth=long.get("mom_growth"),
            rolling_12m_change=long.get("rolling_12m_change"),
            skill_share=long.get("skill_share"),
            share_change=long.get("share_change"),
            emerging_score=s["score"],
            evidence_type="calculated",
            confidence=s["confidence"],
        ))
    trends.sort(key=lambda t: t.emerging_score, reverse=True)

    return DashboardData(
        generated_at=datetime.now().isoformat(),
        total_skills=len(skills),
        emerging_skills=len(emerging),
        increasing_skills=len(increasing),
        declining_skills=len(declining),
        new_evidence_items=evidence_count,
        sources_analyzed=conn.execute("SELECT COUNT(*) as c FROM sources").fetchone()["c"],
        industries_tracked=len(db.get_distinct_industries(conn)),
        countries_tracked=len(db.get_distinct_countries(conn)),
        trends=[t for t in trends],
        monthly_data=monthly_data,
        industry_comparison=industry_comparison,
        new_skills_detected=sorted(set(
            t.skill_name for t in trends
            if t.share_change is not None and t.share_change > 0 and t.skill_share is not None
        )),
        evidence_confidence={
            "high": sum(1 for s in score_results.values() if s["confidence"] == "high"),
            "medium": sum(1 for s in score_results.values() if s["confidence"] == "medium"),
            "low": sum(1 for s in score_results.values() if s["confidence"] == "low"),
        },
    ).model_dump()


def write_dashboard_data(data: dict, date_str: str) -> Path:
    """Write dashboard data JSON file."""
    data_dir = DATA_DIR / "processed"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"dashboard_data_{date_str}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_csv_export(conn, date_str: str) -> Path:
    """Write evidence CSV export."""
    rows = conn.execute("""
        SELECT s.skill_name, e.industry, e.geography, e.period, e.metric,
               e.value, e.unit, e.evidence_type, src.organization, src.source_tier
        FROM evidence e
        JOIN skills s ON e.skill_id = s.skill_id
        JOIN sources src ON e.source_id = src.source_id
    """).fetchall()

    data_dir = DATA_DIR / "processed"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"evidence_export_{date_str}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["skill", "industry", "geography", "period", "metric",
                         "value", "unit", "evidence_type", "source", "source_tier"])
        for r in rows:
            writer.writerow([r["skill_name"], r["industry"], r["geography"], r["period"],
                             r["metric"], r["value"], r["unit"], r["evidence_type"],
                             r["organization"], r["source_tier"]])
    return path


def generate_run_log(conn, run_record) -> None:
    """Write run record JSON for reliability auditing."""
    data_dir = DATA_DIR / "historical"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"run_{run_record.run_id}.json"
    path.write_text(json.dumps(run_record.model_dump(), indent=2), encoding="utf-8")
    return path
