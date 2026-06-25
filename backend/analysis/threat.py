"""Threat data fetching for raid analysis."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.analysis.report import fetch_report_metadata, fetch_table


async def fetch_threat_data(report_code: str, fight_id: int) -> dict[str, Any]:
    """Fetch threat rankings for top 5 DPS on a specific fight.
    
    Returns threat totals and per-ability breakdown for the highest-threat players.
    """
    metadata = await fetch_report_metadata(report_code)
    fights = metadata.get("fights", [])
    actors = metadata.get("masterData", {}).get("actors", [])
    
    players_by_id = {a["id"]: a for a in actors if a.get("type") == "Player"}
    
    fight = next((f for f in fights if f["id"] == fight_id), None)
    if not fight:
        return {"error": "Fight not found", "players": []}
    
    start = fight["startTime"]
    end = fight["endTime"]
    
    # First get DamageDone table to identify top DPS players
    damage_table = await fetch_table(
        report_code, [fight_id], "DamageDone", start, end
    )
    
    entries = damage_table.get("entries", [])
    # Filter to players only and sort by total damage
    player_damage = []
    for entry in entries:
        actor_id = entry.get("id")
        if actor_id in players_by_id:
            player_damage.append({
                "id": actor_id,
                "name": players_by_id[actor_id]["name"],
                "class": players_by_id[actor_id].get("subType", "Unknown"),
                "total_damage": entry.get("total", 0),
            })
    
    player_damage.sort(key=lambda x: x["total_damage"], reverse=True)
    top_players = player_damage[:5]
    
    # Fetch threat table for each top player in parallel
    async def get_player_threat(player: dict) -> dict:
        try:
            threat_data = await fetch_table(
                report_code, [fight_id], "Threat", start, end,
                source_id=player["id"]
            )
            threat_entries = threat_data.get("entries", [])
            total_threat = sum(e.get("total", 0) for e in threat_entries)
            
            # Get per-ability threat breakdown
            abilities = []
            for e in sorted(threat_entries, key=lambda x: x.get("total", 0), reverse=True)[:10]:
                abilities.append({
                    "name": e.get("name", "Unknown"),
                    "total": e.get("total", 0),
                    "hitCount": e.get("hitCount", 0),
                })
            
            return {
                "name": player["name"],
                "class": player["class"],
                "total_threat": total_threat,
                "total_damage": player["total_damage"],
                "tps": round(total_threat / max((end - start) / 1000, 1), 1),
                "abilities": abilities,
            }
        except Exception:
            return {
                "name": player["name"],
                "class": player["class"],
                "total_threat": 0,
                "total_damage": player["total_damage"],
                "tps": 0,
                "abilities": [],
                "error": "Failed to fetch threat data",
            }
    
    threat_results = await asyncio.gather(*[get_player_threat(p) for p in top_players])
    
    # Sort by total threat descending
    threat_results.sort(key=lambda x: x["total_threat"], reverse=True)
    
    return {
        "fight_name": fight.get("name", "Unknown"),
        "fight_id": fight_id,
        "duration_s": round((end - start) / 1000, 1),
        "players": threat_results,
    }
