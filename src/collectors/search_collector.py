"""Web search-based discovery collector (Tier 3/4).

Uses free RSS search endpoints (no API key required) to discover
labour-market evidence for AI soft skills, then classifies results by
authority. Per the source policy, news/blog results are Discovery-only
(Tier 4) and never independently establish a quantitative trend, while
known structured market-evidence domains attract Tier 3.
"""
import hashlib
import re
import feedparser
from datetime import datetime, timezone
from pathlib import Path

from src.database.db import (
    upsert_source, insert_evidence, source_exists, evidence_exists, source_exists_by_id,
)
from src.models import Source, Evidence, EvidenceType
from src.config import load_config
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"

feedparser.USER_AGENT = "SoftSkillAITrends/1.0 (research intelligence; soft-skill trend analysis)"

# Domains that are Tier 3 structured market evidence (methodology disclosed).
TIER3_DOMAINS = [
    "linkedin.com", "microsoft.com", "coursera.org", "lightcast.io",
    "burning-glass.com", "indeed.com", "glassdoor.com",
]

TIER2_DOMAINS = ["nature.com", "science.org", "ieee.org", "acm.org", "arxiv.org"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _domain_tier(url: str) -> int:
    """Determine source tier from the domain."""
    lower = url.lower()
    for d in TIER3_DOMAINS:
        if d in lower:
            return 3
    for d in TIER2_DOMAINS:
        if d in lower:
            return 2
    return 4  # Discovery-only


def _parse_date(raw: str) -> str:
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(raw)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _detect_skills(text: str) -> list[str]:
    config = load_config(CONFIG_DIR)
    keyword_map = {
        s["id"]: [s["name"].lower(), s["id"].replace("_", " ")]
        for s in config.get_skills()
    }
    lower = text.lower()
    return [sid for sid, kws in keyword_map.items() if any(k in lower for k in kws)]


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
    matches = [ind for ind, kws in industry_keywords.items() if any(k in lower for k in kws)]
    return matches or ["general"]


def _detect_geography(text: str) -> str:
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
    for country, kws in country_map.items():
        if any(k in lower for k in kws):
            return country
    return "Global"


def _search_engine(query: str, num: int = 8) -> list[dict]:
    """Search using a free RSS endpoint. Returns [{title, link, published, summary}]."""
    results = []
    # Bing News RSS (free, no key) — discovery only
    from urllib.parse import urlencode
    bing_url = "https://www.bing.com/news/search?" + urlencode({"q": query, "format": "rss", "count": num})
    try:
        parsed = feedparser.parse(bing_url)
    except Exception:
        return results

    if not parsed or not parsed.entries:
        return results

    for entry in parsed.entries[:num]:
        results.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", "") or entry.get("updated", ""),
            "summary": entry.get("summary", "") or "",
        })
    return results


def collect_search(conn, query: str, tier_hint: int = 3) -> dict:
    """Run one search query and collect discovery evidence."""
    stats = {"checked": 0, "accepted": 0}
    results = _search_engine(query)
    for item in results:
        entry_url = item.get("link", "")
        title = item.get("title", "")
        if not entry_url or not title:
            continue

        # Bing returns apiclick redirect URLs whose parameters change per session;
        # dedup on a stable key derived from the canonical title + domain.
        canonical_key = _hash("search", title.strip().lower())
        if source_exists_by_id(conn, canonical_key):
            continue

        summary = item.get("summary", "")
        text = f"{title} {summary}"
        domain_tier = _domain_tier(entry_url)

        source = Source(
            source_id=canonical_key,
            organization=domain_from_url(entry_url),
            title=title,
            url=entry_url,
            publication_date=_parse_date(item.get("published", "")),
            source_tier=domain_tier,
            methodology=f"Web search discovery (query: '{query}')",
            retrieved_at=_now(),
        )
        upsert_source(conn, source)

        skills = _detect_skills(text)
        industries = _detect_industries(text)
        geo = _detect_geography(text)

        for skill_id in skills:
            for industry in industries:
                if evidence_exists(conn, source.source_id, skill_id, "mention_frequency"):
                    continue
                evidence = Evidence(
                    evidence_id=_hash("search-e", source.source_id, skill_id, industry, query),
                    source_id=source.source_id,
                    skill_id=skill_id,
                    metric="mention_frequency",
                    value=1.0,
                    unit="mention",
                    period=_parse_date(item.get("published", ""))[:7],
                    geography=geo,
                    industry=industry,
                    evidence_type=EvidenceType.QUALITATIVE,
                    retrieved_at=_now(),
                )
                insert_evidence(conn, evidence)
                stats["accepted"] += 1
        stats["checked"] += 1

    conn.commit()
    return stats


def collect_all_search(conn) -> dict:
    """Run all configured search queries."""
    config = load_config(CONFIG_DIR)
    queries = config.sources.get("search_queries", [])
    totals = {"checked": 0, "accepted": 0, "errors": []}
    for q in queries:
        try:
            stats = collect_search(conn, q["query"])
            totals["checked"] += stats["checked"]
            totals["accepted"] += stats["accepted"]
        except Exception as e:
            totals["errors"].append(f"search '{q['query']}': {e}")
    return totals


def domain_from_url(url: str) -> str:
    """Extract a readable organization name from a URL."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc
        parts = host.replace("www.", "").split(".")
        return parts[0].title() if parts else host
    except Exception:
        return "Web"
