# TBC Raid Analysis

A pull-by-pull raid analysis tool for World of Warcraft: The Burning Crusade Classic. Built for raid leaders and players who want fast, actionable breakdowns of their raid nights without digging through WarcraftLogs manually.

## How to Use

1. Open the app
2. Paste a WarcraftLogs report URL (e.g., `https://fresh.warcraftlogs.com/reports/ABC123`)
3. Click **Analyze Report**
4. Browse tabs for pull-by-pull breakdowns

No API key needed — the backend handles WarcraftLogs authentication automatically.

## Features

- **Pull-by-pull analysis** — deaths, damage sources, role performance, and positioning for every attempt
- **Action items** — auto-generated improvement suggestions based on wipe patterns
- **Raid awards** — fun and competitive dashboard highlighting standout and meme-worthy moments
- **Raid comparison** — side-by-side diff of two logs with pacing, buff, and DPS/HPS delta analysis
- **Role-specific views** — dedicated tabs for Tanks, Healers, and DPS
- **Individual player drill-down** — per-player spell breakdowns, buff uptimes, and cooldown timelines
- **Boss strategy context** — phase timelines and boss-specific mechanic tracking

## Architecture

```
┌─────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│   Browser    │────▶│   FastAPI Backend     │────▶│  WCL v2 API     │
│  (Frontend)  │◀────│  (Azure Container App)│◀────│  (GraphQL/OAuth) │
└─────────────┘     └──────────────────────┘     └─────────────────┘
```

- **Frontend** — Single-file HTML/CSS/JS served as static files. All rendering logic runs in-browser.
- **Backend** — Python FastAPI app handling WCL v2 OAuth, GraphQL queries, and report analysis.
- **WCL v2 API** — OAuth2 client credentials grant. Provides richer data than v1: threat events, resource tracking, detailed buff/debuff data.
- **Hosting** — Azure Container Apps with GitHub Actions CI/CD.

## Project Structure

```
tbcraidanalysis/
├── backend/
│   ├── main.py                 # FastAPI app, routes, static file serving
│   ├── config.py               # Settings (env vars, secrets)
│   ├── requirements.txt        # Python dependencies
│   ├── wcl/
│   │   ├── auth.py             # WCL v2 OAuth client credentials flow
│   │   ├── client.py           # GraphQL client wrapper
│   │   └── queries.py          # GraphQL query templates
│   └── analysis/
│       ├── report.py           # Report fetching, event normalization, role inference
│       └── compare.py          # Compare-mode report fetching and player details
├── frontend/
│   ├── index.html              # Main analysis UI
│   └── compare.html            # Raid comparison UI
├── scripts/                    # Legacy CLI tools (optional, use v1 API)
├── Dockerfile                  # Container image definition
├── .github/workflows/ci-cd.yml # CI/CD pipeline
└── docs/                       # Documentation
```

## Comparing Two Raids

Click the **Compare Logs** button in the top bar (visible after loading a report), or go directly to `/compare`. Paste two report URLs to see:

- Kill time deltas per boss
- Raid DPS/HPS differences
- Missing buff analysis
- Pacing and trash efficiency gaps
- Per-player detailed breakdowns (damage, healing, buffs, casts)
- Auto-generated recommendations

## Supported Bosses

Works with any TBC raid boss, with enhanced mechanic tracking for:

- Al'ar
- Void Reaver
- High Astromancer Solarian
- Kael'thas Sunstrider (conflagration tracking, phase detection)
- Hydross the Unstable
- The Lurker Below
- Leotheras the Blind
- Fathom-Lord Karathress
- Morogrim Tidewalker
- Lady Vashj

## Documentation

| Doc | Description |
|-----|-------------|
| [Analysis Tabs](docs/analysis-tabs.md) | What each tab shows and how to read it |
| [Raid Awards](docs/awards.md) | All award categories, how they're computed, and data requirements |
| [Log Comparison](docs/comparison.md) | How the comparison tool works and what it reports |
| [Data Model](docs/data-model.md) | Structure of the report JSON and what each field contains |
| [Scripts](docs/scripts.md) | Legacy CLI tools for local fetching, parsing, and comparing |

## Running Locally

### Backend (recommended)

Requires Python 3.9+ and a `.env` file with WCL v2 credentials:

```bash
# .env file
WCL_CLIENT_ID=your_client_id
WCL_CLIENT_SECRET=your_client_secret
```

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

Register a WCL v2 API client at [warcraftlogs.com/api/clients](https://www.warcraftlogs.com/api/clients).

### Docker

```bash
docker build -t tbcraidanalysis .
docker run -p 8000:8000 --env-file .env tbcraidanalysis
```

### Legacy scripts (optional)

The `scripts/` directory contains v1-API-based CLI tools. See [docs/scripts.md](docs/scripts.md) for details. These are not required for normal use.
