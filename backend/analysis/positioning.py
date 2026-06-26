"""Player positioning analysis for raid fights.

Fetches position data from WCL v2 API (via includeResources on events)
and identifies positioning issues around key mechanic events like
Conflagration spread, grouping failures, etc.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from backend.wcl.client import graphql_query


# Mechanics worth tracking positions for (spell IDs)
TRACKED_MECHANICS = {
    # Kael'thas - Conflagration from Capernian
    37018: {"name": "Conflagration", "boss": "Kael'thas Sunstrider", "spread_range": 1500, "type": "spread"},
    37019: {"name": "Conflagration", "boss": "Kael'thas Sunstrider", "spread_range": 1500, "type": "spread"},
    # Hydross - Water Tomb (targets random players)
    38235: {"name": "Water Tomb", "boss": "Hydross the Unstable", "type": "stack"},
    # Vashj - Static Charge (must spread)
    38280: {"name": "Static Charge", "boss": "Lady Vashj", "spread_range": 4000, "type": "spread"},
    # Morogrim - Watery Grave (players teleported)
    37850: {"name": "Watery Grave", "boss": "Morogrim Tidewalker", "type": "displacement"},
    # Solarian - Wrath of the Astromancer (debuff that explodes on nearby)
    42783: {"name": "Wrath of the Astromancer", "boss": "High Astromancer Solarian", "spread_range": 4000, "type": "spread"},
    # Al'ar - Flame Quills (players must be below platform)
    35383: {"name": "Flame Quills", "boss": "Al'ar", "type": "positioning"},
}

POSITION_QUERY = """
query ($code: String!, $fightIDs: [Int]!, $dataType: EventDataType!, $startTime: Float!, $endTime: Float!, $filterExpression: String) {
  reportData {
    report(code: $code) {
      events(
        fightIDs: $fightIDs
        dataType: $dataType
        startTime: $startTime
        endTime: $endTime
        includeResources: true
        filterExpression: $filterExpression
      ) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

DEBUFF_QUERY = """
query ($code: String!, $fightIDs: [Int]!, $startTime: Float!, $endTime: Float!, $filterExpression: String) {
  reportData {
    report(code: $code) {
      events(
        fightIDs: $fightIDs
        dataType: Debuffs
        startTime: $startTime
        endTime: $endTime
        filterExpression: $filterExpression
      ) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

META_QUERY = """
query ($code: String!) {
  reportData {
    report(code: $code) {
      fights(killType: Encounters) {
        id
        name
        encounterID
        startTime
        endTime
        kill
      }
      masterData {
        actors { id name type subType }
        abilities { gameID name }
      }
    }
  }
}
"""


def _distance(p1: dict, p2: dict) -> float:
    """Euclidean distance between two position points."""
    return math.sqrt((p1["x"] - p2["x"]) ** 2 + (p1["y"] - p2["y"]) ** 2)


async def _fetch_positions_at_time(
    code: str, fight_id: int, timestamp: float, window_ms: int = 3000,
    players: dict[int, str] | None = None,
) -> dict[str, dict]:
    """Fetch player positions near a timestamp by combining multiple event types.
    
    Returns {player_name: {x, y, ts}} for the closest event to timestamp.
    """
    start = timestamp - window_ms
    end = timestamp + window_ms

    positions: dict[str, dict] = {}

    async def _fetch_one(dtype: str):
        variables = {
            "code": code,
            "fightIDs": [fight_id],
            "dataType": dtype,
            "startTime": start,
            "endTime": end,
        }
        try:
            data = await graphql_query(POSITION_QUERY, variables)
            return data["reportData"]["report"]["events"].get("data", [])
        except Exception:
            return []

    # Fetch all data types in parallel
    results = await asyncio.gather(
        _fetch_one("Casts"), _fetch_one("DamageDone"), _fetch_one("Healing")
    )

    for events in results:
        for e in events:
            if "x" not in e or "sourceID" not in e:
                continue
            sid = e["sourceID"]
            if players and sid not in players:
                continue
            name = players[sid] if players else str(sid)
            # Keep position closest to target timestamp
            if name not in positions or abs(e["timestamp"] - timestamp) < abs(positions[name]["ts"] - timestamp):
                positions[name] = {"x": e["x"], "y": e["y"], "ts": e["timestamp"]}

    return positions


async def fetch_positioning_data(report_code: str, fight_id: int) -> dict[str, Any]:
    """Fetch positioning snapshots for tracked mechanic events in a fight.
    
    Returns mechanic events with player positions at each event time,
    distance calculations, and spread analysis.
    """
    # Get metadata
    meta = await graphql_query(META_QUERY, {"code": report_code})
    report = meta["reportData"]["report"]

    fight = next((f for f in report["fights"] if f["id"] == fight_id), None)
    if not fight:
        return {"error": "Fight not found", "events": []}

    start = fight["startTime"]
    end = fight["endTime"]
    duration_s = (end - start) / 1000

    # Build actor maps
    actors = report["masterData"]["actors"]
    player_map = {a["id"]: a["name"] for a in actors if a["type"] == "Player"}
    player_classes = {a["name"]: a.get("subType", "Unknown") for a in actors if a["type"] == "Player"}
    abilities = {a["gameID"]: a["name"] for a in report["masterData"]["abilities"]}

    # Find which tracked mechanics are in this fight's ability list
    fight_mechanics = {}
    for ability in report["masterData"]["abilities"]:
        gid = ability["gameID"]
        if gid in TRACKED_MECHANICS:
            fight_mechanics[gid] = TRACKED_MECHANICS[gid]

    if not fight_mechanics:
        # No tracked mechanics — return all player positions at a few timestamps
        # to still show a general positioning view
        snapshots = []
        # Sample 5 evenly-spaced timestamps
        for i in range(5):
            ts = start + (end - start) * (i + 1) / 6
            positions = await _fetch_positions_at_time(
                report_code, fight_id, ts, window_ms=5000, players=player_map
            )
            snapshots.append({
                "time_s": round((ts - start) / 1000, 1),
                "label": f"Positions at {round((ts - start) / 1000)}s",
                "positions": {
                    name: {"x": p["x"], "y": p["y"], "class": player_classes.get(name, "Unknown")}
                    for name, p in positions.items()
                },
                "highlights": [],
            })
        return {
            "fight_name": fight["name"],
            "fight_id": fight_id,
            "kill": fight.get("kill", False),
            "duration_s": round(duration_s, 1),
            "has_mechanics": False,
            "snapshots": snapshots,
        }

    # Fetch debuff application events for tracked mechanics
    mechanic_ids = list(fight_mechanics.keys())
    filter_expr = " OR ".join(f"ability.id={mid}" for mid in mechanic_ids)

    variables = {
        "code": report_code,
        "fightIDs": [fight_id],
        "startTime": float(start),
        "endTime": float(end),
        "filterExpression": filter_expr,
    }
    debuff_data = await graphql_query(DEBUFF_QUERY, variables)
    debuff_events = debuff_data["reportData"]["report"]["events"].get("data", [])

    # Group apply events by timestamp (same-time applies = one mechanic cast)
    mechanic_instances: list[dict] = []
    current_group: dict | None = None

    for e in debuff_events:
        if e.get("type") != "applydebuff":
            continue
        ts = e["timestamp"]
        ability_id = e.get("abilityGameID", 0)
        target_name = player_map.get(e.get("targetID"), "Unknown")

        # Group events within 500ms as same cast
        if current_group is None or abs(ts - current_group["timestamp"]) > 500:
            current_group = {
                "timestamp": ts,
                "ability_id": ability_id,
                "ability_name": abilities.get(ability_id, "Unknown"),
                "mechanic": fight_mechanics.get(ability_id, {}),
                "targets": [],
            }
            mechanic_instances.append(current_group)

        current_group["targets"].append(target_name)

    # Limit mechanic instances to avoid excessive API calls (3 calls per snapshot)
    MAX_SNAPSHOTS = 10
    if len(mechanic_instances) > MAX_SNAPSHOTS:
        mechanic_instances = mechanic_instances[:MAX_SNAPSHOTS]

    # Fetch all position snapshots in parallel
    position_tasks = [
        _fetch_positions_at_time(report_code, fight_id, float(inst["timestamp"]), window_ms=3000, players=player_map)
        for inst in mechanic_instances
    ]
    all_positions = await asyncio.gather(*position_tasks)

    # Build snapshots with distance calculations
    snapshots = []
    for instance, positions in zip(mechanic_instances, all_positions):

        targets = instance["targets"]
        mechanic_info = instance["mechanic"]
        spread_range = mechanic_info.get("spread_range", 3000)

        # Calculate proximity analysis
        proximity_issues = []
        if mechanic_info.get("type") == "spread" and len(targets) > 1:
            # Multiple targets = spread happened. First target is primary, rest are spread victims.
            primary = targets[0]
            spread_victims = targets[1:]
            if primary in positions:
                # Show distances from primary to spread victims
                for victim in spread_victims:
                    if victim in positions:
                        dist = _distance(positions[primary], positions[victim])
                        proximity_issues.append({
                            "player": victim,
                            "near": primary,
                            "distance": round(dist),
                            "was_hit": True,
                        })
                # Also show nearby non-targets that were close but safe
                for name, pos in positions.items():
                    if name == primary or name in targets:
                        continue
                    dist = _distance(positions[primary], pos)
                    if dist < spread_range:
                        proximity_issues.append({
                            "player": name,
                            "near": primary,
                            "distance": round(dist),
                            "was_hit": False,
                        })
            proximity_issues.sort(key=lambda x: x["distance"])

        # Format positions for response
        pos_data = {}
        for name, p in positions.items():
            pos_data[name] = {
                "x": p["x"],
                "y": p["y"],
                "class": player_classes.get(name, "Unknown"),
                "hit": name in targets,
            }

        snapshots.append({
            "time_s": round((instance["timestamp"] - start) / 1000, 1),
            "label": f"{instance['ability_name']} at {round((instance['timestamp'] - start) / 1000, 1)}s",
            "ability": instance["ability_name"],
            "ability_id": instance["ability_id"],
            "targets": targets,
            "target_count": len(targets),
            "positions": pos_data,
            "highlights": targets,
            "proximity_issues": proximity_issues,
            "spread_range": spread_range,
            "mechanic_type": mechanic_info.get("type", "unknown"),
        })

    return {
        "fight_name": fight["name"],
        "fight_id": fight_id,
        "kill": fight.get("kill", False),
        "duration_s": round(duration_s, 1),
        "has_mechanics": True,
        "tracked_abilities": [
            {"id": mid, "name": info["name"], "type": info.get("type", "unknown")}
            for mid, info in fight_mechanics.items()
        ],
        "snapshots": snapshots,
    }
