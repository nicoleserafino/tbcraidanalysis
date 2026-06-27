"""Threat timeline analysis — per-enemy aggro segments with transition events."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.analysis.report import fetch_report_metadata, fetch_events_paginated, fetch_table
from backend.wcl.client import graphql_query
from backend.wcl.queries import REPORT_TABLE

# Known taunt ability IDs (TBC)
TAUNT_ABILITIES = {
    355,    # Taunt (Warrior)
    1161,   # Challenging Shout (Warrior)
    5209,   # Challenging Roar (Druid — unused in TBC)
    6795,   # Growl (Druid)
    31789,  # Righteous Defense (Paladin)
    694,    # Mocking Blow (Warrior)
    20736,  # Distracting Shot (Hunter)
}

# Known threat-drop abilities
THREAT_DROP_ABILITIES = {
    29858,  # Soulshatter (Warlock)
    2894,   # Fire Elemental (Shaman — partial)
    34477,  # Misdirection (Hunter)
    21882,  # Blessing of Salvation proc
    26400,  # Tranquil Air Totem
    1856,   # Vanish (Rogue)
    2983,   # Sprint — not really threat drop
    18499,  # Berserker Rage (Warrior) — not really
    66,     # Invisibility (Mage)
    11958,  # Ice Block (Mage)
    5384,   # Feign Death (Hunter)
    1966,   # Feint (Rogue)
}


async def fetch_threat_data(report_code: str, fight_id: int) -> dict[str, Any]:
    """Fetch threat timeline data for a fight.
    
    Returns per-enemy timelines showing who held aggro and when,
    plus transition events with reasons (taunt, death, rip, threat drop).
    """
    metadata = await fetch_report_metadata(report_code)
    fights = metadata.get("fights", [])
    actors = metadata.get("masterData", {}).get("actors", [])
    
    fight = next((f for f in fights if f["id"] == fight_id), None)
    if not fight:
        return {"error": "Fight not found", "enemies": [], "legend": []}
    
    start = fight["startTime"]
    end = fight["endTime"]
    duration_ms = end - start
    
    # Build actor lookup
    actor_map = {}
    for a in actors:
        actor_map[a["id"]] = a
    
    # Fetch threat table (gives aggro summary per player per target)
    # and also fetch casts + deaths for transition context
    table_task = _fetch_threat_table(report_code, fight_id, start, end)
    casts_task = fetch_events_paginated(
        report_code, [fight_id], "Casts", start, end
    )
    deaths_task = fetch_events_paginated(
        report_code, [fight_id], "Deaths", start, end
    )
    # Fetch threat events for timeline
    threat_events_task = fetch_events_paginated(
        report_code, [fight_id], "Threat", start, end
    )
    
    table_data, casts, deaths, threat_events = await asyncio.gather(
        table_task, casts_task, deaths_task, threat_events_task
    )
    
    # Index taunts and threat drops by timestamp
    taunts = []
    threat_drops = []
    for cast in casts:
        ability_id = cast.get("abilityGameID", 0)
        if ability_id in TAUNT_ABILITIES:
            taunts.append(cast)
        elif ability_id in THREAT_DROP_ABILITIES:
            threat_drops.append(cast)
    
    # Index deaths by timestamp (sourceID = the dead player)
    death_times = {}
    for d in deaths:
        ts = d.get("timestamp", 0)
        source = d.get("sourceID") or d.get("targetID", 0)
        death_times.setdefault(source, []).append(ts)
    
    # Build per-enemy timelines from threat events
    # Group threat events by targetID (the enemy being attacked)
    enemy_events: dict[int, list[dict]] = {}
    for evt in threat_events:
        target_id = evt.get("targetID", 0)
        enemy_events.setdefault(target_id, []).append(evt)
    
    # Also use table data to get the list of enemies with threat info
    table_threats = table_data.get("threat", []) if table_data else []
    
    # Build enemy list from threat events
    enemy_ids_from_events = set(enemy_events.keys())
    
    # Also get enemies from table data (targets within player entries)
    enemy_names_from_table: dict[int, str] = {}
    player_classes: dict[str, str] = {}
    for entry in table_threats:
        player_name = entry.get("name", "Unknown")
        player_classes[player_name] = entry.get("type", "Unknown")
        for t in entry.get("targets", []):
            # Table targets don't have IDs directly, track by name
            pass
    
    # Build timelines per enemy from threat events
    timelines = _build_timelines(
        enemy_events, actor_map, taunts, death_times, threat_drops,
        start, end, duration_ms
    )
    
    # Build player legend (unique players who held aggro)
    legend_players = set()
    for timeline in timelines:
        for seg in timeline.get("segments", []):
            legend_players.add(seg["player"])
    
    # Get class info from table data
    for entry in table_threats:
        player_classes[entry.get("name", "Unknown")] = entry.get("type", "Unknown")
    
    # Also try actor_map for class info
    for a in actors:
        if a.get("type") == "Player" and a.get("name"):
            player_classes.setdefault(a["name"], a.get("subType", "Unknown"))
    
    legend = []
    for name in sorted(legend_players):
        legend.append({
            "name": name,
            "class": player_classes.get(name, "Unknown"),
        })
    
    return {
        "fight_name": fight.get("name", "Unknown"),
        "fight_id": fight_id,
        "duration_ms": duration_ms,
        "duration_s": round(duration_ms / 1000, 1),
        "enemies": timelines,
        "legend": legend,
    }


async def _fetch_threat_table(report_code, fight_id, start, end):
    """Fetch Threat table summary."""
    variables = {
        "code": report_code,
        "fightIDs": [fight_id],
        "dataType": "Threat",
        "startTime": start,
        "endTime": end,
    }
    data = await graphql_query(REPORT_TABLE, variables)
    table = data["reportData"]["report"]["table"]
    if isinstance(table, dict) and "data" in table:
        return table["data"]
    return table


def _build_timelines(
    enemy_events: dict[int, list[dict]],
    actor_map: dict[int, dict],
    taunts: list[dict],
    death_times: dict[int, list[int]],
    threat_drops: list[dict],
    fight_start: int,
    fight_end: int,
    duration_ms: int,
) -> list[dict]:
    """Build per-enemy aggro timelines from threat events.
    
    Each enemy gets a list of segments (who held aggro and when)
    and transition events (why aggro changed).
    """
    # Index taunts by timestamp window for quick lookup
    taunt_index = {}  # (sourceID, timestamp) for matching
    for t in taunts:
        ts = t.get("timestamp", 0)
        source = t.get("sourceID", 0)
        target = t.get("targetID", 0)  # the enemy being taunted
        taunt_index.setdefault(target, []).append({
            "timestamp": ts,
            "player_id": source,
            "ability": t.get("abilityGameID", 0),
        })
    
    timelines = []
    
    for enemy_id, events in sorted(enemy_events.items()):
        enemy_info = actor_map.get(enemy_id, {})
        enemy_name = enemy_info.get("name", f"Enemy #{enemy_id}")
        enemy_type = enemy_info.get("type", "")
        
        # Skip friendly/player entries
        if enemy_type == "Player":
            continue
        
        # Sort events by timestamp
        events.sort(key=lambda e: e.get("timestamp", 0))
        
        # Track who currently has aggro based on threat values
        # WCL threat events have sourceID = player generating threat,
        # targetID = enemy. We need to track who has max threat.
        player_threat: dict[int, float] = {}
        current_holder: int | None = None
        segments: list[dict] = []
        transitions: list[dict] = []
        segment_start = fight_start
        
        for evt in events:
            ts = evt.get("timestamp", 0)
            source_id = evt.get("sourceID", 0)
            threat_val = evt.get("threat", 0)
            
            # Update threat tracking
            if source_id:
                player_threat[source_id] = player_threat.get(source_id, 0) + threat_val
            
            # Determine new aggro holder (highest threat)
            if player_threat:
                new_holder = max(player_threat, key=lambda k: player_threat[k])
            else:
                new_holder = current_holder
            
            # Detect aggro transition
            if new_holder != current_holder and current_holder is not None:
                # Close previous segment
                holder_name = actor_map.get(current_holder, {}).get("name", f"Player #{current_holder}")
                new_name = actor_map.get(new_holder, {}).get("name", f"Player #{new_holder}")
                
                segments.append({
                    "player": holder_name,
                    "player_id": current_holder,
                    "start_ms": segment_start - fight_start,
                    "end_ms": ts - fight_start,
                })
                
                # Determine reason for transition
                reason = _determine_transition_reason(
                    current_holder, new_holder, ts, enemy_id,
                    taunt_index, death_times, threat_drops, actor_map
                )
                
                transitions.append({
                    "timestamp_ms": ts - fight_start,
                    "timestamp_s": round((ts - fight_start) / 1000, 1),
                    "from_player": holder_name,
                    "to_player": new_name,
                    "reason": reason["type"],
                    "detail": reason["detail"],
                })
                
                segment_start = ts
            
            if current_holder is None and new_holder is not None:
                segment_start = ts
            
            current_holder = new_holder
        
        # Close final segment
        if current_holder is not None:
            holder_name = actor_map.get(current_holder, {}).get("name", f"Player #{current_holder}")
            segments.append({
                "player": holder_name,
                "player_id": current_holder,
                "start_ms": segment_start - fight_start,
                "end_ms": duration_ms,
            })
        
        # Only include enemies with meaningful aggro data
        if segments:
            timelines.append({
                "enemy_id": enemy_id,
                "enemy_name": enemy_name,
                "segments": segments,
                "transitions": transitions,
            })
    
    # Sort by total segment time (most relevant enemies first)
    timelines.sort(
        key=lambda t: sum(s["end_ms"] - s["start_ms"] for s in t["segments"]),
        reverse=True,
    )
    
    return timelines


def _determine_transition_reason(
    prev_holder: int,
    new_holder: int,
    timestamp: int,
    enemy_id: int,
    taunt_index: dict,
    death_times: dict,
    threat_drops: list[dict],
    actor_map: dict,
) -> dict:
    """Determine why aggro changed: taunt, death, threat drop, or rip."""
    WINDOW = 2000  # 2s window to correlate events
    
    # Check if new holder taunted
    enemy_taunts = taunt_index.get(enemy_id, [])
    for t in enemy_taunts:
        if abs(t["timestamp"] - timestamp) < WINDOW and t["player_id"] == new_holder:
            return {"type": "taunt", "detail": "Taunted"}
    
    # Check if previous holder died
    prev_deaths = death_times.get(prev_holder, [])
    for dt in prev_deaths:
        if abs(dt - timestamp) < WINDOW:
            prev_name = actor_map.get(prev_holder, {}).get("name", "Unknown")
            return {"type": "death", "detail": f"{prev_name} died"}
    
    # Check if previous holder used a threat drop
    for td in threat_drops:
        if (td.get("sourceID") == prev_holder and 
            abs(td.get("timestamp", 0) - timestamp) < WINDOW):
            ability_name = td.get("ability", {}).get("name", "threat drop")
            if not ability_name:
                ability_name = "threat drop"
            prev_name = actor_map.get(prev_holder, {}).get("name", "Unknown")
            return {"type": "drop", "detail": f"{prev_name} used {ability_name}"}
    
    # Default: threat rip (new holder just out-threated)
    new_name = actor_map.get(new_holder, {}).get("name", "Unknown")
    return {"type": "rip", "detail": f"{new_name} ripped aggro"}

