# Analysis Tabs

The main analysis UI provides several tabs for breaking down raid performance. Each tab offers a different lens on the same underlying pull data.

## Summary

The default view for each pull. Shows:

- **Kill/wipe status** and pull duration
- **Death timeline** — who died, when, and in what order
- **Damage source breakdown** — top sources of incoming raid damage
- **Damage ability breakdown** — which specific abilities hit the raid hardest
- **Player damage taken** — per-player breakdown of damage sources (useful for identifying players standing in mechanics)

When viewing the "All Pulls — Progression Summary":
- Progression timeline across all attempts
- Kill/wipe ratio
- Average pull duration trends

## Action Items

Auto-generated improvement suggestions aggregated across all pulls for the selected boss. Includes:

- Players who died repeatedly and to what
- Common death causes that suggest mechanical failures
- Patterns in early deaths

This tab works regardless of which pull is selected — it always shows the full-boss aggregate view.

## Awards

Raid-wide awards highlighting standout and meme-worthy moments. Aggregated across ALL bosses in the report (not just the currently selected boss). See [awards.md](awards.md) for the full list of categories.

## Strategy

Boss-specific context including:

- Phase timeline (for multi-phase encounters like Kael'thas)
- Creature death tracking (advisor kills, add waves)
- Conflagration tracking (Kael'thas specific)
- Key mechanic events mapped to the pull timeline

## Tanks

Tank-focused metrics per pull:

- Damage intake by source
- Active mitigation uptime (inferred from spell casts)
- Death timing relative to cooldown usage
- Comparison across multiple tanks in the same pull

In "All Pulls" summary mode: aggregated tank performance trends across all attempts.

## Healers

Healer-focused metrics per pull:

- Total healing and HPS per healer
- Overheal percentage and breakdown by spell
- Heal spell distribution (efficiency analysis)
- HOT vs direct heal ratios

In "All Pulls" summary mode: healing throughput trends, mana usage patterns.

## DPS

DPS-focused metrics per pull:

- Total damage and DPS per player
- Spell breakdown showing damage distribution
- Damage done ranking
- Activity rate (casts per minute)

In "All Pulls" summary mode: DPS consistency, performance trends across attempts.

## Individual

Per-player deep dive available for any player in the raid:

- Full spell cast breakdown
- Buff/debuff uptimes with timeline visualization
- Cooldown usage tracking (trinkets, class cooldowns, consumables)
- Cast timeline density chart
- Damage done and healing done breakdowns

## Navigation

- **Boss selector** — switch between bosses in the report
- **Pull selector** — pick a specific attempt or view "All Pulls" summary
- **Player filter** — available in some tabs to focus on a specific player
- **Back button** — return to the report URL input to load a different log

