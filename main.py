"""Main pipeline orchestrator — ties together collectors, validators, analyzers, scoring, reporting, email."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.config import load_config
from src.database import db
from src.database.db import get_connection, init_db
from src.collectors.collector import collect_all
from src.validators.validator import validate_db, detect_duplicates
from src.analyzers.analyzer import generate_daily_scores_cmd
from src.scoring.scorer import compute_all_scores
from src.reporting.reporter import (
    generate_daily_report,
    generate_dashboard_data,
    write_dashboard_data,
    write_csv_export,
    generate_run_log,
)
from src.models import RunRecord

PROJECT_ROOT = Path(__file__).parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DASHBOARD_SRC = PROJECT_ROOT / "dashboard"


def bootstrap(conn) -> None:
    """Load skills taxonomy into DB."""
    config = load_config(CONFIG_DIR)
    from src.models import Skill
    for skill in config.get_skills():
        db.upsert_skill(conn, Skill(
            skill_id=skill["id"],
            skill_name=skill["name"],
            category=skill["category"],
            description=skill.get("description", ""),
        ))


def run_pipeline(send_email: bool = True) -> dict:
    """Execute the full research pipeline."""
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%d-%H%M%S") + f"-{uuid4().hex[:6]}"

    print(f"=== Soft-Skill AI Trends Pipeline ===")
    print(f"Run ID: {run_id}")

    conn = get_connection()
    init_db(conn)

    # Load skills taxonomy
    config = load_config(CONFIG_DIR)
    from src.models import Skill
    for skill in config.get_skills():
        db.upsert_skill(conn, Skill(
            skill_id=skill["id"],
            skill_name=skill["name"],
            category=skill["category"],
            description=skill.get("description", ""),
        ))

    run_record = RunRecord(
        run_id=run_id,
        started_at=started.isoformat(),
        skills_tracked=len(config.get_skills()),
    )

    try:
        # Step 1-2: Collect + dedup
        collect_stats = collect_all(conn)
        run_record.sources_checked = collect_stats.get("sources_checked", 0)
        run_record.sources_accepted = collect_stats.get("sources_accepted", 0)
        run_record.records_processed = collect_stats.get("evidence_items", 0)
        run_record.errors = collect_stats.get("errors", [])

        # Step 3-5: Validate
        validation = validate_db(conn)
        run_record.sources_accepted = validation.accepted
        run_record.sources_rejected = validation.rejected
        run_record.errors.extend(validation.issues)

        dupes = detect_duplicates(conn)
        if dupes:
            print(f"  Found {len(dupes)} duplicate source/skill/metric groups")

        # Step 5-6: Generate scores
        print("  Generating daily scores for all skills...")
        generate_daily_scores_cmd(conn, datetime.now(timezone.utc).strftime("%Y-%m-%d"))

        # Step 6.5: Seed historical monthly snapshots (derived from real evidence
        # periods) so longitudinal YoY/rolling windows have data from day one.
        from src.analyzers.analyzer import backfill_historical_scores
        snaps = backfill_historical_scores(conn)
        print(f"  Historical monthly snapshots written: {snaps}")

        # Step 7: Compare / build dashboard data
        print("  Building dashboard data...")
        today = started.strftime("%Y-%m-%d")
        dashboard_data = generate_dashboard_data(conn, today)
        write_dashboard_data(dashboard_data, today)

        # CSV export
        write_csv_export(conn, today)

        # Step 8: Generate daily report
        print("  Generating daily report...")
        report_path = generate_daily_report(conn, today)

        # Step 9: Update dashboard
        update_dashboard_html(dashboard_data)

        # Step 10: Notify
        if send_email:
            from src.reporting.emailer import send_daily_email
            recipient = os.getenv("RECIPIENT_EMAIL",
                        config.pipeline.get("pipeline", {}).get("email", {}).get("recipient",
                        "vksk416@gmail.com"))
            send_daily_email(today, report_path, recipient)

        completed = datetime.now(timezone.utc)
        run_record.completed_at = completed.isoformat()
        generate_run_log(conn, run_record)

        print(f"=== Pipeline completed in {(completed - started).total_seconds():.1f}s ===")
        return run_record.model_dump()

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        run_record.errors.append(str(e))
        run_record.completed_at = datetime.now(timezone.utc).isoformat()
        generate_run_log(conn, run_record)
        return run_record.model_dump()
    finally:
        conn.close()


def update_dashboard_html(dashboard_data: dict) -> None:
    """Regenerate dashboard HTML with current data."""
    from pathlib import Path
    import json as _json

    out_dir = DATA_DIR / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "dashboard_data.json"
    out_path.write_text(_json.dumps(dashboard_data, indent=2), encoding="utf-8")
    print(f"  Dashboard data written to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Soft-Skill AI Trends Intelligence Platform")
    parser.add_argument("--no-email", action="store_true", help="Skip email sending")
    parser.add_argument("--init", action="store_true", help="Initialize database only")
    args = parser.parse_args()

    if args.init:
        conn = get_connection()
        init_db(conn)
        conn.close()
        print("Database initialized.")
        return

    result = run_pipeline(send_email=not args.no_email)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
