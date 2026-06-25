# Scripts (Legacy / Optional)

CLI tools for fetching, parsing, and comparing WarcraftLogs raid data locally using the **v1 API**. **These are not required to use the tool** — the hosted version uses a FastAPI backend with the WCL v2 API.

These scripts are useful if you want to:
- Process raw combat log files (`WoWCombatLog.txt`)
- Pre-fetch data for offline analysis
- Run comparisons with full per-event data locally
- Extend the tool with custom analysis

All scripts are in the `scripts/` directory and require Python 3.9+.

> **Note:** These scripts use the WCL v1 API which requires a personal API key. The main app uses v2 OAuth handled by the backend — no API key needed.

## fetch_from_api.py

Fetches raid data from the WarcraftLogs v1 API and generates a report JSON file.

### Usage

```bash
python3 scripts/fetch_from_api.py <report_url> [output_path]
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `report_url` | Full WarcraftLogs URL (e.g., `https://fresh.warcraftlogs.com/reports/ABC123`) | Required |
| `output_path` | Where to write the output JSON | `data/report.json` |

### Requirements

- `.env` file in project root with `API_KEY=your_v1_key_here`
- Python 3.9+

### What it fetches per pull

- Deaths (player and enemy)
- Interrupts
- Dispels
- Healing events (with per-event hitPoints for clutch detection)
- Cast events
- Damage taken events
- Damage done events (per-hit for crit tracking)
- Damage done table (aggregated per-player totals)
- Buff events (applications, removals, refreshes)
- Conflagration events (Kael-specific)

### Rate Limiting

The script includes a 0.5-second delay between API requests to stay within WarcraftLogs rate limits. A full raid with 6 bosses and multiple pulls typically takes 2-5 minutes to fetch.

### Output

Generates a JSON file matching the [data model](data-model.md) structure. The file can be loaded directly by `index.html`.

---

## parse_log.py

Parses a raw `WoWCombatLog.txt` file into the same report JSON format.

### Usage

```bash
python3 scripts/parse_log.py <path_to_combat_log> [output_path]
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `path_to_combat_log` | Path to `WoWCombatLog.txt` | Required |
| `output_path` | Where to write the output JSON | `data/report.json` |

### Advantages over API fetch

- **Consumable tracking** — detects potion, flask, food, and rune usage from combat log events
- **Talent spec detection** — infers talent specs from spell usage patterns
- **More accurate role detection** — uses talent-based role assignment per encounter
- **No API key needed** — works entirely offline
- **No rate limiting** — processes instantly

### Limitations

- Requires the raw combat log file (not always accessible to non-loggers)
- File must be from the logging player's perspective
- Very large logs may take a few seconds to parse

---

## compare_logs.py

Compares two WarcraftLogs reports and generates a comparison payload with recommendations.

### Usage

```bash
python3 scripts/compare_logs.py <our_report_url> <their_report_url>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `our_report_url` | Your raid's WarcraftLogs URL |
| `their_report_url` | The raid you're comparing against |

### What it compares

- **Composition** — role and class counts
- **Boss kill times** — who kills each boss faster
- **Raid DPS/HPS** — throughput deltas per boss
- **Buff coverage** — which buffs each raid has/lacks
- **Cooldown timing** — when Bloodlust/Heroism was used (% into fight)
- **Pacing** — non-combat time, trash time, total raid duration
- **Per-player damage/healing** — full roster breakdown per boss

### Output

- `data/comparison.json` — structured comparison data
- Updates `compare.html` with embedded comparison data (if the file exists)

### Auto-Generated Recommendations

The script identifies the biggest performance gaps and generates actionable tips:

- Pacing issues (too much downtime between bosses)
- Kill speed deltas with missing buff analysis
- Trash efficiency differences
- Cooldown timing discrepancies

See [comparison.md](comparison.md) for full output format details.

---

## Environment Setup

All scripts read the API key from a `.env` file in the project root:

```
API_KEY=your_warcraftlogs_v1_api_key
```

Get your key from [WarcraftLogs Profile Settings](https://fresh.warcraftlogs.com/profile) under the "Web API" section (v1 key).

## Python Dependencies

No external packages required. All scripts use only Python standard library modules:
- `json`, `re`, `sys`, `time`
- `collections` (Counter, defaultdict)
- `pathlib`, `urllib`
