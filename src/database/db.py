import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from src.models import Source, Evidence, DailyScore, Skill

DB_PATH = Path(__file__).parent.parent.parent / "data" / "historical" / "trends.db"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY,
            skill_name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            organization TEXT DEFAULT '',
            title TEXT DEFAULT '',
            url TEXT DEFAULT '',
            publication_date TEXT DEFAULT '',
            source_tier INTEGER DEFAULT 4,
            methodology TEXT DEFAULT '',
            retrieved_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            metric TEXT DEFAULT '',
            value REAL,
            unit TEXT DEFAULT '',
            period TEXT DEFAULT '',
            geography TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            evidence_type TEXT DEFAULT 'qualitative',
            retrieved_at TEXT DEFAULT '',
            FOREIGN KEY (source_id) REFERENCES sources(source_id),
            FOREIGN KEY (skill_id) REFERENCES skills(skill_id)
        );

        CREATE TABLE IF NOT EXISTS daily_scores (
            date TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            demand_score REAL DEFAULT 0.0,
            growth_rate REAL,
            emerging_score REAL DEFAULT 0.0,
            confidence TEXT DEFAULT 'low',
            PRIMARY KEY (date, skill_id),
            FOREIGN KEY (skill_id) REFERENCES skills(skill_id)
        );

        CREATE TABLE IF NOT EXISTS run_log (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT DEFAULT '',
            sources_checked INTEGER DEFAULT 0,
            sources_accepted INTEGER DEFAULT 0,
            sources_rejected INTEGER DEFAULT 0,
            records_processed INTEGER DEFAULT 0,
            skills_tracked INTEGER DEFAULT 0,
            errors TEXT DEFAULT '[]'
        );

        CREATE INDEX IF NOT EXISTS idx_evidence_skill ON evidence(skill_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_period ON evidence(period);
        CREATE INDEX IF NOT EXISTS idx_daily_scores_date ON daily_scores(date);
        CREATE INDEX IF NOT EXISTS idx_daily_scores_skill ON daily_scores(skill_id);
    """)
    conn.commit()


def upsert_skill(conn: sqlite3.Connection, skill: Skill) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO skills (skill_id, skill_name, category, description)
        VALUES (?, ?, ?, ?)
    """, (skill.skill_id, skill.skill_name, skill.category, skill.description))


def upsert_source(conn: sqlite3.Connection, source: Source) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO sources
        (source_id, organization, title, url, publication_date, source_tier, methodology, retrieved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (source.source_id, source.organization, source.title, source.url,
          source.publication_date, source.source_tier, source.methodology, source.retrieved_at))


def insert_evidence(conn: sqlite3.Connection, evidence: Evidence) -> None:
    conn.execute("""
        INSERT OR IGNORE INTO evidence
        (evidence_id, source_id, skill_id, metric, value, unit, period, geography, industry, evidence_type, retrieved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (evidence.evidence_id, evidence.source_id, evidence.skill_id,
          evidence.metric, evidence.value, evidence.unit, evidence.period,
          evidence.geography, evidence.industry, evidence.evidence_type.value, evidence.retrieved_at))


def upsert_daily_score(conn: sqlite3.Connection, score: DailyScore) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO daily_scores (date, skill_id, demand_score, growth_rate, emerging_score, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (score.date, score.skill_id, score.demand_score, score.growth_rate,
          score.emerging_score, score.confidence))


def get_evidence_for_skill(conn: sqlite3.Connection, skill_id: str, months: int = 12) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT e.*, s.organization, s.source_tier, s.methodology
        FROM evidence e
        JOIN sources s ON e.source_id = s.source_id
        WHERE e.skill_id = ? AND e.period >= ?
        ORDER BY e.period DESC
    """, (skill_id, cutoff)).fetchall()
    return [dict(r) for r in rows]


def get_all_skills(conn: sqlite3.Connection) -> list[Skill]:
    rows = conn.execute("SELECT * FROM skills").fetchall()
    return [Skill(skill_id=r["skill_id"], skill_name=r["skill_name"],
                  category=r["category"], description=r["description"]) for r in rows]


def get_daily_scores(conn: sqlite3.Connection, skill_id: str, days: int = 365) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT * FROM daily_scores
        WHERE skill_id = ? AND date >= ?
        ORDER BY date DESC
    """, (skill_id, cutoff)).fetchall()
    return [dict(r) for r in rows]


def get_evidence_count_by_skill(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("""
        SELECT skill_id, COUNT(*) as cnt FROM evidence GROUP BY skill_id
    """).fetchall()
    return {r["skill_id"]: r["cnt"] for r in rows}


def get_sources_by_tier(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute("""
        SELECT source_tier, COUNT(*) as cnt FROM sources GROUP BY source_tier
    """).fetchall()
    return {r["source_tier"]: r["cnt"] for r in rows}


def get_distinct_industries(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("""
        SELECT DISTINCT industry FROM evidence WHERE industry != '' AND industry IS NOT NULL
    """).fetchall()
    return [r["industry"] for r in rows]


def get_distinct_countries(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("""
        SELECT DISTINCT geography FROM evidence WHERE geography != '' AND geography IS NOT NULL
    """).fetchall()
    return [r["geography"] for r in rows]


def get_last_run_date(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("""
        SELECT date FROM daily_scores ORDER BY date DESC LIMIT 1
    """).fetchone()
    return row["date"] if row else None


def get_previous_period_scores(conn: sqlite3.Connection, skill_id: str, current_date: str, days_back: int = 30) -> Optional[dict]:
    cutoff = (datetime.strptime(current_date, "%Y-%m-%d") - timedelta(days=days_back)).strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT * FROM daily_scores
        WHERE skill_id = ? AND date <= ?
        ORDER BY date DESC LIMIT 1
    """, (skill_id, cutoff)).fetchone()
    return dict(row) if row else None


def source_exists(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute("SELECT 1 FROM sources WHERE url = ?", (url,)).fetchone()
    return row is not None


def source_exists_by_id(conn: sqlite3.Connection, source_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM sources WHERE source_id = ?", (source_id,)).fetchone()
    return row is not None


def evidence_exists(conn: sqlite3.Connection, source_id: str, skill_id: str, metric: str) -> bool:
    row = conn.execute("""
        SELECT 1 FROM evidence WHERE source_id = ? AND skill_id = ? AND metric = ?
    """, (source_id, skill_id, metric)).fetchone()
    return row is not None
