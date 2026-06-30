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
    14: "Back",
    15: "Main Hand",
    16: "Off Hand",
}

# Cheap/suboptimal enchant IDs by slot — flagged as warnings, not missing
# Source: CLA spreadsheet gear issues config
CHEAP_ENCHANTS = {
    # Wrist (slot 8) — low stat enchants
    8: {927, 856, 823, 248, 929, 852, 724, 66, 41, 907, 851, 255, 905, 723, 923, 925, 924,
        1886, 1885},
    # Hands (slot 9) — cheap/irrelevant glove enchants
    9: {1887, 904, 856, 909, 845, 906, 844, 865, 846, 927, 2934},
    # Feet (slot 7) — low-tier boot enchants
    7: {255, 904, 849, 247, 852, 724, 66, 929, 1887},
    # Chest (slot 4) — cheap chest enchants
    4: {908, 850, 254, 242, 41, 913, 857, 843, 246, 24, 928, 866, 847, 63, 44, 1891, 1893},
    # Back (slot 14) — cheap cloak enchants
    14: {910, 903, 65, 2463, 256, 1889, 884, 848, 744, 783, 247, 2938},
    # Shoulder (slot 2) — handled separately via CHEAP_SHOULDER_ENCHANTS
    # Legs (slot 6) — Silver/Mystic Thread instead of proper leg armor
    6: {2745, 2747},
    # Main Hand (slot 15) — cheap weapon enchants
    15: {1903, 255, 1904, 723, 1896, 963, 943, 241, 2443, 1899, 1898, 803, 854, 805, 2646,
         2568},
}

# Shoulder enchants that are Honored-tier (suboptimal vs Exalted)
# Shoulder enchant IDs — Honored tier (confirmed on Dreamscythe fresh):
# 2979 = Inscription of Faith (Aldor Honored, healing)
# 2981 = Inscription of Discipline (Aldor Honored, caster)
# 2978 = Inscription (Scryer Honored)
# Exalted versions (NOT flagged): 2980, 2983, 2986, 2993, 2994, 2995, 2996, 2997
CHEAP_SHOULDER_ENCHANTS = {
    2978: "Scryer Honored — upgrade to Exalted",
    2979: "Aldor Honored (Faith) — upgrade to Exalted",
    2981: "Aldor Honored (Discipline) — upgrade to Exalted",
}

# Cheap enchant names for display
CHEAP_ENCHANT_NAMES = {
    2745: "Silver Thread (Legs)", 2747: "Mystic Thread (Legs)",
    2938: "Spell Penetration (Cloak)", 803: "Fiery Weapon",
    1898: "Lifestealing", 1899: "Unholy Weapon", 854: "Elemental Weapon",
    2646: "25 Agility (Weapon)", 2568: "22 Intellect (Weapon)",
    2606: "ZG Shoulder", 2934: "Blasting (Gloves)",
    2463: "7 Fire Resistance (Cloak)", 256: "5 Fire Resistance (Cloak)",
    904: "Minor Stamina", 1886: "Minor Intellect",
}

# TBC uncommon (green) gem IDs — only these should be flagged as low-quality
# The WCL itemLevel field is unreliable (some rare gems report ilvl 60)
UNCOMMON_GEM_IDS = {
    # Blood Garnet (red)
    23095, 28595, 23114, 23116,
    # Golden Draenite (yellow)
    23112, 23113, 23118, 23120, 28290,
    # Azure Moonstone (blue)
    23117, 23119, 23121,
    # Flame Spessarite (orange)
    21929, 23098, 23099, 23100, 23101, 31866,
    # Deep Peridot (green)
    23079, 23094, 23096, 23097, 23103, 23104, 23105, 23106,
    # Shadow Draenite (purple)
    23107, 23108, 23109, 23110, 23111,
}


# TBC consumable buff names (detected from pre-pull auras)
FLASK_BUFFS = {
    "Flask of Pure Death", "Flask of Blinding Light", "Flask of Supreme Power",
    "Flask of Relentless Assault", "Flask of Mighty Versatility",
    "Flask of Fortification", "Flask of the Titans",
    "Supreme Power", "Greater Versatility",  # alternate buff names
    "Unstable Flask of the Bandit", "Unstable Flask of the Elder",
    "Unstable Flask of the Beast", "Unstable Flask of the Physician",
    "Unstable Flask of the Soldier", "Unstable Flask of the Sorcerer",
}

BATTLE_ELIXIRS = {
    "Elixir of Major Agility", "Elixir of Major Firepower", "Major Firepower",
    "Elixir of Major Shadow Power", "Major Shadow Power",
    "Elixir of Healing Power", "Healing Power",
    "Elixir of Major Mageblood",
    "Elixir of Major Strength",
    "Elixir of Mastery",
    "Elixir of Demonslaying",
    "Adept's Elixir", "Onslaught Elixir",
    "Mighty Agility",
    "Fel Strength Elixir", "Fel Strength",
    "Elixir of Major Frost Power",
    "Elixir of the Mongoose",
    "Spellpower Elixir",
}

GUARDIAN_ELIXIRS = {
    "Elixir of Major Fortitude", "Elixir of Major Defense",
    "Elixir of Ironshield", "Earthen Elixir",
    "Elixir of Draenic Wisdom",
}

ELIXIR_BUFFS = BATTLE_ELIXIRS | GUARDIAN_ELIXIRS

FOOD_BUFFS = {"Well Fed"}

WEAPON_BUFFS = {
    "Brilliant Wizard Oil", "Superior Wizard Oil", "Blessed Wizard Oil",
    "Adamantite Weightstone", "Adamantite Sharpening Stone",
    "Superior Mana Oil", "Brilliant Mana Oil",
}

# Known TBC temporary weapon enchant IDs (verified via player class correlation)
TEMP_ENCHANT_NAMES = {
    # Caster DPS oils
    2628: "Superior Wizard Oil",       # Mage, Warlock, Druid casters
    2678: "Brilliant Wizard Oil",      # Mage, Warlock, Paladin, Priest casters
    # Healer oils
    2629: "Brilliant Mana Oil",        # Druid, Priest, Paladin healers
    2677: "Superior Mana Oil",
    # Shaman imbues
    2636: "Windfury Weapon",
    2641: "Flametongue Weapon",
    # Physical DPS - stones/weightstones
    2713: "Adamantite Sharpening Stone",  # Warrior, Rogue, Hunter (sharp weapons)
    2955: "Adamantite Weightstone",       # Hunter, others (blunt weapons)
    3225: "Adamantite Sharpening Stone",
    3226: "Adamantite Weightstone",
    2679: "Elemental Sharpening Stone",
    # Rogue poisons (also stored as temporaryEnchant)
    2643: "Instant Poison VII",
    2644: "Deadly Poison VII",
    # Other
    2630: "Righteous Weapon Coating",
    2684: "Blessed Wizard Oil",
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

    # Use zone name from attendance data directly (avoids 50+ extra API calls)
    # Only resolve instances if zone name is missing or "Unknown"
    reports_needing_instances = []
    report_indices = []
    for i, entry in enumerate(raw_reports):
        zone_name = (entry.get("zone") or {}).get("name", "")
        if not zone_name or zone_name == "Unknown":
            reports_needing_instances.append(entry["code"])
            report_indices.append(i)

    # Only fetch instances for reports with missing zone data
    instance_map = {}
    if reports_needing_instances:
        instance_tasks = [_fetch_report_instances(code) for code in reports_needing_instances]
        instance_results = await asyncio.gather(*instance_tasks, return_exceptions=True)
        for idx, instances in zip(report_indices, instance_results):
            if not isinstance(instances, Exception) and instances:
                instance_map[idx] = " / ".join(sorted(instances))

    reports = []
    for i, entry in enumerate(raw_reports):
        players = entry.get("players", [])
        zone = instance_map.get(i) or (entry.get("zone") or {}).get("name", "Unknown")

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
    data = await graphql_query(REPORT_FIGHTS, {"code": report_code, "killType": "Encounters"})
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

    Tracks consumable usage per-fight for uptime percentages, and uses gear
    from first appearance (doesn't change mid-raid).
    """
    metadata = await fetch_report_metadata(report_code)
    fights = metadata.get("fights", [])
    actors = metadata.get("masterData", {}).get("actors", [])

    players_by_id = {a["id"]: a for a in actors if a.get("type") == "Player"}

    # Only check boss fights (have encounterID)
    boss_fights = [f for f in fights if f.get("encounterID")]
    if not boss_fights:
        return {"players": [], "report_code": report_code, "fights": []}

    # Fetch CombatantInfo from all boss fights in parallel
    import asyncio as _aio
    fight_tasks = [
        _fetch_combatant_info(report_code, f["id"], f["startTime"], f["endTime"])
        for f in boss_fights
    ]
    all_fight_events = await _aio.gather(*fight_tasks)

    # Track per-fight consumable data for each player
    player_gear: dict[int, list] = {}       # sourceID -> gear from first seen
    player_fight_data: dict[int, list] = {} # sourceID -> list of per-fight audits

    fight_names = [f.get("name", f"Fight {i+1}") for i, f in enumerate(boss_fights)]

    for fight_idx, fight_events in enumerate(all_fight_events):
        for ev in fight_events:
            source_id = ev.get("sourceID")
            if source_id not in players_by_id:
                continue

            gear_items = ev.get("gear", [])
            auras = ev.get("auras", [])
            player_class = players_by_id[source_id].get("subType", "")

            # Keep gear snapshot with the most enchants (best representation)
            if source_id not in player_gear:
                player_gear[source_id] = gear_items
            else:
                existing_enchants = sum(1 for g in player_gear[source_id] if g.get("permanentEnchant", 0))
                new_enchants = sum(1 for g in gear_items if g.get("permanentEnchant", 0))
                if new_enchants > existing_enchants:
                    player_gear[source_id] = gear_items

            # Audit consumables for this fight
            consumable_audit = _audit_consumables(auras, gear_items, player_class)
            consumable_audit["fight_idx"] = fight_idx
            consumable_audit["fight_name"] = fight_names[fight_idx]

            if source_id not in player_fight_data:
                player_fight_data[source_id] = []
            player_fight_data[source_id].append(consumable_audit)

    total_fights = len(boss_fights)

    # Build final audit with per-fight tracking and summary percentages
    player_audits = []
    for source_id, gear_items in player_gear.items():
        player = players_by_id.get(source_id)
        if not player:
            continue

        gear_audit = _audit_gear(gear_items)
        fight_data = player_fight_data.get(source_id, [])
        player_class = player.get("subType", "")

        # Compute per-category uptime percentages
        fights_present = len(fight_data)
        flask_count = sum(1 for f in fight_data if f.get("flask"))
        elixir_count = sum(1 for f in fight_data if f.get("elixirs"))
        food_count = sum(1 for f in fight_data if f.get("food"))
        weapon_count = sum(1 for f in fight_data if f.get("weapon_buff"))
        flask_or_elixir = sum(1 for f in fight_data if f.get("flask") or f.get("elixirs"))

        # Best snapshot for backwards-compatible "consumables" field
        best = max(fight_data, key=lambda f: sum([
            bool(f.get("flask")), len(f.get("elixirs", [])),
            bool(f.get("food")), bool(f.get("weapon_buff")),
        ])) if fight_data else {}

        # Aggregate all unique elixirs seen across fights for display
        all_elixirs = set()
        for f in fight_data:
            all_elixirs.update(f.get("elixirs", []))

        consumable_summary = {
            "flask": best.get("flask"),
            "elixirs": sorted(all_elixirs) if all_elixirs else best.get("elixirs", []),
            "food": best.get("food", False),
            "weapon_buff": best.get("weapon_buff"),
            "has_battle_elixir": best.get("has_battle_elixir", False),
            "has_guardian_elixir": best.get("has_guardian_elixir", False),
            "has_both_elixirs": best.get("has_both_elixirs", False),
            "fully_consumed": bool(best.get("flask") or best.get("has_both_elixirs")) and best.get("food", False),
        }

        # Per-fight breakdown
        per_fight = []
        for f in fight_data:
            per_fight.append({
                "fight": f.get("fight_name", ""),
                "flask": f.get("flask"),
                "elixirs": f.get("elixirs", []),
                "has_battle_elixir": f.get("has_battle_elixir", False),
                "has_guardian_elixir": f.get("has_guardian_elixir", False),
                "has_both_elixirs": f.get("has_both_elixirs", False),
                "food": bool(f.get("food")),
                "weapon_buff": f.get("weapon_buff"),
            })

        # Uptimes as percentages
        uptimes = {
            "flask_or_elixir": round(flask_or_elixir / max(fights_present, 1) * 100),
            "flask": round(flask_count / max(fights_present, 1) * 100),
            "elixir": round(elixir_count / max(fights_present, 1) * 100),
            "food": round(food_count / max(fights_present, 1) * 100),
            "weapon_buff": round(weapon_count / max(fights_present, 1) * 100),
            "fights_present": fights_present,
            "total_fights": total_fights,
        }

        # Overall score (avg of flask/elixir, food, weapon)
        scores = [uptimes["flask_or_elixir"], uptimes["food"], uptimes["weapon_buff"]]
        uptimes["overall"] = round(sum(scores) / len(scores))

        player_audits.append({
            "name": player["name"],
            "class": player.get("subType", "Unknown"),
            "spec_id": 0,
            "avg_ilvl": gear_audit["avg_ilvl"],
            "missing_enchants": gear_audit["missing_enchants"],
            "missing_gems": gear_audit["missing_gems"],
            "gear_warnings": gear_audit["gear_warnings"],
            "enchant_count": gear_audit["enchant_count"],
            "gem_count": gear_audit["gem_count"],
            "total_enchantable": gear_audit["total_enchantable"],
            "total_gem_slots": gear_audit["total_gem_slots"],
            "consumables": consumable_summary,
            "consumable_uptimes": uptimes,
            "consumable_per_fight": per_fight,
            "gear": gear_audit["items"],
        })

    player_audits.sort(key=lambda x: x["name"])

    return {
        "report_code": report_code,
        "fight_name": boss_fights[0].get("name", "Unknown") if boss_fights else "Unknown",
        "fight_names": fight_names,
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
    """Analyze gear for missing enchants, cheap enchants, and uncommon gems."""
    items = []
    total_ilvl = 0
    equipped_count = 0
    enchant_count = 0
    total_enchantable = 0
    gem_count = 0
    total_gem_slots = 0
    missing_enchants = []
    missing_gems = []
    gear_warnings = []  # cheap enchants, uncommon gems, etc.

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
                # Check if it's a cheap/suboptimal enchant
                cheap_ids = CHEAP_ENCHANTS.get(slot_idx, set())
                if enchant_id in cheap_ids:
                    name = CHEAP_ENCHANT_NAMES.get(enchant_id, f"Enchant {enchant_id}")
                    gear_warnings.append(f"{slot_name} [cheap enchant: {name}]")
                # Check shoulder honored-tier enchants
                if slot_idx == 2 and enchant_id in CHEAP_SHOULDER_ENCHANTS:
                    gear_warnings.append(
                        f"Shoulder [{CHEAP_SHOULDER_ENCHANTS[enchant_id]}]"
                    )
            else:
                missing_enchants.append(slot_name)

        # Check gems for uncommon quality
        if gems:
            gem_count += len(gems)
            total_gem_slots += len(gems)
            for gem in gems:
                gem_id = gem.get("id", 0)
                if gem_id in UNCOMMON_GEM_IDS:
                    gear_warnings.append(f"{slot_name or f'Slot {slot_idx}'} [uncommon gem]")
                    break  # only flag once per item

    avg_ilvl = round(total_ilvl / equipped_count) if equipped_count > 0 else 0

    return {
        "avg_ilvl": avg_ilvl,
        "enchant_count": enchant_count,
        "total_enchantable": total_enchantable,
        "missing_enchants": missing_enchants,
        "gem_count": gem_count,
        "total_gem_slots": total_gem_slots,
        "missing_gems": missing_gems,
        "gear_warnings": gear_warnings,
        "items": items,
    }


def _audit_consumables(auras: list[dict], gear_items: list[dict] | None = None, player_class: str = "") -> dict[str, Any]:
    """Check pre-pull auras and gear for consumable usage."""
    has_flask = False
    has_battle = False
    has_guardian = False
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
        elif name in BATTLE_ELIXIRS:
            has_battle = True
            elixir_names.append(name)
        elif name in GUARDIAN_ELIXIRS:
            has_guardian = True
            elixir_names.append(name)
        if name in FOOD_BUFFS:
            has_food = True
            food_name = name
        if name in WEAPON_BUFFS:
            has_weapon_buff = True
            weapon_buff_name = name

    # Check weapon slots for temporaryEnchant (weapon oils, stones, etc.)
    if not has_weapon_buff and gear_items:
        for slot_idx in (15, 16):  # MH, OH in WCL gear array
            if slot_idx < len(gear_items):
                item = gear_items[slot_idx]
                temp_enchant = item.get("temporaryEnchant", 0)
                if temp_enchant:
                    has_weapon_buff = True
                    name = TEMP_ENCHANT_NAMES.get(temp_enchant, f"Weapon Buff ({temp_enchant})")
                    # Resolve ambiguous IDs by class
                    if temp_enchant == 2641 and player_class == "Rogue":
                        name = "Poison"
                    weapon_buff_name = name
                    break

    has_elixir = has_battle or has_guardian
    has_both_elixirs = has_battle and has_guardian

    return {
        "flask": flask_name if has_flask else None,
        "elixirs": elixir_names if has_elixir else [],
        "has_battle_elixir": has_battle,
        "has_guardian_elixir": has_guardian,
        "has_both_elixirs": has_both_elixirs,
        "food": has_food,
        "weapon_buff": weapon_buff_name if has_weapon_buff else None,
        "fully_consumed": (has_flask or has_both_elixirs) and has_food,
    }
