# TBC Raid Analysis

A pull-by-pull raid analysis tool for World of Warcraft: The Burning Crusade Classic. Built for raid leaders and players who want fast, actionable breakdowns of their raid nights without digging through WarcraftLogs manually.

**Use it now:** [nicoleserafino.github.io/tbcraidanalysis](https://nicoleserafino.github.io/tbcraidanalysis)

## How to Use

1. Go to [nicoleserafino.github.io/tbcraidanalysis](https://nicoleserafino.github.io/tbcraidanalysis)
2. Paste a WarcraftLogs report URL (e.g., `https://fresh.warcraftlogs.com/reports/ABC123`)
3. Click **Analyze Report**
4. Browse tabs for pull-by-pull breakdowns

No API key is needed for public logs. For unlisted/private logs, enter your own [WarcraftLogs v1 API key](https://fresh.warcraftlogs.com/profile).

## Features

- **Pull-by-pull analysis** — deaths, damage sources, role performance, and positioning for every attempt
- **Action items** — auto-generated improvement suggestions based on wipe patterns
- **Raid awards** — fun and competitive dashboard highlighting standout and meme-worthy moments
- **Raid comparison** — side-by-side diff of two logs with pacing, buff, and DPS delta analysis
- **Role-specific views** — dedicated tabs for Tanks, Healers, and DPS
- **Individual player drill-down** — per-player spell breakdowns, buff uptimes, and cooldown timelines
- **Boss strategy context** — phase timelines and boss-specific mechanic tracking

## Comparing Two Raids

Click the **Compare Logs** button in the top bar (visible after loading a report), or go directly to the compare page. Paste two report URLs to see:

- Kill time deltas per boss
- Raid DPS/HPS differences
- Missing buff analysis
- Pacing and trash efficiency gaps
- Auto-generated recommendations

## Supported Bosses

Works with any TBC raid boss, with enhanced mechanic tracking for:

- Kael'thas Sunstrider (conflagration tracking, phase detection)
- Lady Vashj
- Hydross the Unstable
- The Lurker Below
- Leotheras the Blind
- Fathom-Lord Karathress
- Morogrim Tidewalker

## Documentation

| Doc | Description |
|-----|-------------|
| [Analysis Tabs](docs/analysis-tabs.md) | What each tab shows and how to read it |
| [Raid Awards](docs/awards.md) | All award categories, how they're computed, and data requirements |
| [Log Comparison](docs/comparison.md) | How the comparison tool works and what it reports |
| [Data Model](docs/data-model.md) | Structure of the report JSON and what each field contains |
| [Scripts](docs/scripts.md) | CLI tools for local fetching, parsing, and comparing (advanced/optional) |

## Screenshots

<!-- TODO: Add screenshots of the main UI, awards, and comparison views -->

## Running Locally (Optional)

The tool is a static site — no server needed. If you want to run it locally or use the CLI scripts:

```
index.html              Main analysis UI (single-file app)
compare.html            Raid comparison UI
scripts/
  fetch_from_api.py     Fetch report data from WarcraftLogs v1 API
  parse_log.py          Parse raw WoWCombatLog.txt into report JSON
  compare_logs.py       Compare two reports and generate recommendations
```

Requires a modern browser. Python 3.9+ needed only for CLI scripts. See [docs/scripts.md](docs/scripts.md) for details.
