"""Guild-level data: attendance, gear audits, consumable tracking."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.wcl.client import graphql_query
from backend.wcl.queries import GUILD_ATTENDANCE, REPORT_EVENTS, REPORT_FIGHTS
from backend.analysis.report import fetch_report_metadata
from backend.analysis.utils import spell_name

# TBC encounter IDs by instance
SSC_ENCOUNTER_IDS = {623, 624, 625, 626, 627, 628}  # Hydross, Lurker, Leo, Karathress, Morogrim, Vashj
TK_ENCOUNTER_IDS = {730, 731, 732, 733}  # Al'ar, VR, Solarian, Kael'thas
# Boss name substrings for fallback detection
SSC_BOSS_NAMES = {"Hydross", "Lurker", "Leotheras", "Karathress", "Morogrim", "Vashj"}
TK_BOSS_NAMES = {"Al'ar", "Void Reaver", "Solarian", "Kael'thas"}

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
    """Fetch guild attendance/report list with resolved zone names."""
    data = await graphql_query(GUILD_ATTENDANCE, {
        "guildID": guild_id,
        "limit": limit,
        "page": page,
    })
    guild = data.get("guildData", {}).get("guild")
    if not guild:
        raise ValueError(f"Guild {guild_id} not found")

    attendance = guild.get("attendance", {})
    raw_reports = attendance.get("data", [])

    # Resolve actual instances for each report in parallel
    codes = [entry["code"] for entry in raw_reports]
    instance_tasks = [_fetch_report_instances(code) for code in codes]
    instance_results = await asyncio.gather(*instance_tasks, return_exceptions=True)

    reports = []
    for entry, instances in zip(raw_reports, instance_results):
        players = entry.get("players", [])
        # Determine zone from actual encounters
        if isinstance(instances, Exception) or not instances:
            zone = (entry.get("zone") or {}).get("name", "Unknown")
        else:
            zone = " / ".join(sorted(instances))

        reports.append({
            "code": entry["code"],
            "date": entry["startTime"],
            "zone": zone,
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


def _lockout_week(timestamp_ms: int) -> str:
    """Return the Tuesday-reset lockout week label for a timestamp.

    WoW TBC resets on Tuesday ~11am ET. We use Tuesday 15:00 UTC as the
    boundary. A raid on Monday night belongs to the *previous* week's lockout.
    """
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    # Find most recent Tuesday 15:00 UTC at or before this timestamp
    days_since_tuesday = (dt.weekday() - 1) % 7
    tuesday = dt - timedelta(days=days_since_tuesday)
    tuesday = tuesday.replace(hour=15, minute=0, second=0, microsecond=0)
    if dt < tuesday:
        tuesday -= timedelta(days=7)
    return tuesday.strftime("%Y-%m-%d")


def _detect_instance(fights: list[dict]) -> set[str]:
    """Determine which raid instances (SSC / TK) a report covers."""
    instances: set[str] = set()
    for f in fights:
        eid = f.get("encounterID", 0)
        name = f.get("name", "")
        if eid in SSC_ENCOUNTER_IDS or any(b in name for b in SSC_BOSS_NAMES):
            instances.add("SSC")
        if eid in TK_ENCOUNTER_IDS or any(b in name for b in TK_BOSS_NAMES):
            instances.add("TK")
    return instances


async def _fetch_report_instances(report_code: str) -> set[str]:
    """Fetch fights for a report and determine which instances were run."""
    data = await graphql_query(REPORT_FIGHTS, {"code": report_code})
    report = data.get("reportData", {}).get("report", {})
    fights = report.get("fights", [])
    return _detect_instance(fights)


async def compute_attendance(
    guild_id: int, max_pages: int = 4
) -> dict[str, Any]:
    """Compute attendance per lockout week per instance (SSC / TK).

    Returns weekly attendance showing whether each character attended
    SSC and/or TK during each Tuesday-to-Tuesday lockout period.
    """
    # 1. Gather all reports from guild attendance
    all_reports: list[dict] = []
    page = 1
    while page <= max_pages:
        result = await fetch_guild_reports(guild_id, limit=25, page=page)
        all_reports.extend(result["reports"])
        if not result["has_more"]:
            break
        page += 1

    # 2. Determine which instance each report covers (parallel)
    instance_tasks = [_fetch_report_instances(r["code"]) for r in all_reports]
    instance_results = await asyncio.gather(*instance_tasks, return_exceptions=True)

    # 3. Build weekly attendance: week -> instance -> set of player names
    weeks: dict[str, dict[str, set[str]]] = {}
    player_info: dict[str, str] = {}  # name -> class

    for report, instances in zip(all_reports, instance_results):
        if isinstance(instances, Exception):
            continue
        # Skip non-SSC/TK raids (Gruul/Mag, Kara, etc.)
        if not instances:
            continue

        week = _lockout_week(report["date"])
        if week not in weeks:
            weeks[week] = {"SSC": set(), "TK": set()}

        present_players = [p["name"] for p in report["players"] if p["present"]]
        for inst in instances:
            if inst in weeks[week]:
                weeks[week][inst].update(present_players)

        for p in report["players"]:
            if p["name"] not in player_info:
                player_info[p["name"]] = p["class"]

    # 4. Sort weeks newest first
    sorted_weeks = sorted(weeks.keys(), reverse=True)

    # 5. Build per-player summary
    player_summary: dict[str, dict[str, Any]] = {}
    for week in sorted_weeks:
        for inst in ("SSC", "TK"):
            for name in weeks[week].get(inst, set()):
                if name not in player_summary:
                    player_summary[name] = {
                        "name": name,
                        "class": player_info.get(name, "Unknown"),
                        "ssc_weeks": 0,
                        "tk_weeks": 0,
                        "total_weeks": 0,
                        "weekly": {},
                    }
                if week not in player_summary[name]["weekly"]:
                    player_summary[name]["weekly"][week] = {"SSC": False, "TK": False}

        # Mark attendance
        for name in weeks[week].get("SSC", set()):
            player_summary[name]["weekly"][week]["SSC"] = True
            player_summary[name]["ssc_weeks"] += 1
        for name in weeks[week].get("TK", set()):
            player_summary[name]["weekly"][week]["TK"] = True
            player_summary[name]["tk_weeks"] += 1

    # Count total weeks each player appeared in
    for info in player_summary.values():
        info["total_weeks"] = len(info["weekly"])
        pct_weeks = len(sorted_weeks) if sorted_weeks else 1
        info["attendance_pct"] = round(
            (info["ssc_weeks"] + info["tk_weeks"]) / (pct_weeks * 2) * 100, 1
        )

    players = sorted(
        player_summary.values(),
        key=lambda x: (-x["attendance_pct"], -x["total_weeks"], x["name"]),
    )

    return {
        "weeks": sorted_weeks,
        "total_weeks": len(sorted_weeks),
        "players": players,
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
