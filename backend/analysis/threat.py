"""Threat timeline analysis — per-enemy aggro segments with transition events."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.analysis.report import fetch_report_metadata, fetch_events_paginated
from backend.wcl.client import graphql_query
from backend.wcl.queries import REPORT_TABLE

# Known taunt ability IDs (TBC)
TAUNT_ABILITIES = {
    355,    # Taunt (Warrior)
    1161,   # Challenging Shout (Warrior)
    6795,   # Growl (Druid)
    31789,  # Righteous Defense (Paladin)
    694,    # Mocking Blow (Warrior)
    20736,  # Distracting Shot (Hunter)
}

# Known threat-drop abilities
THREAT_DROP_ABILITIES = {
    29858,  # Soulshatter (Warlock)
    34477,  # Misdirection (Hunter)
    1856,   # Vanish (Rogue)
    66,     # Invisibility (Mage)
    11958,  # Ice Block (Mage)
    5384,   # Feign Death (Hunter)
    1966,   # Feint (Rogue)
}


async def fetch_threat_data(report_code: str, fight_id: int) -> dict[str, Any]:
    """Fetch threat timeline using WCL Threat table bands.
    
    The Threat table provides exact aggro windows (bands) per player per enemy,
    including the events that started/ended each aggro window.
    """
    metadata = await fetch_report_metadata(report_code)
    fights = metadata.get("fights", [])
    actors = metadata.get("masterData", {}).get("actors", [])
    
    fight = next((f for f in fights if f["id"] == fight_id), None)
    if not fight:
        return {"error": "Fight not found", "enemies": []}
    
    start = fight["startTime"]
    end = fight["endTime"]
    duration_ms = end - start
    
    # Fetch threat table (has bands) + casts (for taunt correlation) + deaths
    table_task = _fetch_threat_table(report_code, fight_id, start, end)
    casts_task = fetch_events_paginated(report_code, [fight_id], "Casts", start, end)
    deaths_task = fetch_events_paginated(report_code, [fight_id], "Deaths", start, end)
    
    table_data, casts, deaths = await asyncio.gather(table_task, casts_task, deaths_task)
    
    # Index taunts by (target enemy, timestamp)
    taunt_events = []
    for cast in casts:
        ability_id = cast.get("abilityGameID", 0)
        if ability_id in TAUNT_ABILITIES:
            taunt_events.append(cast)
    
    # Index threat drops
    drop_events = []
    for cast in casts:
        ability_id = cast.get("abilityGameID", 0)
        if ability_id in THREAT_DROP_ABILITIES:
            drop_events.append(cast)
    
    # Index deaths by actor ID
    death_times: dict[int, list[int]] = {}
    for d in deaths:
        actor_id = d.get("targetID", 0)
        death_times.setdefault(actor_id, []).append(d.get("timestamp", 0))
    
    # Build actor ID->name map from table data
    actor_id_to_name: dict[int, str] = {}
    for a in actors:
        actor_id_to_name[a["id"]] = a.get("name", f"Actor #{a['id']}")
    
    # Process threat table into per-enemy timelines
    threats = table_data.get("threat", []) if table_data else []
    
    # Group bands by enemy (target) — keyed by ID to avoid name collisions
    enemy_bands: dict[int, list[dict]] = {}
    enemy_id_to_name: dict[int, str] = {}
    
    for player_entry in threats:
        player_name = player_entry.get("name", "Unknown")
        player_class = player_entry.get("type", "Unknown")
        player_id = player_entry.get("id", 0)
        
        for target in player_entry.get("targets", []):
            enemy_name = target.get("name", "Unknown")
            enemy_id = target.get("id", 0)
            bands = target.get("bands", [])
            
            enemy_id_to_name[enemy_id] = enemy_name
            if enemy_id not in enemy_bands:
                enemy_bands[enemy_id] = []
            
            for band in bands:
                enemy_bands[enemy_id].append({
                    "player": player_name,
                    "player_id": player_id,
                    "player_class": player_class,
                    "enemy_id": enemy_id,
                    "start_ms": band["startTime"] - start,
                    "end_ms": band["endTime"] - start,
                    "start_event": band.get("startEvent"),
                    "end_event": band.get("endEvent"),
                })
    
    # Build timelines per enemy
    timelines = []
    
    for enemy_id, bands in enemy_bands.items():
        enemy_name = enemy_id_to_name.get(enemy_id, f"Enemy #{enemy_id}")
        # Sort bands by start time
        bands.sort(key=lambda b: b["start_ms"])
        
        # Build segments and detect transitions
        segments = []
        transitions = []
        
        for i, band in enumerate(bands):
            segments.append({
                "player": band["player"],
                "player_class": band["player_class"],
                "start_ms": band["start_ms"],
                "end_ms": band["end_ms"],
            })
            
            # Detect transition from previous band holder
            if i > 0:
                prev = bands[i - 1]
                if prev["player"] != band["player"]:
                    reason = _classify_transition(
                        prev, band, start, 
                        taunt_events, drop_events, death_times
                    )
                    transitions.append({
                        "timestamp_ms": band["start_ms"],
                        "timestamp_s": round(band["start_ms"] / 1000, 1),
                        "from_player": prev["player"],
                        "to_player": band["player"],
                        "reason": reason["type"],
                        "detail": reason["detail"],
                    })
        
        if segments:
            timelines.append({
                "enemy_name": enemy_name,
                "segments": segments,
                "transitions": transitions,
            })
    
    # Sort enemies: bosses first, then by total aggro time
    timelines.sort(
        key=lambda t: sum(s["end_ms"] - s["start_ms"] for s in t["segments"]),
        reverse=True,
    )
    
    return {
        "fight_name": fight.get("name", "Unknown"),
        "fight_id": fight_id,
        "duration_ms": duration_ms,
        "duration_s": round(duration_ms / 1000, 1),
        "enemies": timelines,
    }


async def _fetch_threat_table(report_code, fight_id, start, end):
    """Fetch Threat table summary with bands."""
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


def _classify_transition(
    prev_band: dict,
    new_band: dict,
    fight_start: int,
    taunt_events: list[dict],
    drop_events: list[dict],
    death_times: dict[int, list[int]],
) -> dict:
    """Classify why aggro transferred between players."""
    WINDOW = 3000  # 3s correlation window
    transition_time = new_band["start_ms"] + fight_start
    
    # Check if new holder taunted near this time
    for t in taunt_events:
        ts = t.get("timestamp", 0)
        source = t.get("sourceID", 0)
        if (abs(ts - transition_time) < WINDOW and 
            source == new_band["player_id"]):
            ability_name = t.get("ability", {}).get("name", "Taunt")
            return {"type": "taunt", "detail": f"{new_band['player']} used {ability_name}"}
    
    # Check if previous holder died
    prev_deaths = death_times.get(prev_band["player_id"], [])
    for dt in prev_deaths:
        if abs(dt - transition_time) < WINDOW:
            return {"type": "death", "detail": f"{prev_band['player']} died"}
    
    # Check if previous holder used a threat drop
    for td in drop_events:
        ts = td.get("timestamp", 0)
        source = td.get("sourceID", 0)
        if (abs(ts - transition_time) < WINDOW and
            source == prev_band["player_id"]):
            ability_name = td.get("ability", {}).get("name", "threat drop")
            return {"type": "drop", "detail": f"{prev_band['player']} used {ability_name}"}
    
    # Check the startEvent on the band itself for clues
    start_evt = new_band.get("start_event")
    if start_evt:
        ability = start_evt.get("ability", {})
        ability_name = ability.get("name", "")
        # If the boss started meleeing the new player, it's a rip
        if ability_name == "Melee" and not start_evt.get("sourceIsFriendly", True):
            return {"type": "rip", "detail": f"{new_band['player']} pulled aggro"}
    
    return {"type": "rip", "detail": f"{new_band['player']} pulled aggro"}

