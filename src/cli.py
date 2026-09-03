"""Command-line entry point for the Soft-Skill AI Trends pipeline.

Replicates the root `main.py` orchestration so the pipeline can be invoked via
the installed console script (`softskill-trends`) in addition to `python main.py`.

The project root is resolved in priority order:
  1. SOFT_SKILL_TRENDS_ROOT env var (for installed/deployed layouts)
  2. The repository root two levels above this file (source-tree layout)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_config
from src.database import db
from src.database.db import get_connection, init_db


def resolve_root() -> Path:
    env = os.environ.get("SOFT_SKILL_TRENDS_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if root.exists():
            return root
    # source-tree layout: <repo>/src/cli.py -> <repo>
    return Path(__file__).resolve().parent.parent


def run_pipeline(send_email: bool = True, root: Path | None = None) -> dict:
    from src.models import RunRecord
    from src.collectors.collector import collect_all
    from src.validators.validator import validate_db, detect_duplicates
    from src.analyzers.analyzer import generate_daily_scores_cmd, backfill_historical_scores
    from src.reporting.reporter import (
        generate_daily_report,
        generate_dashboard_data,
        write_dashboard_data,
        write_csv_export,
        generate_run_log,
    )

    root = root or resolve_root()
    config_dir = root / "config"
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%d-%H%M%S")
    print(f"=== Soft-Skill AI Trends Pipeline ===")
    print(f"Run ID: {run_id}")
    print(f"Root: {root}")

    conn = get_connection()
    init_db(conn)

    config = load_config(config_dir)
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
        collect_stats = collect_all(conn)
        run_record.sources_checked = collect_stats.get("sources_checked", 0)
        run_record.sources_accepted = collect_stats.get("sources_accepted", 0)
        run_record.records_processed = collect_stats.get("evidence_items", 0)
        run_record.errors = collect_stats.get("errors", [])

        validation = validate_db(conn)
        run_record.sources_accepted = validation.accepted
        run_record.sources_rejected = validation.rejected
        run_record.errors.extend(validation.issues)

        dupes = detect_duplicates(conn)
        if dupes:
            print(f"  Found {len(dupes)} duplicate source/skill/metric groups")

        print("  Generating daily scores for all skills...")
        generate_daily_scores_cmd(conn, datetime.now(timezone.utc).strftime("%Y-%m-%d"))

        snaps = backfill_historical_scores(conn)
        print(f"  Historical monthly snapshots written: {snaps}")

        print("  Building dashboard data...")
        today = started.strftime("%Y-%m-%d")
        dashboard_data = generate_dashboard_data(conn, today)
        write_dashboard_data(dashboard_data, today)
        write_csv_export(conn, today)

        print("  Generating daily report...")
        report_path = generate_daily_report(conn, today)

        print("  Updating dashboard...")
        out = data_dir / "processed" / "dashboard_data.json"
        out.write_text(json.dumps(dashboard_data, indent=2), encoding="utf-8")
        print(f"  Dashboard data written to {out}")

        if send_email:
            from src.reporting.emailer import send_daily_email
            recipient = config.pipeline.get("pipeline", {}).get("email", {}).get(
                "recipient", "shrivigneshr15@gmail.com")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Soft-Skill AI Trends Intelligence Platform")
    parser.add_argument("--no-email", action="store_true", help="Skip email sending")
    parser.add_argument("--init", action="store_true", help="Initialize database only")
    parser.add_argument("--root", default=None, help="Project root override")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else None

    if args.init:
        conn = get_connection()
        init_db(conn)
        conn.close()
        print("Database initialized.")
        return 0

    result = run_pipeline(send_email=not args.no_email, root=root)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
