# Log Comparison

The comparison tool lets you diff two WarcraftLogs reports side-by-side to identify performance gaps, pacing differences, and buff/comp advantages.

## Usage

From the main analysis UI, click **Compare Logs** in the top bar — or navigate directly to the compare page at [nicoleserafino.github.io/tbcraidanalysis/compare.html](https://nicoleserafino.github.io/tbcraidanalysis/compare.html).

Paste two report URLs and the tool will show you a full breakdown of differences.

### CLI (advanced/optional)

If you prefer to generate comparison data locally:

```bash
python3 scripts/compare_logs.py \
  "https://fresh.warcraftlogs.com/reports/YOUR_REPORT" \
  "https://fresh.warcraftlogs.com/reports/THEIR_REPORT"
```

This generates `data/comparison.json` and rebuilds `compare.html` with the embedded data.

## What Gets Compared

### Raid Composition

- Total player count and role breakdown (Tank/Healer/DPS)
- Class distribution differences

### Boss-by-Boss

For each boss killed in either report:

- **Kill time** — who killed it faster and by how much
- **Raid DPS/HPS** — overall throughput delta
- **Overheal %** — healing efficiency comparison
- **Buff coverage** — which raid buffs they have that you're missing (and vice versa)
- **Cooldown timing** — Bloodlust/Heroism usage timing differences
- **Top DPS/Healer rankings** — per-player performance comparison
- **Per-player damage** — full damage breakdown available for every player

### Pacing

- **Total raid time** — end-to-end comparison
- **Non-combat time** — time spent between boss kills (trash, running, rebuffing)
- **Trash time** — estimated time spent on trash packs
- **Per-boss gap time** — how long between each kill

### Auto-Generated Recommendations

The comparison tool automatically generates actionable tips based on the biggest deltas:

- **Pacing** — if your non-combat time is significantly higher
- **Kill speed** — bosses where you're notably slower, with missing buff analysis
- **Trash** — if trash clearing takes significantly longer
- **Cooldown timing** — differences in Bloodlust/Heroism usage timing

## Output Format

The comparison JSON (`data/comparison.json`) contains:

```json
{
  "ours": { "report_id": "...", "url": "...", "title": "...", "owner": "..." },
  "theirs": { "report_id": "...", "url": "...", "title": "...", "owner": "..." },
  "comp": { "ours": { "total": 25, "roles": {...}, "classes": {...} }, "theirs": {...} },
  "roster": { "ours": { "PlayerName": { "class": "Shaman", "role": "DPS", "icon": "..." } }, "theirs": {...} },
  "bosses": [ { "name": "...", "ours": {...}, "theirs": {...}, "delta": {...} } ],
  "pacing": { "ours": {...}, "theirs": {...}, "delta_total_ms": ..., "delta_gap_ms": ... },
  "recommendations": [ { "category": "...", "title": "...", "detail": "..." } ]
}
```

## Requirements

- Python 3.9+
- A `.env` file with `API_KEY=your_wcl_v1_key` in the project root
- Both reports must be accessible with the provided API key (public or your own unlisted logs)

## Limitations

- Only compares boss kills (wipes are excluded)
- Relies on matching boss names between reports
- Cooldown detection is limited to the spells defined in `MAJOR_COOLDOWNS`
- Per-player damage uses the WCL `tables/damage-done` endpoint (aggregated, not per-hit)

<!-- TODO: Screenshot of compare.html showing boss comparison and recommendations -->
