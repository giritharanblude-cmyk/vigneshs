"""Evidence validation layer.

Validates source authority, dates, numerical consistency, and deduplication.
"""
from datetime import datetime
from src.database import db
from src.database.db import get_connection


class ValidationResult:
    def __init__(self):
        self.accepted = 0
        self.rejected = 0
        self.issues: list[str] = []

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "issues": self.issues,
        }


def _validate_tier(source_tier: int) -> bool:
    return source_tier in (1, 2, 3, 4)


def _validate_date(date_str: str) -> bool:
    if not date_str:
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _validate_value(value) -> bool:
    if value is None:
        return True  # qualitative evidence
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value):  # NaN check
            return False
        if value < -1000 or value > 1_000_000_000:
            return False
    return True


def validate_db(conn) -> ValidationResult:
    """Validate all evidence in the database."""
    result = ValidationResult()

    sources = conn.execute("SELECT DISTINCT source_id FROM evidence").fetchall()
    for row in sources:
        source_id = row["source_id"]
        source_row = conn.execute(
            "SELECT * FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()

        if not source_row:
            result.rejected += 1
            result.issues.append(f"Source {source_id} has no matching source record")
            continue

        if not _validate_tier(source_row["source_tier"]):
            result.rejected += 1
            result.issues.append(f"Source {source_id} has invalid tier")
            continue

        if not _validate_date(source_row["publication_date"]):
            result.rejected += 1
            result.issues.append(f"Source {source_id} has invalid or missing date")
            continue

        result.accepted += 1

    return result


def validate_evidence_value(conn, evidence_id: str) -> ValidationResult:
    result = ValidationResult()
    row = conn.execute(
        "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
    ).fetchone()

    if not row:
        result.rejected += 1
        result.issues.append(f"Evidence {evidence_id} not found")
        return result

    if not _validate_value(row["value"]):
        result.rejected += 1
        result.issues.append(f"Evidence {evidence_id} has invalid value")
        return result

    # Check denominator consistency for percentage metrics
    if row["unit"] in ("percent", "%") and row["value"] is not None:
        if row["value"] > 100:
            result.issues.append(
                f"Evidence {evidence_id} has percentage value > 100, may be a rate"
            )

    result.accepted += 1
    return result


def detect_duplicates(conn) -> list[str]:
    """Detect evidence records that have the same source+skill+metric."""
    duplicates = []
    rows = conn.execute("""
        SELECT source_id, skill_id, metric, COUNT(*) as cnt
        FROM evidence
        GROUP BY source_id, skill_id, metric
        HAVING cnt > 1
    """).fetchall()
    for row in rows:
        duplicates.append(f"{row['source_id']}|{row['skill_id']}|{row['metric']}")
    return duplicates


def detect_outliers(conn, skill_id: str) -> list[dict]:
    """Detect numerical outliers using IQR method."""
    rows = conn.execute("""
        SELECT evidence_id, value, unit, period
        FROM evidence
        WHERE skill_id = ? AND value IS NOT NULL
    """, (skill_id,)).fetchall()
    values = [r["value"] for r in rows if isinstance(r["value"], (int, float))]
    if not values or len(values) < 4:
        return []

    values_sorted = sorted(values)
    q1 = values_sorted[len(values_sorted) // 4]
    q3 = values_sorted[(3 * len(values_sorted)) // 4]
    iqr = q3 - q1
    if iqr == 0:
        return []

    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    outliers = []
    for r in rows:
        if r["value"] is not None and (r["value"] < lower_bound or r["value"] > upper_bound):
            outliers.append({
                "evidence_id": r["evidence_id"],
                "value": r["value"],
                "unit": r["unit"],
                "period": r["period"],
            })
    return outliers
