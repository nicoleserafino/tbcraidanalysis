"""Threat/aggro data fetching for raid analysis."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.analysis.report import fetch_report_metadata, fetch_table


async def fetch_threat_data(report_code: str, fight_id: int) -> dict[str, Any]:
    """Fetch aggro/threat data from the WCL Threat table for a fight.
    
    The Threat table shows who held aggro on each enemy and for how long.
    Returns per-player aggro uptime and per-enemy breakdown.
    """
    metadata = await fetch_report_metadata(report_code)
    fights = metadata.get("fights", [])
    
    fight = next((f for f in fights if f["id"] == fight_id), None)
    if not fight:
        return {"error": "Fight not found", "players": [], "enemies": []}
    
    start = fight["startTime"]
    end = fight["endTime"]
    total_time_ms = end - start
    
    # Fetch threat table (gives aggro assignments)
    from backend.wcl.client import graphql_query
    from backend.wcl.queries import REPORT_TABLE
    
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
        table = table["data"]
    
    threats = table.get("threat", [])
    total_time = table.get("totalTime", total_time_ms) or total_time_ms
    
    # Aggregate per-player: total aggro uptime across all enemies
    player_aggro: dict[str, dict] = {}
    enemies_tanked: list[dict] = []
    
    for entry in threats:
        player_name = entry.get("name", "Unknown")
        player_class = entry.get("type", "Unknown")
        uptime = entry.get("totalUptime", 0)
        targets = entry.get("targets", [])
        
        # Each entry is a player, targets are NPCs they tanked
        target_list = []
        for t in targets:
            target_list.append({
                "name": t.get("name", "Unknown"),
                "uptime_ms": t.get("totalUptime", 0),
            })
        
        if player_name not in player_aggro:
            player_aggro[player_name] = {
                "name": player_name,
                "class": player_class,
                "total_uptime_ms": 0,
                "targets": [],
            }
        player_aggro[player_name]["total_uptime_ms"] += uptime
        player_aggro[player_name]["targets"].extend(target_list)
    
    # Sort players by total aggro uptime
    players_sorted = sorted(
        player_aggro.values(),
        key=lambda x: x["total_uptime_ms"],
        reverse=True,
    )
    
    # Add percentage and formatted values
    for p in players_sorted:
        p["uptime_pct"] = round(p["total_uptime_ms"] / max(total_time, 1) * 100, 1)
        p["uptime_sec"] = round(p["total_uptime_ms"] / 1000, 1)
    
    return {
        "fight_name": fight.get("name", "Unknown"),
        "fight_id": fight_id,
        "duration_s": round(total_time_ms / 1000, 1),
        "total_time_ms": total_time,
        "players": players_sorted,
    }

