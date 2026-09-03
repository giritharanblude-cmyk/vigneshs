"""API-based collectors for Tier-1 labour-market evidence.

Wires public APIs from:
- World Bank Indicators API (free, no key)
- OECD SDMX/data API (free, no key)
- BLS Public Data API (free; optional key for higher limits)
"""
import os
from pathlib import Path
from datetime import datetime, timezone

from src.database import db
from src.database.db import upsert_source, insert_evidence, evidence_exists
from src.models import Source, Evidence, EvidenceType
from src.http import http_get_json

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sid(url: str, *parts: str) -> str:
    raw = url + "|" + "|".join(parts)
    return __import__("hashlib").sha256(raw.encode("utf-8")).hexdigest()[:16]


def collect_world_bank(conn) -> dict:
    """Collect World Bank education / labour / ICT indicators."""
    stats = {"checked": 0, "accepted": 0}
    base = "https://api.worldbank.org/v2/country/all/indicator"
    format = "json&per_page=100&mrnev=8"

    # Indicator -> (skill_id, metric, geography_note)
    indicators = [
        # Tertiary education enrollment ratio (proxy for skill acquisition / learning agility)
        ("SE.TER.ENRR", "learning_agility", "tertiary_enrollment_rate", "percent"),
        # Labor force with advanced education (% of total working-age)
        ("SL.TLF.ADVN.ZS", "learning_agility", "labor_force_advanced_education", "percent"),
        # Scientific and technical journal articles (proxy for analytical / critical thinking demand)
        ("IP.JRN.ARTC.SC", "analytical_thinking", "research_output", "count"),
        # Individuals using the internet (% — proxy for digital literacy reach)
        ("IT.NET.USER.ZS", "digital_literacy", "internet_users", "percent"),
        # Mobile cellular subscriptions (digital access proxy)
        ("IT.CEL.SETS.P2", "digital_literacy", "mobile_subscriptions", "per100"),
        # Employment in services (% of total employment — service economy soft-skill demand)
        ("SL.SRV.EMPL.ZS", "communication", "services_employment_share", "percent"),
        # High-technology exports (% of manufactured exports)
        ("TX.VAL.TECH.MF.ZS", "adaptability", "high_tech_exports", "percent"),
        # Unemployment total (% of labor force)
        ("SL.UEM.TOTL.ZS", "resilience", "unemployment_rate", "percent"),
        # Labor force participation rate
        ("SL.TLF.CACT.ZS", "adaptability", "labor_force_participation", "percent"),
    ]

    for code, skill_id, metric, unit in indicators:
        stats["checked"] += 1
        try:
            url = f"{base}/{code}"
            resp = http_get_json(url, params={"format": "json", "per_page": "100", "mrnev": "12"})
            if not resp or not isinstance(resp, list) or len(resp) < 2 or not resp[1]:
                continue
            records = resp[1]
            most_recent = _most_recent_record(records)
            if not most_recent:
                continue

            # Take global aggregate (country code "1W" or the first global row)
            global_rows = [r for r in records if r.get("countryiso3code") in ("WLD", "1A", "1W")]
            row = global_rows[0] if global_rows else most_recent
            value = row.get("value")
            if value is None:
                continue
            year = row.get("date")
            source = _world_bank_source(code, metric, year)
            upsert_source(conn, source)
            if not evidence_exists(conn, source.source_id, skill_id, metric):
                evidence = Evidence(
                    evidence_id=_sid("wb", source.source_id, skill_id, metric, str(year)),
                    source_id=source.source_id,
                    skill_id=skill_id,
                    metric=metric,
                    value=float(value),
                    unit=unit,
                    period=f"{year}-12",
                    geography="Global",
                    industry="general",
                    evidence_type=EvidenceType.OBSERVED,
                    retrieved_at=_now(),
                )
                insert_evidence(conn, evidence)
                stats["accepted"] += 1
        except Exception as e:
            print(f"  [worldbank] {code}: {e}")

    conn.commit()
    return stats


def _world_bank_source(series_code: str, metric: str, year: str) -> Source:
    return Source(
        source_id=_sid("wb-src", series_code),
        organization="World Bank",
        title=f"World Bank Open Data — {metric} ({series_code})",
        url=f"https://data.worldbank.org/indicator/{series_code}",
        publication_date=f"{year}-12-01",
        source_tier=1,
        methodology=f"World Bank Open Data API, series {series_code}, most recent annual value.",
        retrieved_at=_now(),
    )


def _most_recent_record(records: list) -> dict:
    """Return the record with the most recent date among those with a value."""
    valid = [r for r in records if r.get("value") is not None]
    if not valid:
        return None
    return sorted(valid, key=lambda r: r.get("date", ""), reverse=True)[0]


def collect_oecd(conn) -> dict:
    """Collect OECD data via the OECD Data Explorer (SDMX JSON).

    Degrades gracefully — if the endpoint is unreachable or the flow
    reference is unavailable, no evidence is added and no error is raised.
    """
    stats = {"checked": 0, "accepted": 0}

    # Try a set of plausible OECD SDMX endpoints; use the first that responds.
    candidates = [
        ("https://sdmx.oecd.org/public/rest/data/OECD/SDD/EDU_DEM", {"format": "jsondata"}),
        ("https://data-explorer.oecd.org/rest/data/OECD/SDD/EDU_DEM", {"format": "jsondata"}),
    ]

    for endpoint, params in candidates:
        resp = http_get_json(endpoint, params=params)
        if not resp:
            continue
        stats["checked"] += 1
        series = _flatten_oecd(resp)
        if not series:
            continue
        source = Source(
            source_id=_sid("oecd-src", endpoint),
            organization="OECD",
            title="OECD Education & Labour Statistics",
            url="https://data.oecd.org/education/",
            publication_date=f"{datetime.now().year}-06-01",
            source_tier=1,
            methodology="OECD Data Explorer (SDMX JSON), education & labour statistics.",
            retrieved_at=_now(),
        )
        upsert_source(conn, source)
        val = series.get("value")
        if val is not None and not evidence_exists(conn, source.source_id, "learning_agility", "education_index"):
            evidence = Evidence(
                evidence_id=_sid("oecd-e", source.source_id, "learning_agility", str(val)),
                source_id=source.source_id,
                skill_id="learning_agility",
                metric="education_index",
                value=float(val),
                unit="index",
                period=f"{datetime.now().year}-06",
                geography="OECD",
                industry="general",
                evidence_type=EvidenceType.OBSERVED,
                retrieved_at=_now(),
            )
            insert_evidence(conn, evidence)
            stats["accepted"] += 1
        break

    conn.commit()
    return stats


def _flatten_oecd(resp: dict) -> dict:
    """Extract a simple numeric observation from OECD SDMX JSON."""
    try:
        data = resp.get("data", {})
        # structure keyed by dimension; find first observation with value
        datasets = data.get("dataSets", [])
        if datasets:
            series = datasets[0].get("series", {})
            for key in list(series.keys())[:5]:
                obs = series[key].get("observations", {})
                for pos in list(obs.keys())[:5]:
                    entry = obs[pos]
                    if isinstance(entry, list) and entry:
                        return {"value": entry[0]}
    except Exception:
        pass
    return {}


def collect_bls(conn) -> dict:
    """Collect BLS data via the Public Data API (v2).

    Note: unauthenticated requests are limited (~25 calls/day); use
    a BLS_API_KEY secret for production workloads.
    """
    stats = {"checked": 0, "accepted": 0}
    key = os.getenv("BLS_API_KEY")
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    series_ids = [
        "CES0000000001",  # Total nonfarm employment
    ]
    start = str(datetime.now().year - 1)
    end = str(datetime.now().year)

    payload = {
        "seriesid": series_ids,
        "startyear": start,
        "endyear": end,
    }
    if key:
        payload["registrationkey"] = key

    try:
        data = _bls_post(url, payload)
        stats["checked"] = len(series_ids)
        if not data or data.get("status") != "REQUEST_SUCCEEDED":
            print(f"  [bls] API returned: {data.get('status') if data else 'no response'}")
            return stats
        for series in data.get("Results", {}).get("series", []):
            series_id = series.get("seriesID")
            data_rows = series.get("data", [])
            for row in data_rows[:6]:
                try:
                    value = float(row.get("value", "").replace(",", ""))
                except ValueError:
                    continue
                period = row.get("period")
                year = row.get("year")
                source = Source(
                    source_id=_sid("bls-src", series_id),
                    organization="U.S. Bureau of Labor Statistics",
                    title=f"BLS Employment Data ({series_id})",
                    url=f"https://data.bls.gov/timeseries/{series_id}",
                    publication_date=f"{year}-12-01",
                    source_tier=1,
                    methodology="BLS Public Data API v2, monthly employment series.",
                    retrieved_at=_now(),
                )
                upsert_source(conn, source)
                # Map employment levels to adaptability/labour-market resilience
                if not evidence_exists(conn, source.source_id, "adaptability", "employment_level"):
                    evidence = Evidence(
                        evidence_id=_sid("bls-e", source.source_id, "adaptability", series_id, period, year),
                        source_id=source.source_id,
                        skill_id="adaptability",
                        metric="employment_level",
                        value=value,
                        unit="thousands",
                        period=f"{year}-{period[1:]}",
                        geography="United States",
                        industry="general",
                        evidence_type=EvidenceType.OBSERVED,
                        retrieved_at=_now(),
                    )
                    insert_evidence(conn, evidence)
                    stats["accepted"] += 1
    except Exception as e:
        print(f"  [bls] {e}")

    conn.commit()
    return stats


def _bls_post(url: str, payload: dict) -> dict | None:
    import requests
    from src.http import DEFAULT_HEADERS, TIMEOUT
    try:
        resp = requests.post(url, json=payload, headers=DEFAULT_HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        print(f"  [bls] HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [bls] {e}")
    return None


def collect_all_apis(conn) -> dict:
    """Run all API collectors and aggregate stats."""
    totals = {"checked": 0, "accepted": 0}
    for fn in (collect_world_bank, collect_oecd, collect_bls):
        try:
            stats = fn(conn)
            totals["checked"] += stats.get("checked", 0)
            totals["accepted"] += stats.get("accepted", 0)
        except Exception as e:
            print(f"  [api] collector {fn.__name__} failed: {e}")
    return totals
