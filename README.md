# Soft-Skill AI Trends Intelligence Platform

An automated intelligence platform that researches, validates, analyzes, and reports **AI-related soft-skill trends and emerging skill demand** over a rolling one-year period.

Built for a soft-skills trainer to answer:

> What evidence from the last 12 months indicates that this AI-related soft skill is becoming more or less important, how large is the change, how reliable is the evidence, and what should a trainer do about it?

---

## Features

- **Daily intelligence report** (markdown + email)
- **Rolling 12-month trend analysis** with YoY / MoM / rolling-change metrics
- **Emerging-skill ranking** via a weighted, evidence-based scoring model
- **Source-level provenance** for every quantitative result
- **Lightweight static HTML dashboard** (Chart.js, no server needed)
- **SQLite historical database** for longitudinal comparison
- **Automatic GitHub repo updates** via GitHub Actions
- **Multi-source collection**:
  - RSS feeds (academic/institutional)
  - Tier-1 official APIs (World Bank, U.S. BLS, OECD)
  - Web search discovery (Bing News RSS) for Tier 3/4 labour-market signals

---

## Scoring Model

Emerging Skill Score is a weighted sum of normalized evidence components:

| Component | Weight |
|-----------|--------|
| Demand growth | 30% |
| Hiring/job-posting frequency | 25% |
| Cross-industry spread | 15% |
| Cross-country spread | 10% |
| Employer/research evidence | 10% |
| Recency | 5% |
| Source reliability | 5% |

Every component retains its underlying source values. **No percentages are fabricated** — 
insufficient data yields no number.

---

## Evidence Types

The platform distinguishes four evidence types and never conflates them:

- **Observed** — directly reported by a source
- **Calculated** — derived mathematically from source data
- **Estimated** — modelled because direct data is unavailable
- **Qualitative** — supported by text/research but not numerically measurable

---

## Source Policy

Sources are ranked in tiers:

- **Tier 1** — Primary/official (OECD, ILO, WEF, UNESCO, World Bank, BLS, Eurostat, etc.)
- **Tier 2** — High-quality research (Nature, Science, IEEE, ACM, Elsevier, Springer, arXiv*)
- **Tier 3** — Structured market evidence with disclosed methodology (LinkedIn, Microsoft, Coursera, Lightcast, etc.)
- **Tier 4** — Discovery-only (news, blogs, social; not authoritative for trends)

---

## Architecture

```
Scheduled Trigger (GitHub Actions cron)
        │
        ▼
Source Collection (RSS / APIs / official data)
        │
        ▼
Evidence Validation (dedup + provenance + checks)
        │
        ▼
Trend Analysis Engine (Pandas)
        │
        ▼
Historical Store (SQLite / JSON / CSV)
        │
        ▼
Static Dashboard (HTML + Chart.js)     Email Report
```

---

## Repository Structure

```
softskill-ai-trends/
├── README.md
├── REQUIREMENTS.md
├── configuration.yaml
├── config/
│   ├── sources.yaml          # Tiers, feeds, APIs, queries
│   ├── skills.yaml           # Skill taxonomy
│   └── pipeline.yaml         # Weights, thresholds, schedule
├── data/
│   ├── raw/                  # Raw collected items
│   ├── processed/            # Dashboard JSON, CSV exports
│   └── historical/           # SQLite DB, run logs
├── src/
│   ├── collectors/
│   │   ├── collector.py      # RSS collector orchestration
│   │   ├── api_collector.py  # World Bank / OECD / BLS API collectors
│   │   └── search_collector.py  # Web-search Discovery-only collector
│   ├── validators/
│   ├── analyzers/
│   ├── scoring/
│   ├── reporting/
│   ├── http.py               # HTTP client (retries, UA, timeouts)
│   ├── calc.py               # YoY/MoM/rolling math helpers
│   └── database/
├── dashboard/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── reports/
│   └── daily/
├── main.py                   # Pipeline orchestrator
├── requirements.txt
└── .github/workflows/
    └── daily-softskill-trends.yml
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Initialize database (creates data/historical/trends.db)
python main.py --init

# 3. Run the pipeline (collect, validate, score, report)
python main.py

# Skip email for a local test run
python main.py --no-email
```

---

## Deployment (GitHub Actions)

1. Create a GitHub repository and push this project.
2. Enable GitHub Pages (deploy from `gh-pages` or via Actions).
3. Add repository secrets:

```
EMAIL_USERNAME        # SMTP username
EMAIL_PASSWORD        # SMTP app password
SMTP_HOST             # e.g. smtp.gmail.com
SMTP_PORT             # e.g. 587
DASHBOARD_URL         # public dashboard URL
```

4. The workflow `daily-softskill-trends.yml` runs the pipeline daily
   at `30 13 UTC` (7:00 PM IST).

> **Note on exact time:** GitHub Actions runs on a scheduled cron but does not
> guarantee the exact minute. If exact 7:00 PM IST delivery is a strict SLA,
> use a scheduler with an explicit execution-time guarantee (e.g. a cloud
> scheduler). The pipeline records actual execution time in every run record.

---

## Dashboard

The dashboard is a lightweight static page using **Chart.js**:

- KPI cards (skills, emerging, increasing, declining, evidence, sources, industries, countries)
- Top emerging skills (bar)
- Demand growth YoY (bar)
- 12-month demand trend (indexed line)
- Skill-share comparison (doughnut)
- Industry comparison (bar)
- Evidence confidence (doughnut)
- Detail table with sorting, confidence badges, CSV export
- Filters by skill, industry, geography, evidence level
- Source/methodology inspection

---

## Security

- **No credentials** are stored in source, HTML, JS, git history, or README.
- All secrets come from **GitHub Actions Secrets** / environment variables.
- Use an authenticating SMTP provider or transactional email API.
- The recipient email is never exposed in public frontend JS.

---

## Reliability

Each run writes a run record with timing, source counts, processed records,
and any errors. A failed run:
- does **not** overwrite the previous valid dataset,
- retains the last successful dashboard,
- records the failure for auditing.

---

## Quality Control

Before publication the pipeline verifies every cited source, date, percentage,
and denominator; detects duplicates and outliers; and flags missing methodology.
A failed check blocks publication of the affected metric. Missing values are
never fabricated or silently set to zero.

---

## License

Internal tool. Please verify all statistics against primary sources before use.
