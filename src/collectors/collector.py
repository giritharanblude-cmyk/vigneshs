"""Source collection layer.

Collects evidence from RSS feeds and web APIs.
"""
import hashlib
import requests
import feedparser
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from src.database import db
from src.database.db import upsert_source, insert_evidence, source_exists
from src.models import Source, Evidence, EvidenceType
from src.config import load_config

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"

feedparser.USER_AGENT = "SoftSkillAITrends/1.0 (research intelligence; soft-skill trend analysis)"


def _log(msg: str) -> None:
    print(f"[collector] {msg}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def collect_all(conn) -> dict:
    """Run all collectors and return a stats dict."""
    config = load_config(CONFIG_DIR)
    stats = {"sources_checked": 0, "sources_accepted": 0, "evidence_items": 0, "errors": []}

    for feed in config.sources.get("rss_feeds", []):
        try:
            count = collect_rss(conn, feed)
            stats["sources_checked"] += 1
            stats["sources_accepted"] += count
        except Exception as e:
            stats["errors"].append(f"RSS {feed.get('name')}: {e}")

    # Tier-1 official API sources (World Bank, OECD, BLS)
    try:
        from src.collectors.api_collector import collect_all_apis
        api_stats = collect_all_apis(conn)
        stats["sources_checked"] += api_stats.get("checked", 0)
        stats["sources_accepted"] += api_stats.get("accepted", 0)
        stats["evidence_items"] += api_stats.get("accepted", 0)
    except Exception as e:
        stats["errors"].append(f"API collectors: {e}")

    # Tier 3/4 web search discovery
    try:
        from src.collectors.search_collector import collect_all_search
        search_stats = collect_all_search(conn)
        stats["sources_checked"] += search_stats.get("checked", 0)
        stats["sources_accepted"] += search_stats.get("accepted", 0)
        stats["evidence_items"] += search_stats.get("accepted", 0)
        if search_stats.get("errors"):
            stats["errors"].extend(search_stats["errors"])
    except Exception as e:
        stats["errors"].append(f"Search collectors: {e}")

    return stats


def collect_rss(conn, feed: dict) -> int:
    """Collect entries from an RSS feed."""
    name = feed.get("name", "Unknown Feed")
    url = feed.get("url", "")
    tier = feed.get("tier", 4)
    category = feed.get("category", "general")

    if not url:
        return 0

    _log(f"Fetching RSS: {name}")
    try:
        parsed = feedparser.parse(url)
    except Exception as e:
        _log(f"  Error: {e}")
        return 0

    if parsed.bozo and not parsed.entries:
        _log(f"  Malformed feed, no entries")
        return 0

    count = 0
    for entry in parsed.entries[:20]:
        entry_url = entry.get("link", "")
        if not entry_url:
            continue
        if source_exists(conn, entry_url):
            continue

        title = entry.get("title", "")
        published = entry.get("published", "") or entry.get("updated", "")
        pub_date = _parse_date(published)

        source = Source(
            source_id=_hash(url, entry_url, title),
            organization=name,
            title=title,
            url=entry_url,
            publication_date=pub_date,
            source_tier=tier,
            methodology=f"RSS feed collection from {name}",
            retrieved_at=_now(),
        )
        upsert_source(conn, source)

        summary = entry.get("summary", "")
        text = f"{title} {summary}"

        # Auto-detect skills mentioned in the text
        skill_hits = _detect_skills(text)
        industries = _detect_industries(text)
        geography = _detect_geography(text)

        for skill_id in skill_hits:
            for industry in industries:
                evidence = Evidence(
                    evidence_id=_hash("evidence", source.source_id, skill_id, industry, category),
                    source_id=source.source_id,
                    skill_id=skill_id,
                    metric="mention_frequency",
                    value=1.0,
                    unit="mention",
                    period=pub_date[:7] if len(pub_date) >= 7 else pub_date,
                    geography=geography,
                    industry=industry,
                    evidence_type=EvidenceType.QUALITATIVE,
                    retrieved_at=_now(),
                )
                insert_evidence(conn, evidence)

        count += 1

    conn.commit()
    return count


def _parse_date(raw: str) -> str:
    """Parse a date string into YYYY-MM-DD format."""
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(raw)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _detect_skills(text: str) -> list[str]:
    """Detect which tracked skills appear in the text (keyword matching)."""
    config = load_config(CONFIG_DIR)
    skills = config.get_skills()
    keyword_map = {
        s["id"]: [s["name"].lower(), s["id"].replace("_", " ")]
        for s in skills
    }

    lower = text.lower()
    hits = []
    for skill_id, keywords in keyword_map.items():
        if any(kw in lower for kw in keywords):
            hits.append(skill_id)
    return hits


def _detect_industries(text: str) -> list[str]:
    industry_keywords = {
        "technology": ["technology", "tech", "software", "it sector", "digital"],
        "finance": ["finance", "financial", "banking", "fintech"],
        "healthcare": ["healthcare", "health care", "medical", "clinical", "health"],
        "education": ["education", "school", "university", "training", "learning"],
        "manufacturing": ["manufacturing", "factory", "production", "industrial"],
        "retail": ["retail", "consumer", "e-commerce", "commerce"],
        "consulting": ["consulting", "advisory", "professional services"],
        "government": ["government", "public sector", "policy", "regulation"],
    }
    lower = text.lower()
    matches = []
    for industry, keywords in industry_keywords.items():
        if any(kw in lower for kw in keywords):
            matches.append(industry)
    return matches or ["general"]


def _detect_geography(text: str) -> str:
    import re

    country_map = {
        "United States": ["united states", "us", "u.s.", "american"],
        "United Kingdom": ["united kingdom", "uk", "british", "england"],
        "India": ["india", "indian"],
        "Germany": ["germany", "german"],
        "Australia": ["australia", "australian"],
        "Canada": ["canada", "canadian"],
        "Singapore": ["singapore"],
        "EU": ["european union", "eu", "europe", "european"],
        "Japan": ["japan", "japanese"],
        "China": ["china", "chinese"],
    }
    lower = text.lower()
    for country, keywords in country_map.items():
        if any(kw in lower for kw in keywords):
            return country
    return "Global"
