"""Guild-level data: attendance, gear audits, consumable tracking."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.wcl.client import graphql_query
from backend.wcl.queries import GUILD_ATTENDANCE, REPORT_EVENTS
from backend.analysis.report import fetch_report_metadata
from backend.analysis.utils import spell_name

# Enchantable gear slots (index in CombatantInfo gear array)
# 0=Head, 2=Shoulder, 4=Chest, 6=Legs, 7=Feet, 8=Wrist, 9=Hands,
# 14=Main Hand, 15=Off Hand, 16=Ranged
ENCHANTABLE_SLOTS = {
    0: "Head",
    2: "Shoulder",
    4: "Chest",
    6: "Legs",
    7: "Feet",
    8: "Wrist",
    9: "Hands",
    14: "Main Hand",
    15: "Off Hand",
}

# TBC consumable buff names (detected from pre-pull auras)
FLASK_BUFFS = {
    "Flask of Pure Death", "Flask of Blinding Light", "Flask of Supreme Power",
    "Flask of Relentless Assault", "Flask of Mighty Versatility",
    "Flask of Fortification", "Flask of the Titans",
    "Unstable Flask of the Bandit", "Unstable Flask of the Elder",
    "Unstable Flask of the Beast", "Unstable Flask of the Physician",
    "Unstable Flask of the Soldier", "Unstable Flask of the Sorcerer",
}

ELIXIR_BUFFS = {
    "Elixir of Major Agility", "Elixir of Major Firepower",
    "Elixir of Major Shadow Power", "Elixir of Healing Power",
    "Elixir of Draenic Wisdom", "Elixir of Major Mageblood",
    "Elixir of Major Strength", "Elixir of Mastery",
    "Elixir of Major Fortitude", "Elixir of Major Defense",
    "Elixir of Demonslaying", "Adept's Elixir", "Onslaught Elixir",
    "Mighty Agility",
}

FOOD_BUFFS = {"Well Fed"}

WEAPON_BUFFS = {
    "Brilliant Wizard Oil", "Superior Wizard Oil", "Blessed Wizard Oil",
    "Adamantite Weightstone", "Adamantite Sharpening Stone",
    "Superior Mana Oil", "Brilliant Mana Oil",
}


async def fetch_guild_reports(
    guild_id: int, limit: int = 25, page: int = 1
) -> dict[str, Any]:
    """Fetch guild attendance/report list."""
    data = await graphql_query(GUILD_ATTENDANCE, {
        "guildID": guild_id,
        "limit": limit,
        "page": page,
    })
    guild = data.get("guildData", {}).get("guild")
    if not guild:
        raise ValueError(f"Guild {guild_id} not found")

    attendance = guild.get("attendance", {})
    reports = []
    for entry in attendance.get("data", []):
        players = entry.get("players", [])
        reports.append({
            "code": entry["code"],
            "date": entry["startTime"],
            "zone": (entry.get("zone") or {}).get("name", "Unknown"),
            "player_count": len(players),
            "players": [
                {
                    "name": p["name"],
                    "class": p.get("type", "Unknown"),
                    "present": p.get("presence", 0) > 0,
                }
                for p in players
            ],
        })

    return {
        "guild": {
            "id": guild["id"],
            "name": guild["name"],
            "server": guild.get("server", {}).get("name", ""),
            "region": guild.get("server", {}).get("region", {}).get("compactName", ""),
        },
        "reports": reports,
        "total": attendance.get("total", 0),
        "has_more": attendance.get("has_more_pages", False),
        "page": attendance.get("current_page", page),
        "last_page": attendance.get("last_page", 1),
    }


async def compute_attendance(
    guild_id: int, max_pages: int = 4
) -> dict[str, Any]:
    """Compute aggregated attendance across recent raids."""
    all_reports: list[dict] = []
    page = 1

    while page <= max_pages:
        result = await fetch_guild_reports(guild_id, limit=25, page=page)
        all_reports.extend(result["reports"])
        if not result["has_more"]:
            break
        page += 1

    # Aggregate attendance per player
    player_attendance: dict[str, dict[str, Any]] = {}
    total_raids = len(all_reports)

    for report in all_reports:
        for player in report["players"]:
            name = player["name"]
            if name not in player_attendance:
                player_attendance[name] = {
                    "name": name,
                    "class": player["class"],
                    "raids_present": 0,
                    "raids_absent": 0,
                }
            if player["present"]:
                player_attendance[name]["raids_present"] += 1
            else:
                player_attendance[name]["raids_absent"] += 1

    # Calculate attendance rate and sort
    attendance_list = []
    for info in player_attendance.values():
        total_seen = info["raids_present"] + info["raids_absent"]
        info["attendance_pct"] = round(
            info["raids_present"] / total_seen * 100, 1
        ) if total_seen > 0 else 0
        info["total_raids_seen"] = total_seen
        attendance_list.append(info)

    attendance_list.sort(key=lambda x: (-x["attendance_pct"], -x["raids_present"]))

    return {
        "total_raids": total_raids,
        "players": attendance_list,
    }


async def fetch_gear_audit(report_code: str) -> dict[str, Any]:
    """Fetch gear, enchant, gem, and consumable data for all players in a report.

    Uses CombatantInfo from the first boss fight to get each player's loadout.
    """
    metadata = await fetch_report_metadata(report_code)
    fights = metadata.get("fights", [])
    actors = metadata.get("masterData", {}).get("actors", [])
    ability_names = {
        a["gameID"]: a["name"]
        for a in metadata.get("masterData", {}).get("abilities", [])
    }

    players_by_id = {a["id"]: a for a in actors if a.get("type") == "Player"}

    if not fights:
        return {"players": [], "report_code": report_code}

    # Use first fight for gear snapshot
    fight = fights[0]
    fight_id = fight["id"]
    start = fight["startTime"]
    end = fight["endTime"]

    combatant_events = await _fetch_combatant_info(report_code, fight_id, start, end)

    player_audits = []
    for ev in combatant_events:
        source_id = ev.get("sourceID")
        player = players_by_id.get(source_id)
        if not player:
            continue

        gear_items = ev.get("gear", [])
        auras = ev.get("auras", [])

        # Audit gear
        gear_audit = _audit_gear(gear_items)

        # Audit consumables from pre-pull auras
        consumable_audit = _audit_consumables(auras)

        player_audits.append({
            "name": player["name"],
            "class": player.get("subType", "Unknown"),
            "spec_id": ev.get("specID", 0),
            "avg_ilvl": gear_audit["avg_ilvl"],
            "missing_enchants": gear_audit["missing_enchants"],
            "missing_gems": gear_audit["missing_gems"],
            "enchant_count": gear_audit["enchant_count"],
            "gem_count": gear_audit["gem_count"],
            "total_enchantable": gear_audit["total_enchantable"],
            "total_gem_slots": gear_audit["total_gem_slots"],
            "consumables": consumable_audit,
            "gear": gear_audit["items"],
        })

    player_audits.sort(key=lambda x: x["name"])

    return {
        "report_code": report_code,
        "fight_name": fight.get("name", "Unknown"),
        "players": player_audits,
    }


async def _fetch_combatant_info(
    report_code: str, fight_id: int, start: int, end: int
) -> list[dict]:
    """Fetch CombatantInfo events for a fight."""
    from backend.analysis.report import fetch_events_paginated
    return await fetch_events_paginated(
        report_code, [fight_id], "CombatantInfo", start, end
    )


def _audit_gear(gear_items: list[dict]) -> dict[str, Any]:
    """Analyze gear for missing enchants and gems."""
    items = []
    total_ilvl = 0
    equipped_count = 0
    enchant_count = 0
    total_enchantable = 0
    gem_count = 0
    total_gem_slots = 0
    missing_enchants = []
    missing_gems = []

    for slot_idx, item in enumerate(gear_items):
        item_id = item.get("id", 0)
        if item_id == 0:
            continue

        ilvl = item.get("itemLevel", 0)
        total_ilvl += ilvl
        equipped_count += 1

        enchant_id = item.get("permanentEnchant", 0)
        gems = item.get("gems", [])

        slot_name = ENCHANTABLE_SLOTS.get(slot_idx)

        item_info = {
            "slot": slot_idx,
            "slot_name": slot_name or f"Slot {slot_idx}",
            "item_id": item_id,
            "item_level": ilvl,
            "enchant_id": enchant_id,
            "gem_count": len(gems),
        }
        items.append(item_info)

        # Check enchants on enchantable slots
        if slot_name:
            total_enchantable += 1
            if enchant_id > 0:
                enchant_count += 1
            else:
                missing_enchants.append(slot_name)

        # Count gems (any socket that has gems)
        if gems:
            gem_count += len(gems)
            total_gem_slots += len(gems)

    avg_ilvl = round(total_ilvl / equipped_count) if equipped_count > 0 else 0

    return {
        "avg_ilvl": avg_ilvl,
        "enchant_count": enchant_count,
        "total_enchantable": total_enchantable,
        "missing_enchants": missing_enchants,
        "gem_count": gem_count,
        "total_gem_slots": total_gem_slots,
        "missing_gems": missing_gems,
        "items": items,
    }


def _audit_consumables(auras: list[dict]) -> dict[str, Any]:
    """Check pre-pull auras for consumable usage."""
    has_flask = False
    has_elixir = False
    has_food = False
    has_weapon_buff = False
    flask_name = ""
    elixir_names: list[str] = []
    food_name = ""
    weapon_buff_name = ""

    for aura in auras:
        name = aura.get("name", "")
        if name in FLASK_BUFFS:
            has_flask = True
            flask_name = name
        elif name in ELIXIR_BUFFS:
            has_elixir = True
            elixir_names.append(name)
        if name in FOOD_BUFFS:
            has_food = True
            food_name = name
        if name in WEAPON_BUFFS:
            has_weapon_buff = True
            weapon_buff_name = name

    return {
        "flask": flask_name if has_flask else None,
        "elixirs": elixir_names if has_elixir else [],
        "food": has_food,
        "weapon_buff": weapon_buff_name if has_weapon_buff else None,
        "fully_consumed": (has_flask or has_elixir) and has_food,
    }
