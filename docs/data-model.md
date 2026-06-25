# Data Model

This document describes the structure of the report JSON returned by the backend API (`GET /api/report/{code}`). The same structure is consumed by `frontend/index.html` for rendering.

## Top-Level Structure

```json
{
  "log_info": {
    "file": "ABC123",
    "total_encounters": 6,
    "report_id": "ABC123",
    "title": "SSC / TK"
  },
  "players": {
    "PlayerName": { "role": "Tank|Healer|DPS", "class": "Warrior|Paladin|..." }
  },
  "bosses": {
    "Boss Name": {
      "total_pulls": 5,
      "kills": 1,
      "wipes": 4,
      "pulls": [ <Pull>, <Pull>, ... ]
    }
  }
}
```

## Pull Object

Each pull contains the full breakdown of a single boss attempt:

```json
{
  "encounter_id": 733,
  "boss_name": "Kael'thas Sunstrider",
  "start_time": "2024-01-15 20:30:00",
  "end_time": "2024-01-15 20:45:00",
  "duration_sec": 260.5,
  "kill": false,
  "players": ["Player1", "Player2", "..."],

  "deaths": [
    { "time": "20:32:15", "relative_time": 135.2, "player": "PlayerName" }
  ],

  "damage_sources": {
    "Boss Name": { "Player1": 5, "Player2": 3 }
  },

  "damage_abilities": {
    "Fireball": 12, "Conflagration": 5
  },

  "player_damage_taken": {
    "Player1": { "Boss: Fireball": 3, "Boss: Melee": 10 }
  },

  "creature_deaths": [
    { "time": "20:33:00", "relative_time": 60.0, "name": "Thaladred the Darkener" }
  ],

  "interrupts": [
    { "time": "20:31:00", "relative_time": 60.0, "source": "Player1", "target": "Mob Name" }
  ],

  "dispels": [
    { "time": "20:31:05", "relative_time": 65.0, "source": "Player2" }
  ],

  "conflagrations": [
    { "time": "20:32:00", "relative_time": 120.0, "target": "Player3" }
  ],

  "heals_by_player": { "Healer1": 145, "Healer2": 120 },

  "heal_details": {
    "Healer1": {
      "Circle of Healing": { "total": 250000, "overheal": 80000, "count": 50, "is_hot": false },
      "Renew": { "total": 45000, "overheal": 12000, "count": 30, "is_hot": true }
    }
  },

  "casts_by_player": { "Player1": 180, "Player2": 155 },

  "cast_timeline": {
    "Player1": [0.5, 2.8, 5.1, 7.3, "..."]
  },

  "spell_casts": {
    "Player1": { "Lightning Bolt": 70, "Chain Lightning": 14, "Drums of Battle": 2 }
  },

  "damage_done": {
    "Player1": { "Lightning Bolt": 194000, "Chain Lightning": 29000 }
  },

  "buff_events": {
    "Player1": [
      { "spell": "Flask of Pure Death", "type": "applybuff", "time": 0.5 },
      { "spell": "Flask of Pure Death", "type": "removebuff", "time": 260.0 }
    ]
  },

  "consumables": {},

  "clutch_heals": [
    { "healer": "Healer1", "target": "Tank1", "spell": "Flash of Light", "amount": 4500, "hp_pct": 3.2, "time": 45.0, "self_heal": false }
  ],

  "biggest_heals": [
    { "player": "Healer1", "target": "Tank1", "spell": "Holy Light", "amount": 12000, "crit": true, "time": 80.0 }
  ],

  "biggest_crits": [
    { "player": "Mage1", "spell": "Fireball", "amount": 8500, "type": "damage", "time": 30.0 }
  ]
}
```

## Field Notes

### deaths

Sorted by time of death. The first entry is the first player to die on the pull.

### player_damage_taken

Keys are formatted as `"Source: Ability"` with hit counts as values (not damage amounts). Used for mechanic failure detection.

### heal_details

Per-healer, per-spell breakdown. `total` is effective healing, `overheal` is wasted healing. `is_hot` indicates if the spell is a heal-over-time.

### buff_events

Chronological list of buff applications, removals, and refreshes. Types: `applybuff`, `removebuff`, `refreshbuff`, `applydebuff`, `removedebuff`.

### clutch_heals

Sorted by HP% ascending (most clutch first). `hp_pct` is the target's HP percentage *before* the heal landed.

**Note:** The WCL v2 API does not include `hitPoints` in heal events, so clutch heal detection is currently limited when using the backend. The legacy v1 scripts and raw log parser still support full clutch heal tracking.

### biggest_heals / biggest_crits

Top 5 per pull, sorted by amount descending.

### threat_events (v2 only)

Threat events from the WCL v2 API. Each entry has `player`, `amount`, and `time` fields. Not available via v1 API.

### consumables

Currently empty (`{}`) when fetched via the API. Only populated from raw combat log parsing via `parse_log.py`.

## Data Sources

The primary data source is the **WCL v2 GraphQL API** via the FastAPI backend. The backend handles OAuth authentication and returns normalized data matching this model.

### v2 API Notes

- Spell names are resolved from `masterData.abilities` using `abilityGameID`
- Roles are inferred from class, spell usage, healing output, and damage taken patterns
- `hitPoints` is **not available** in v2 heal events — clutch heal detection is limited
- Threat events are available in v2 (not in v1) — enables future threat analysis
- `encounterID` replaces `boss` for boss identification

### Legacy CLI Scripts

The `scripts/` directory contains v1-API-based tools (`fetch_from_api.py`, `parse_log.py`) that produce the same data shape. These are optional and not required for normal use.

| Feature | Backend (v2 API) | Legacy Script (v1 API) | Raw Log Parser |
|---------|-----------------|------------------------|----------------|
| Clutch heal detection | Limited (no hitPoints) | Yes | Yes |
| Threat events | Yes | No | No |
| Buff events | Yes | Yes | Yes |
| Consumable tracking | Limited | Limited | Full |
| Role inference | Spell + healing heuristics | Icon + spec suffix | Talent-based |
