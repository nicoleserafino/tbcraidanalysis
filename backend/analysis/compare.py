"""Compare-report data fetching using WCL v2 API."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.analysis.utils import infer_role, spell_name
from backend.analysis.report import fetch_events_paginated, fetch_table
from backend.wcl.client import graphql_query
from backend.wcl.queries import REPORT_FIGHTS_ALL

PLAYER_CLASSES = {
    "Warrior", "Paladin", "Hunter", "Rogue", "Priest",
    "Shaman", "Mage", "Warlock", "Druid",
}

CONSUMABLE_BUFFS = {
    "Flask of Pure Death", "Flask of Blinding Light", "Flask of Supreme Power", "Flask of Relentless Assault",
    "Flask of Mighty Versatility", "Flask of Fortification", "Flask of the Titans",
    "Unstable Flask of the Bandit", "Unstable Flask of the Elder", "Unstable Flask of the Beast",
    "Unstable Flask of the Physician", "Unstable Flask of the Soldier", "Unstable Flask of the Sorcerer",
    "Well Fed", "Brilliant Wizard Oil", "Superior Wizard Oil", "Adamantite Weightstone", "Adamantite Sharpening Stone",
    "Elixir of Major Agility", "Elixir of Major Firepower", "Elixir of Major Shadow Power",
    "Elixir of Healing Power", "Elixir of Draenic Wisdom", "Elixir of Major Mageblood",
    "Elixir of Major Strength", "Elixir of Mastery", "Elixir of Major Fortitude", "Elixir of Major Defense",
    "Haste Potion", "Destruction Potion", "Super Mana Potion", "Ironshield Potion", "Free Action Potion",
}
RAID_BUFFS = {
    "Arcane Brilliance", "Mark of the Wild", "Gift of the Wild",
    "Power Word: Fortitude", "Prayer of Fortitude", "Shadow Protection", "Prayer of Shadow Protection",
    "Divine Spirit", "Prayer of Spirit", "Blessing of Kings", "Greater Blessing of Kings",
    "Blessing of Might", "Greater Blessing of Might", "Blessing of Wisdom", "Greater Blessing of Wisdom",
    "Blessing of Salvation", "Greater Blessing of Salvation", "Blessing of Light", "Greater Blessing of Light",
    "Windfury Totem", "Grace of Air Totem", "Strength of Earth Totem", "Mana Spring Totem",
    "Wrath of Air Totem", "Totem of Wrath", "Moonkin Aura", "Leader of the Pack",
    "Trueshot Aura", "Ferocious Inspiration", "Unleashed Rage", "Vampiric Embrace",
}


def fmt_duration(ms: int) -> str:
    """Format milliseconds as M:SS or H:MM:SS."""
    total_sec = abs(ms) / 1000
    if total_sec >= 3600:
        hours = int(total_sec // 3600)
        minutes = int((total_sec % 3600) // 60)
        seconds = int(total_sec % 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    minutes = int(total_sec // 60)
    seconds = int(total_sec % 60)
    return f"{minutes}:{seconds:02d}"


def ability_id(payload: dict[str, Any]) -> int:
    """Resolve an ability/game id from a v2 table row or event."""
    ability = payload.get("ability")
    if isinstance(ability, dict):
        for key in ("guid", "gameID", "id"):
            if isinstance(ability.get(key), int):
                return ability[key]
    for key in ("abilityGameID", "gameID", "guid", "id"):
        if isinstance(payload.get(key), int):
            return int(payload[key])
    return 0


def iter_table_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten table rows for player detail endpoints."""
    rows: list[dict[str, Any]] = []
    for entry in table.get("entries", []) or []:
        abilities = entry.get("abilities")
        if isinstance(abilities, list) and abilities:
            rows.extend(abilities)
        else:
            rows.append(entry)
    return rows


def normalize_damage_rows(table: dict[str, Any], ability_names: dict[int, str]) -> list[dict[str, Any]]:
    rows = []
    for entry in iter_table_rows(table):
        rows.append({
            "name": spell_name(entry, ability_names),
            "total": int(entry.get("total", 0) or 0),
            "hitCount": int(entry.get("hitCount", 0) or 0),
            "critHitCount": int(entry.get("critHitCount", 0) or 0),
            "missCount": int(entry.get("missCount", 0) or 0),
            "tickCount": int(entry.get("tickCount", 0) or 0),
            "critTickCount": int(entry.get("critTickCount", 0) or 0),
        })
    rows.sort(key=lambda row: row["total"], reverse=True)
    return rows


def normalize_healing_rows(table: dict[str, Any], ability_names: dict[int, str]) -> list[dict[str, Any]]:
    rows = []
    for entry in iter_table_rows(table):
        rows.append({
            "name": spell_name(entry, ability_names),
            "total": int(entry.get("total", 0) or 0),
            "overheal": int(entry.get("overheal", 0) or 0),
            "hitCount": int(entry.get("hitCount", 0) or 0),
            "critHitCount": int(entry.get("critHitCount", 0) or 0),
            "tickCount": int(entry.get("tickCount", 0) or 0),
            "critTickCount": int(entry.get("critTickCount", 0) or 0),
        })
    rows.sort(key=lambda row: row["total"], reverse=True)
    return rows


def normalize_buff_rows(table: dict[str, Any], ability_names: dict[int, str], fight_duration_ms: int) -> list[dict[str, Any]]:
    rows = []
    for entry in table.get("auras", []) or []:
        uptime_ms = int(entry.get("totalUptime", 0) or 0)
        name = spell_name(entry, ability_names)
        rows.append({
            "name": name,
            "uptime_ms": uptime_ms,
            "uptime_pct": round(uptime_ms / fight_duration_ms * 100, 1) if fight_duration_ms > 0 else 0,
            "isConsumable": name in CONSUMABLE_BUFFS,
            "isRaidBuff": name in RAID_BUFFS,
        })
    rows.sort(key=lambda row: row["uptime_pct"], reverse=True)
    return rows


def normalize_cast_rows(table: dict[str, Any], ability_names: dict[int, str]) -> list[dict[str, Any]]:
    rows = []
    for entry in iter_table_rows(table):
        rows.append({
            "name": spell_name(entry, ability_names),
            "total": int(entry.get("total", 0) or 0),
            "hitCount": int(entry.get("hitCount", 0) or 0),
        })
    rows.sort(key=lambda row: row["total"], reverse=True)
    return rows


def normalize_cast_events(events: list[dict[str, Any]], ability_names: dict[int, str], start_time: int) -> list[dict[str, Any]]:
    rows = []
    for event in events:
        if event.get("type") != "cast":
            continue
        timestamp = int(event.get("timestamp", 0) or 0)
        rows.append({
            "ability": spell_name(event, ability_names),
            "abilityId": ability_id(event),
            "timestamp": timestamp,
            "time_into_fight_sec": round((timestamp - start_time) / 1000, 1),
        })
    rows.sort(key=lambda row: row["timestamp"])
    return rows


async def fetch_compare_metadata(report_code: str) -> dict[str, Any]:
    data = await graphql_query(REPORT_FIGHTS_ALL, {"code": report_code})
    return data["reportData"]["report"]


async def fetch_cooldown_events(report_code: str, fight_id: int, start_time: int, end_time: int, spell: str) -> list[dict[str, Any]]:
    try:
        return await fetch_events_paginated(
            report_code,
            [fight_id],
            "Casts",
            start_time,
            end_time,
            filter_expression=f'ability.name="{spell}"',
        )
    except RuntimeError:
        return []


async def fetch_compare_report(report_code: str) -> tuple[dict[str, Any], dict[int, str]]:
    """Fetch all data needed by frontend/compare.html."""
    metadata = await fetch_compare_metadata(report_code)
    fights = metadata.get("fights", []) or []
    actors = metadata.get("masterData", {}).get("actors", []) or []
    abilities = metadata.get("masterData", {}).get("abilities", []) or []
    ability_names = {ability["gameID"]: ability["name"] for ability in abilities if ability.get("gameID")}

    players = [
        actor for actor in actors
        if actor.get("type") == "Player" and actor.get("subType") in PLAYER_CLASSES
    ]
    players_by_id = {int(player["id"]): player for player in players if player.get("id") is not None}

    boss_fights = [fight for fight in fights if int(fight.get("encounterID", 0) or 0) > 0]
    trash_fights = [fight for fight in fights if int(fight.get("encounterID", 0) or 0) == 0 and fight.get("name") != "Unknown"]

    fastest_kills: dict[str, dict[str, Any]] = {}
    for fight in boss_fights:
        if not fight.get("kill"):
            continue
        duration_ms = int((fight.get("endTime", 0) or 0) - (fight.get("startTime", 0) or 0))
        existing = fastest_kills.get(fight["name"])
        if existing is None or duration_ms < existing["duration_ms"]:
            fastest_kills[fight["name"]] = {"fight": fight, "duration_ms": duration_ms}

    aggregate_damage: dict[int, int] = {}
    aggregate_healing: dict[int, int] = {}
    aggregate_damage_taken: dict[int, int] = {}
    bosses: list[dict[str, Any]] = []

    for boss_name, entry in sorted(fastest_kills.items(), key=lambda item: item[1]["fight"]["startTime"]):
        fight = entry["fight"]
        fight_id = int(fight["id"])
        start_time = int(fight["startTime"])
        end_time = int(fight["endTime"])
        duration_ms = end_time - start_time

        dmg_table, heal_table, buff_table, damage_taken_table, bloodlust_events, heroism_events = await asyncio.gather(
            fetch_table(report_code, [fight_id], "DamageDone", start_time, end_time),
            fetch_table(report_code, [fight_id], "Healing", start_time, end_time),
            fetch_table(report_code, [fight_id], "Buffs", start_time, end_time),
            fetch_table(report_code, [fight_id], "DamageTaken", start_time, end_time),
            fetch_cooldown_events(report_code, fight_id, start_time, end_time, "Bloodlust"),
            fetch_cooldown_events(report_code, fight_id, start_time, end_time, "Heroism"),
        )

        total_damage = 0
        player_damage: dict[str, int] = {}
        for row in dmg_table.get("entries", []) or []:
            player_id = row.get("id")
            if player_id not in players_by_id:
                continue
            damage = int(row.get("total", 0) or 0)
            player_name = players_by_id[player_id]["name"]
            player_damage[player_name] = damage
            total_damage += damage
            aggregate_damage[player_id] = aggregate_damage.get(player_id, 0) + damage

        total_healing = 0
        total_overheal = 0
        player_healing: dict[str, dict[str, int]] = {}
        for row in heal_table.get("entries", []) or []:
            player_id = row.get("id")
            if player_id not in players_by_id:
                continue
            healing = int(row.get("total", 0) or 0)
            overheal = int(row.get("overheal", 0) or 0)
            player_name = players_by_id[player_id]["name"]
            player_healing[player_name] = {"healing": healing, "overheal": overheal}
            total_healing += healing
            total_overheal += overheal
            aggregate_healing[player_id] = aggregate_healing.get(player_id, 0) + healing

        for row in damage_taken_table.get("entries", []) or []:
            player_id = row.get("id")
            if player_id not in players_by_id:
                continue
            taken = int(row.get("total", 0) or 0)
            aggregate_damage_taken[player_id] = aggregate_damage_taken.get(player_id, 0) + taken

        buffs_present = sorted({
            spell_name(aura, ability_names)
            for aura in (buff_table.get("auras", []) or [])
            if spell_name(aura, ability_names) in CONSUMABLE_BUFFS or spell_name(aura, ability_names) in RAID_BUFFS
        })

        cooldowns = []
        for spell, events in (("Bloodlust", bloodlust_events), ("Heroism", heroism_events)):
            for event in events:
                if event.get("type") != "cast":
                    continue
                timestamp = int(event.get("timestamp", 0) or 0)
                cooldowns.append({
                    "spell": spell,
                    "time_sec": round((timestamp - start_time) / 1000, 1),
                    "time_pct": round((timestamp - start_time) / duration_ms * 100, 1) if duration_ms > 0 else 0,
                })
        cooldowns.sort(key=lambda row: row["time_sec"])

        duration_sec = duration_ms / 1000
        bosses.append({
            "name": boss_name,
            "fight_id": fight_id,
            "duration_ms": duration_ms,
            "duration_str": fmt_duration(duration_ms),
            "start_time": start_time,
            "end_time": end_time,
            "total_damage": total_damage,
            "raid_dps": round(total_damage / duration_sec) if duration_sec > 0 else 0,
            "total_healing": total_healing,
            "total_overheal": total_overheal,
            "overheal_pct": round(total_overheal / (total_healing + total_overheal) * 100, 1) if (total_healing + total_overheal) > 0 else 0,
            "raid_hps": round(total_healing / duration_sec) if duration_sec > 0 else 0,
            "player_damage": dict(sorted(player_damage.items(), key=lambda item: item[1], reverse=True)),
            "player_healing": dict(sorted(player_healing.items(), key=lambda item: item[1]["healing"], reverse=True)),
            "buffs_present": buffs_present,
            "cooldowns": cooldowns,
        })

    roster = {}
    for player in sorted(players, key=lambda item: item["name"]):
        player_id = int(player["id"])
        player_class = player.get("subType", "Unknown")
        roster[player["name"]] = {
            "class": player_class,
            "role": infer_role(
                player_class,
                total_healing=aggregate_healing.get(player_id, 0),
                total_damage_done=aggregate_damage.get(player_id, 0),
                total_damage_taken=aggregate_damage_taken.get(player_id, 0),
            ),
            "icon": "",
            "id": player_id,
        }

    boss_pull_counts: dict[str, dict[str, int]] = {}
    for fight in boss_fights:
        boss_name = fight["name"]
        boss_pull_counts.setdefault(boss_name, {"total_pulls": 0, "kills": 0, "wipes": 0})
        boss_pull_counts[boss_name]["total_pulls"] += 1
        if fight.get("kill"):
            boss_pull_counts[boss_name]["kills"] += 1
        else:
            boss_pull_counts[boss_name]["wipes"] += 1

    trash = {"logged": False, "total_time_ms": 0, "pull_count": 0}
    if trash_fights:
        total_trash_ms = sum(int((fight.get("endTime", 0) or 0) - (fight.get("startTime", 0) or 0)) for fight in trash_fights)
        trash = {
            "logged": True,
            "total_time_ms": total_trash_ms,
            "total_time_str": fmt_duration(total_trash_ms),
            "pull_count": len(trash_fights),
        }

    pacing = []
    for index, boss in enumerate(bosses):
        entry: dict[str, Any] = {
            "boss": boss["name"],
            "kill_time_ms": boss["end_time"],
            "fight_duration_ms": boss["duration_ms"],
        }
        if index > 0:
            gap_ms = boss["start_time"] - bosses[index - 1]["end_time"]
            entry["gap_from_prev_ms"] = gap_ms
            entry["gap_from_prev_str"] = fmt_duration(max(0, gap_ms))
        pacing.append(entry)

    if bosses:
        first_event_ms = min(int(fight.get("startTime", 0) or 0) for fight in fights) if fights else bosses[0]["start_time"]
        last_kill_ms = bosses[-1]["end_time"]
        total_raid_ms = last_kill_ms - first_event_ms
    else:
        total_raid_ms = int((metadata.get("endTime", 0) or 0) - (metadata.get("startTime", 0) or 0))
    total_gap_ms = sum(max(0, int(entry.get("gap_from_prev_ms", 0) or 0)) for entry in pacing)

    return {
        "report_id": report_code,
        "url": f"https://fresh.warcraftlogs.com/reports/{report_code}",
        "title": metadata.get("title", report_code),
        "owner": (metadata.get("owner") or {}).get("name", ""),
        "report_start_ms": int(metadata.get("startTime", 0) or 0),
        "total_raid_ms": total_raid_ms,
        "total_raid_str": fmt_duration(total_raid_ms),
        "total_gap_ms": total_gap_ms,
        "total_gap_str": fmt_duration(total_gap_ms),
        "roster": roster,
        "bosses": bosses,
        "boss_order": [boss["name"] for boss in bosses],
        "boss_pull_counts": boss_pull_counts,
        "trash": trash,
        "pacing": pacing,
    }, ability_names


async def fetch_player_details(
    report_code: str,
    fight_id: int,
    player_id: int,
    ability_names: dict[int, str],
    start_time: int,
    end_time: int,
) -> dict[str, Any]:
    """Fetch detailed per-player tables for a single boss kill."""
    damage_table, healing_table, buff_table, cast_table, cast_events = await asyncio.gather(
        fetch_table(report_code, [fight_id], "DamageDone", start_time, end_time, source_id=player_id),
        fetch_table(report_code, [fight_id], "Healing", start_time, end_time, source_id=player_id),
        fetch_table(report_code, [fight_id], "Buffs", start_time, end_time, target_id=player_id),
        fetch_table(report_code, [fight_id], "Casts", start_time, end_time, source_id=player_id),
        fetch_events_paginated(report_code, [fight_id], "Casts", start_time, end_time, source_id=player_id),
    )

    return {
        "damage": normalize_damage_rows(damage_table, ability_names),
        "healing": normalize_healing_rows(healing_table, ability_names),
        "buffs": normalize_buff_rows(buff_table, ability_names, end_time - start_time),
        "casts": normalize_cast_rows(cast_table, ability_names),
        "cast_events": normalize_cast_events(cast_events, ability_names, start_time),
    }
