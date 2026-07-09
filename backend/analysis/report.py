"""Report fetching and normalization using WCL v2 API."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from backend.analysis.utils import actor_name, infer_role, spell_name
from backend.wcl.client import graphql_query
from backend.wcl.queries import REPORT_FIGHTS, REPORT_EVENTS, REPORT_EVENTS_ENEMY_DEATHS, REPORT_TABLE, REPORT_EVENTS_WITH_RESOURCES


async def fetch_report_metadata(report_code: str) -> dict:
    """Fetch report fights and actors."""
    data = await graphql_query(REPORT_FIGHTS, {"code": report_code, "killType": "Encounters"})
    report = data["reportData"]["report"]
    return report


async def fetch_events_paginated(
    report_code: str,
    fight_ids: list[int],
    data_type: str,
    start_time: float,
    end_time: float,
    filter_expression: str | None = None,
    source_id: int | None = None,
    target_id: int | None = None,
) -> list[dict]:
    """Fetch all pages of events for a fight."""
    all_events = []
    current_start = start_time
    max_pages = 50  # safety guard against infinite pagination

    for _ in range(max_pages):
        if current_start is None:
            break
        variables = {
            "code": report_code,
            "fightIDs": fight_ids,
            "dataType": data_type,
            "startTime": current_start,
            "endTime": end_time,
        }
        if filter_expression:
            variables["filterExpression"] = filter_expression
        if source_id is not None:
            variables["sourceID"] = source_id
        if target_id is not None:
            variables["targetID"] = target_id

        data = await graphql_query(REPORT_EVENTS, variables)
        events_data = data["reportData"]["report"]["events"]
        all_events.extend(events_data.get("data", []))
        next_start = events_data.get("nextPageTimestamp")
        if next_start == current_start:
            break  # prevent infinite loop on stuck pagination
        current_start = next_start

    return all_events


async def fetch_enemy_deaths(
    report_code: str,
    fight_ids: list[int],
    start_time: float,
    end_time: float,
) -> list[dict]:
    """Fetch enemy/NPC death events for a fight."""
    all_events = []
    current_start = start_time
    for _ in range(50):
        if current_start is None:
            break
        variables = {
            "code": report_code,
            "fightIDs": fight_ids,
            "startTime": current_start,
            "endTime": end_time,
        }
        data = await graphql_query(REPORT_EVENTS_ENEMY_DEATHS, variables)
        events_data = data["reportData"]["report"]["events"]
        all_events.extend(events_data.get("data", []))
        next_start = events_data.get("nextPageTimestamp")
        if next_start == current_start:
            break
        current_start = next_start
    return all_events


async def fetch_table(
    report_code: str,
    fight_ids: list[int],
    data_type: str,
    start_time: float,
    end_time: float,
    source_id: int | None = None,
    target_id: int | None = None,
) -> dict:
    """Fetch a table summary for a fight."""
    variables = {
        "code": report_code,
        "fightIDs": fight_ids,
        "dataType": data_type,
        "startTime": start_time,
        "endTime": end_time,
    }
    if source_id is not None:
        variables["sourceID"] = source_id
    if target_id is not None:
        variables["targetID"] = target_id

    data = await graphql_query(REPORT_TABLE, variables)
    table = data["reportData"]["report"]["table"]
    # v2 wraps table content in a "data" key
    if isinstance(table, dict) and "data" in table and isinstance(table["data"], dict):
        return table["data"]
    return table


async def fetch_events_with_resources(
    report_code: str,
    fight_ids: list[int],
    data_type: str,
    start_time: float,
    end_time: float,
    filter_expression: str | None = None,
) -> list[dict]:
    """Fetch events with position/resource data (x, y, facing)."""
    all_events = []
    current_start = start_time
    for _ in range(50):
        if current_start is None:
            break
        variables = {
            "code": report_code,
            "fightIDs": fight_ids,
            "dataType": data_type,
            "startTime": current_start,
            "endTime": end_time,
        }
        if filter_expression:
            variables["filterExpression"] = filter_expression
        data = await graphql_query(REPORT_EVENTS_WITH_RESOURCES, variables)
        events_data = data["reportData"]["report"]["events"]
        all_events.extend(events_data.get("data", []))
        next_start = events_data.get("nextPageTimestamp")
        if next_start == current_start:
            break
        current_start = next_start
    return all_events


async def fetch_full_report(report_code: str) -> dict:
    """Fetch a complete report: metadata + per-fight event data.

    Returns a structure compatible with the frontend's expected data shape.
    """
    metadata = await fetch_report_metadata(report_code)
    fights = metadata.get("fights", []) or []
    actors = metadata.get("masterData", {}).get("actors", []) or []

    # Build actor lookup
    actors_by_id = {a["id"]: a for a in actors if a.get("id") is not None}
    players = [a for a in actors if a.get("type") == "Player"]
    players_by_id = {p["id"]: p for p in players if p.get("id") is not None}

    # Build ability name lookup (v2 uses abilityGameID instead of ability.name)
    abilities = metadata.get("masterData", {}).get("abilities", []) or []
    ability_names = {a["gameID"]: a["name"] for a in abilities if a.get("gameID")}

    # Aggregate spell casts, healing, damage for role inference
    agg_spell_casts: dict[str, dict[str, int]] = {}
    agg_healing: dict[str, int] = {}
    agg_damage_done: dict[str, int] = {}
    agg_damage_taken: dict[str, int] = {}

    async def process_fight(fight: dict, semaphore: asyncio.Semaphore) -> tuple[dict, dict]:
        async with semaphore:
            fight_id = fight["id"]
            start = fight["startTime"]
            end = fight["endTime"]

            (
                deaths,
                enemy_deaths,
                interrupts,
                dispels,
                healing,
                casts,
                damage_taken,
                damage_done,
                buffs,
                threat,
                dmg_table,
                heal_table,
            ) = await asyncio.gather(
                fetch_events_paginated(report_code, [fight_id], "Deaths", start, end),
                fetch_enemy_deaths(report_code, [fight_id], start, end),
                fetch_events_paginated(report_code, [fight_id], "Interrupts", start, end),
                fetch_events_paginated(report_code, [fight_id], "Dispels", start, end),
                fetch_events_paginated(report_code, [fight_id], "Healing", start, end),
                fetch_events_paginated(report_code, [fight_id], "Casts", start, end),
                fetch_events_paginated(report_code, [fight_id], "DamageTaken", start, end),
                fetch_events_paginated(report_code, [fight_id], "DamageDone", start, end),
                fetch_events_paginated(report_code, [fight_id], "Buffs", start, end),
                fetch_events_paginated(report_code, [fight_id], "Threat", start, end),
                fetch_table(report_code, [fight_id], "DamageDone", start, end),
                fetch_table(report_code, [fight_id], "Healing", start, end),
            )

            # Fetch WW position data for Leotheras fights
            ww_position_events = []
            all_player_positions = []
            if "leotheras" in fight.get("name", "").lower():
                ww_position_events, all_player_positions = await asyncio.gather(
                    fetch_events_with_resources(
                        report_code, [fight_id], "DamageTaken", start, end,
                        filter_expression="ability.name = 'Whirlwind'"
                    ),
                    fetch_events_with_resources(
                        report_code, [fight_id], "Casts", start, end,
                    ),
                )

            pull = build_pull_data(
                fight, actors_by_id, players_by_id, ability_names,
                deaths, enemy_deaths, interrupts, dispels, healing, casts,
                damage_taken, damage_done, buffs, threat,
                dmg_table, heal_table, ww_position_events, all_player_positions,
            )
            return fight, pull

    semaphore = asyncio.Semaphore(4)
    fight_results = await asyncio.gather(*(process_fight(fight, semaphore) for fight in fights))

    bosses: dict[str, dict] = {}
    for fight, pull in fight_results:
        boss_name = fight["name"]

        # Aggregate for role inference
        for player, spells in pull.get("spell_casts", {}).items():
            agg_spell_casts.setdefault(player, {})
            for spell, count in spells.items():
                agg_spell_casts[player][spell] = agg_spell_casts[player].get(spell, 0) + count

        for player, details in pull.get("heal_details", {}).items():
            for info in details.values():
                agg_healing[player] = agg_healing.get(player, 0) + info.get("total", 0)

        for player, spells in pull.get("damage_done", {}).items():
            for total in spells.values():
                agg_damage_done[player] = agg_damage_done.get(player, 0) + total

        for player, total in pull.get("player_damage_taken_total", {}).items():
            agg_damage_taken[player] = agg_damage_taken.get(player, 0) + total

        if boss_name not in bosses:
            bosses[boss_name] = {"total_pulls": 0, "kills": 0, "wipes": 0, "pulls": []}
        entry = bosses[boss_name]
        entry["pulls"].append(pull)
        entry["total_pulls"] += 1
        if pull["kill"]:
            entry["kills"] += 1
        else:
            entry["wipes"] += 1

    # Only include players who participated in at least one boss fight
    active_names = set()
    for boss_entry in bosses.values():
        for pull in boss_entry["pulls"]:
            active_names.update(pull.get("players", []))

    player_info = {}
    for p in sorted(players, key=lambda x: x["name"]):
        name = p["name"]
        if name not in active_names:
            continue
        player_class = p["subType"]
        role = infer_role(
            player_class,
            spell_counts=agg_spell_casts.get(name, {}),
            total_healing=agg_healing.get(name, 0),
            total_damage_done=agg_damage_done.get(name, 0),
            total_damage_taken=agg_damage_taken.get(name, 0),
        )
        player_info[name] = {"role": role, "class": player_class}

    # Attach roles to each pull
    for boss_entry in bosses.values():
        for pull in boss_entry["pulls"]:
            pull["roles"] = {}
            for name in pull.get("players", []):
                if name in player_info:
                    pull["roles"][name] = player_info[name]["role"]

    return {
        "log_info": {
            "file": report_code,
            "total_encounters": len(fights),
            "report_id": report_code,
            "title": metadata.get("title", report_code),
        },
        "players": player_info,
        "bosses": bosses,
    }


def build_pull_data(
    fight: dict,
    actors_by_id: dict,
    players_by_id: dict,
    ability_names: dict,
    deaths: list,
    enemy_deaths: list,
    interrupts: list,
    dispels: list,
    healing: list,
    casts: list,
    damage_taken: list,
    damage_done_events: list,
    buffs: list,
    threat: list,
    dmg_table: dict | None = None,
    heal_table: dict | None = None,
    ww_position_events: list | None = None,
    all_player_positions: list | None = None,
) -> dict:
    """Build a normalized pull data structure from raw events."""
    start = fight["startTime"]
    end = fight["endTime"]
    duration_sec = round((end - start) / 1000, 2)

    def rel_sec(ts: int) -> float:
        return round((ts - start) / 1000, 1)

    # Process deaths
    deaths_out = []
    for ev in deaths:
        if ev.get("type") != "death":
            continue
        target_id = ev.get("targetID")
        if target_id in players_by_id:
            # Extract killing blow ability if available
            killing_ability = ""
            if ev.get("killingAbility"):
                killing_ability = ev["killingAbility"].get("name", "") or ability_names.get(ev["killingAbility"].get("guid", 0), "")
            elif ev.get("ability"):
                killing_ability = ev["ability"].get("name", "") or ability_names.get(ev["ability"].get("guid", 0), "")
            deaths_out.append({
                "player": players_by_id[target_id]["name"],
                "relative_time": rel_sec(ev["timestamp"]),
                "ability": killing_ability,
            })

    # Process enemy/creature deaths (weapons, advisors, etc.)
    creature_deaths_out = []
    for ev in enemy_deaths:
        if ev.get("type") != "death":
            continue
        target_id = ev.get("targetID")
        name = actors_by_id.get(target_id, {}).get("name", "Unknown") if target_id else "Unknown"
        creature_deaths_out.append({
            "name": name,
            "relative_time": rel_sec(ev["timestamp"]),
        })

    # Process interrupts
    interrupts_out = []
    for ev in interrupts:
        if ev.get("type") != "interrupt":
            continue
        source_id = ev.get("sourceID")
        if source_id in players_by_id:
            # extraAbilityGameID is the spell that was interrupted
            interrupted_spell_id = ev.get("extraAbilityGameID")
            interrupted_name = ability_names.get(interrupted_spell_id, "") if interrupted_spell_id else ""
            target_id = ev.get("targetID")
            interrupts_out.append({
                "source": actor_name(source_id, actors_by_id),
                "ability": spell_name(ev, ability_names),
                "target": actor_name(target_id, actors_by_id) if target_id else "",
                "interrupted_spell": interrupted_name,
                "relative_time": rel_sec(ev["timestamp"]),
            })

    # Process dispels — include target and debuff name for reaction time analysis
    dispels_out = []
    for ev in dispels:
        if ev.get("type") != "dispel":
            continue
        source_id = ev.get("sourceID")
        if source_id in players_by_id:
            target_id = ev.get("targetID")
            dispels_out.append({
                "source": actor_name(source_id, actors_by_id),
                "target": actor_name(target_id, actors_by_id) if target_id in players_by_id else "",
                "spell": spell_name(ev, ability_names),
                "relative_time": rel_sec(ev["timestamp"]),
            })

    # Process healing — track clutch heals and biggest heals
    heals_by_player = {}
    heal_details = {}
    clutch_heals = []
    biggest_heals = []
    biggest_crits = []

    NON_HEAL_ABILITIES = {
        "Bloodthirst", "Vampiric Embrace", "Judgement of Light",
        "Siphon Life", "Drain Life", "Death Coil", "Fel Armor",
        "Spirit Link", "Second Wind", "Cannibalize", "Mana Drain",
        "Touch of Weakness", "Devour Magic", "Lock and Load",
        "Improved Leader of the Pack", "Leader of the Pack",
    }

    # Track last seen (sourceID, spell, timestamp) to deduplicate AoE heal casts
    # AoE heals like Circle of Healing emit one event per target at the same timestamp
    _last_heal_cast = {}  # (source_id, spell) -> last_timestamp

    for ev in healing:
        if ev.get("type") != "heal":
            continue
        source_id = ev.get("sourceID")
        if source_id not in players_by_id:
            continue
        player = actor_name(source_id, actors_by_id)
        spell = spell_name(ev, ability_names)
        amount = ev.get("amount", 0)
        overheal = ev.get("overheal", 0)
        timestamp = ev.get("timestamp", 0)

        heals_by_player[player] = heals_by_player.get(player, 0) + 1
        if player not in heal_details:
            heal_details[player] = {}
        if spell not in heal_details[player]:
            heal_details[player][spell] = {"total": 0, "overheal": 0, "count": 0, "is_hot": False}
        heal_details[player][spell]["total"] += amount
        heal_details[player][spell]["overheal"] += overheal

        # Count casts (not hits): same spell at same timestamp = one cast
        cast_key = (source_id, spell)
        last_ts = _last_heal_cast.get(cast_key, -1)
        if timestamp != last_ts:
            heal_details[player][spell]["count"] += 1
            _last_heal_cast[cast_key] = timestamp

        if ev.get("tick"):
            heal_details[player][spell]["is_hot"] = True

        # Clutch heal tracking
        target_id = ev.get("targetID")
        target_name = players_by_id.get(target_id, {}).get("name") if target_id else None
        hit_points = ev.get("hitPoints")

        if amount > 0 and hit_points and target_name and spell not in NON_HEAL_ABILITIES:
            hp_before = hit_points - amount
            if hp_before >= 0 and hit_points > 0:
                hp_pct = round(hp_before / hit_points * 100, 1)
                if hp_pct < 20:
                    clutch_heals.append({
                        "healer": player, "target": target_name, "spell": spell,
                        "amount": amount, "hp_pct": hp_pct,
                        "time": rel_sec(ev["timestamp"]),
                        "self_heal": source_id == target_id,
                        "is_hot": bool(ev.get("tick")),
                    })

        if amount > 0:
            biggest_heals.append({
            "player": player, "target": target_name or "Unknown",
            "spell": spell, "amount": amount,
            "crit": ev.get("hitType") == 2, "time": rel_sec(ev["timestamp"]),
            "is_hot": bool(ev.get("tick")),
            })
        if ev.get("hitType") == 2 and amount > 0:
            biggest_crits.append({
                "player": player, "spell": spell, "amount": amount,
                "type": "heal", "time": rel_sec(ev["timestamp"]),
            })

    # Process damage done for crits
    for ev in damage_done_events:
        if ev.get("type") != "damage":
            continue
        source_id = ev.get("sourceID")
        if source_id not in players_by_id:
            continue
        if ev.get("hitType") == 2 and (ev.get("amount", 0)) > 0:
            biggest_crits.append({
                "player": players_by_id[source_id]["name"],
                "spell": spell_name(ev, ability_names),
                "amount": ev["amount"], "type": "damage",
                "time": rel_sec(ev["timestamp"]),
            })

    # Process casts
    casts_by_player = {}
    cast_timeline = {}
    spell_casts = {}
    spell_cast_times = {}  # player -> spell -> [relative_seconds] for totem/CD tracking
    # Spells to track timestamps for (totems, CDs, key abilities)
    TRACKED_SPELL_TIMES = {
        "Windfury Totem", "Grace of Air Totem", "Wrath of Air Totem",
        "Tranquil Air Totem", "Grounding Totem",
        "Strength of Earth Totem", "Stoneskin Totem", "Tremor Totem",
        "Earthbind Totem", "Earth Elemental Totem",
        "Searing Totem", "Totem of Wrath", "Fire Nova Totem",
        "Magma Totem", "Fire Elemental Totem",
        "Mana Spring Totem", "Mana Tide Totem", "Healing Stream Totem",
        "Bloodlust", "Heroism", "Drums of Battle", "Drums of War",
        "Drums of Restoration",
    }
    # Track NPC casts that completed (for missed interrupt detection)
    # Key spells that SHOULD be interrupted per boss
    INTERRUPTIBLE_SPELLS = {
        # Karathress council
        "Healing Wave", "Greater Healing Wave",
        # Kael'thas P4
        "Fireball", "Pyroblast",
        # Kael P2 weapons
        "Heal",
        # Solarian adds
        "Greater Heal",
        # General
        "Shadow Bolt Volley", "Fear", "Bellowing Roar",
    }
    enemy_casts_completed = {}  # {spell_name: count}
    cancelled_casts = {}  # {player: count} — begincast without matching cast
    begincast_pending = {}  # {(sourceID, spell): timestamp}
    for ev in casts:
        source_id = ev.get("sourceID")
        spell = spell_name(ev, ability_names)
        if ev.get("type") == "begincast" and source_id in players_by_id:
            begincast_pending[(source_id, spell)] = ev["timestamp"]
            continue
        if ev.get("type") != "cast":
            continue
        if source_id in players_by_id:
            player = actor_name(source_id, actors_by_id)
            # Clear pending begincast (this cast completed)
            begincast_pending.pop((source_id, spell), None)
            casts_by_player[player] = casts_by_player.get(player, 0) + 1
            cast_timeline.setdefault(player, []).append(rel_sec(ev["timestamp"]))
            spell_casts.setdefault(player, {})
            spell_casts[player][spell] = spell_casts[player].get(spell, 0) + 1
            # Track per-spell timestamps for totems and key abilities
            if spell in TRACKED_SPELL_TIMES:
                spell_cast_times.setdefault(player, {}).setdefault(spell, []).append(
                    rel_sec(ev["timestamp"])
                )
        else:
            # NPC cast that completed — track if it's an interruptible spell
            if spell in INTERRUPTIBLE_SPELLS:
                source_name = actor_name(source_id, actors_by_id) if source_id else "Unknown"
                key = f"{spell} ({source_name})"
                enemy_casts_completed[key] = enemy_casts_completed.get(key, 0) + 1

    # Count cancelled casts: begincast events that were never followed by a cast
    for (src_id, _spell), _ts in begincast_pending.items():
        if src_id in players_by_id:
            player = actor_name(src_id, actors_by_id)
            cancelled_casts[player] = cancelled_casts.get(player, 0) + 1

    # Process damage taken — label includes source NPC name for mechanic identification
    player_damage_taken = {}
    player_damage_taken_total = {}
    player_damage_taken_amounts = {}  # per-ability damage amounts (not just counts)
    damage_sources = {}
    conflagrations = []

    # Conflagration spell IDs (Kael'thas - Capernian)
    CONFLAG_IDS = {36965, 37018, 37019}

    for ev in damage_taken:
        if ev.get("type") != "damage":
            continue
        target_id = ev.get("targetID")
        if target_id not in players_by_id:
            continue
        player = actor_name(target_id, actors_by_id)
        ability = spell_name(ev, ability_names)
        amount = ev.get("amount", 0) + ev.get("absorbed", 0)

        # Build label: include source name when source is not a player
        # This covers boss NPCs and boss pets (e.g., Spitfire Totem)
        source_id = ev.get("sourceID")
        source_npc = ""
        if source_id and source_id not in players_by_id:
            source_actor = actors_by_id.get(source_id, {})
            source_npc = source_actor.get("name", "")
        if source_npc and source_npc.lower() != ability.lower():
            label = f"{ability} ({source_npc})"
        else:
            label = ability

        player_damage_taken.setdefault(player, {})
        player_damage_taken[player][label] = player_damage_taken[player].get(label, 0) + 1
        player_damage_taken_amounts.setdefault(player, {})
        player_damage_taken_amounts[player][label] = player_damage_taken_amounts[player].get(label, 0) + amount
        player_damage_taken_total[player] = player_damage_taken_total.get(player, 0) + amount
        damage_sources[label] = damage_sources.get(label, 0) + 1

        # Track conflagration events
        ability_id = ev.get("abilityGameID") or (ev.get("ability") or {}).get("guid")
        if ability_id in CONFLAG_IDS or "conflag" in ability.lower():
            conflagrations.append({
                "target": player,
                "relative_time": rel_sec(ev["timestamp"]),
                "amount": amount,
            })

    # ─── Leotheras Whirlwind Phase Analysis ───────────────────────────────
    # Detects WW phases, identifies ranged targets hit (WW escaped melee),
    # and includes per-second position data for path visualization.
    whirlwind_analysis = None
    if "leotheras" in fight["name"].lower():
        RANGED_CLASSES = {"Mage", "Warlock", "Hunter", "Priest"}
        ww_events = []
        for ev in damage_taken:
            if ev.get("type") != "damage":
                continue
            ability = spell_name(ev, ability_names)
            if "whirlwind" not in ability.lower():
                continue
            target_id = ev.get("targetID")
            if target_id not in players_by_id:
                continue
            ww_events.append({
                "timestamp": ev["timestamp"],
                "target_id": target_id,
                "target": players_by_id[target_id]["name"],
                "class": players_by_id[target_id].get("subType", ""),
                "amount": ev.get("amount", 0) + ev.get("absorbed", 0),
                "time": rel_sec(ev["timestamp"]),
            })

        # Build position lookup from ww_position_events (has x/y per hit)
        pos_events = ww_position_events or []
        # Index: (timestamp, target_id) -> (x, y)
        pos_lookup: dict[tuple[int, int], tuple[int, int]] = {}
        for ev in pos_events:
            if ev.get("x") is not None and ev.get("targetID") in players_by_id:
                pos_lookup[(ev["timestamp"], ev["targetID"])] = (ev["x"], ev["y"])

        # Build a timeline of all player positions from cast events
        # Key: sourceID -> list of (timestamp, x, y)
        cast_pos_timeline: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        for ev in (all_player_positions or []):
            if ev.get("x") is not None and ev.get("sourceID") in players_by_id:
                cast_pos_timeline[ev["sourceID"]].append(
                    (ev["timestamp"], ev["x"], ev["y"])
                )

        if ww_events:
            # Split into phases (gap > 5s between damage = new phase)
            phases = []
            current_phase: list[dict] = [ww_events[0]]
            for ev in ww_events[1:]:
                if ev["timestamp"] - current_phase[-1]["timestamp"] > 5000:
                    phases.append(current_phase)
                    current_phase = [ev]
                else:
                    current_phase.append(ev)
            phases.append(current_phase)

            phase_results = []
            for phase_events in phases:
                phase_start = phase_events[0]["time"]
                phase_end = phase_events[-1]["time"]
                # Group by 1-second ticks per target
                target_ticks: dict[str, list[float]] = {}
                for ev in phase_events:
                    target_ticks.setdefault(ev["target"], []).append(ev["time"])

                # Classify targets
                melee_targets = []
                ranged_targets = []
                for ev in phase_events:
                    name = ev["target"]
                    pclass = ev["class"]
                    entry = {"name": name, "class": pclass}
                    if pclass in RANGED_CLASSES:
                        if not any(t["name"] == name for t in ranged_targets):
                            ticks = target_ticks[name]
                            ranged_targets.append({
                                **entry,
                                "hits": len(ticks),
                                "first_hit": min(ticks),
                                "last_hit": max(ticks),
                                "exposure": round(max(ticks) - min(ticks), 1) if len(ticks) > 1 else 0,
                            })
                    else:
                        if not any(t["name"] == name for t in melee_targets):
                            melee_targets.append({**entry, "hits": len(target_ticks[name])})

                # Deaths during this phase
                phase_deaths = [
                    d for d in deaths_out
                    if phase_start <= d["relative_time"] <= phase_end + 3
                ]

                # Build per-second path data (centroid of hit positions per tick)
                # and player positions for the map visualization
                path_points = []
                player_positions: dict[str, dict] = {}  # name -> {x, y, class, is_ranged, was_hit}
                phase_start_ts = phase_events[0]["timestamp"]
                phase_end_ts = phase_events[-1]["timestamp"]

                # Group position events by second
                sec_positions: dict[int, list[tuple[int, int]]] = defaultdict(list)

                for ev in phase_events:
                    tid = ev["target_id"]
                    ts = ev["timestamp"]
                    pos = pos_lookup.get((ts, tid))
                    if pos:
                        sec = int((ts - phase_start_ts) / 1000)
                        sec_positions[sec].append(pos)
                        # Track hit player position (use first seen position)
                        if ev["target"] not in player_positions:
                            player_positions[ev["target"]] = {
                                "x": pos[0], "y": pos[1],
                                "class": ev["class"],
                                "is_ranged": ev["class"] in RANGED_CLASSES,
                                "was_hit": True,
                            }

                # Add positions for ALL players from cast events during this phase
                for pid, timeline in cast_pos_timeline.items():
                    pname = players_by_id[pid]["name"]
                    if pname in player_positions:
                        continue  # already have from WW hits
                    pclass = players_by_id[pid].get("subType", "")
                    # Find closest cast position to phase start
                    best_pos = None
                    best_dist = float("inf")
                    for ts, x, y in timeline:
                        # Prefer positions during the phase, or just before
                        if phase_start_ts - 5000 <= ts <= phase_end_ts + 2000:
                            dist = abs(ts - phase_start_ts)
                            if dist < best_dist:
                                best_dist = dist
                                best_pos = (x, y)
                    if best_pos:
                        player_positions[pname] = {
                            "x": best_pos[0], "y": best_pos[1],
                            "class": pclass,
                            "is_ranged": pclass in RANGED_CLASSES,
                            "was_hit": False,
                        }

                for sec in sorted(sec_positions.keys()):
                    positions = sec_positions[sec]
                    cx = sum(p[0] for p in positions) / len(positions)
                    cy = sum(p[1] for p in positions) / len(positions)
                    path_points.append({
                        "sec": sec,
                        "x": round(cx),
                        "y": round(cy),
                    })

                escaped = len(ranged_targets) > 0
                phase_results.append({
                    "phase_num": len(phase_results) + 1,
                    "start_time": phase_start,
                    "end_time": phase_end,
                    "duration": round(phase_end - phase_start, 1),
                    "escaped": escaped,
                    "melee_targets": melee_targets,
                    "ranged_targets": ranged_targets,
                    "deaths": phase_deaths,
                    "total_targets": len(melee_targets) + len(ranged_targets),
                    "path": path_points,
                    "positions": player_positions,
                })

            whirlwind_analysis = {
                "total_phases": len(phase_results),
                "escaped_phases": sum(1 for p in phase_results if p["escaped"]),
                "clean_phases": sum(1 for p in phase_results if not p["escaped"]),
                "phases": phase_results,
            }

    # Process damage done table
    damage_done_out = {}
    damage_totals = {}  # Canonical per-player totals from WCL table
    if dmg_table and "entries" in dmg_table:
        for entry in dmg_table["entries"]:
            pid = entry.get("id")
            if pid not in players_by_id:
                continue
            player = players_by_id[pid]["name"]
            damage_totals[player] = entry.get("total", 0)
            damage_done_out[player] = {}
            for ab in entry.get("abilities", []):
                name = ab.get("name", "Unknown")
                if name == "Melee":
                    name = "Melee (Auto Attack)"
                damage_done_out[player][name] = damage_done_out[player].get(name, 0) + ab.get("total", 0)

    # Process buff events
    buff_events = {}
    for ev in buffs:
        if ev.get("type") not in ("applybuff", "removebuff", "refreshbuff", "applydebuff", "removedebuff"):
            continue
        target_id = ev.get("targetID")
        if target_id not in players_by_id:
            continue
        player = players_by_id[target_id]["name"]
        entry = {
            "spell": spell_name(ev, ability_names),
            "type": ev["type"],
            "time": rel_sec(ev["timestamp"]),
        }
        # Include source (caster) for external buffs like Power Infusion, Pain Suppression
        source_id = ev.get("sourceID")
        if source_id and source_id != target_id and source_id in players_by_id:
            entry["source"] = players_by_id[source_id]["name"]
        buff_events.setdefault(player, []).append(entry)

    # Process threat events (new in v2!)
    threat_events = []
    for ev in threat:
        source_id = ev.get("sourceID")
        if source_id in players_by_id:
            threat_events.append({
                "player": players_by_id[source_id]["name"],
                "amount": ev.get("amount", 0),
                "time": rel_sec(ev["timestamp"]),
            })

    # Sort and trim
    clutch_heals.sort(key=lambda x: x["hp_pct"])
    biggest_heals.sort(key=lambda x: -x["amount"])
    biggest_crits.sort(key=lambda x: -x["amount"])

    # Determine participants — only players who had activity in this fight
    active_players = set()
    active_players.update(casts_by_player.keys())
    active_players.update(heals_by_player.keys())
    active_players.update(damage_done_out.keys())
    active_players.update(player_damage_taken_total.keys())
    active_players.update(d["player"] for d in deaths_out)
    participants = sorted(active_players)

    return {
        "fight_id": fight["id"],
        "encounter_id": fight.get("encounterID"),
        "boss_name": fight["name"],
        "duration_sec": duration_sec,
        "kill": bool(fight.get("kill")),
        "deaths": deaths_out,
        "creature_deaths": creature_deaths_out,
        "interrupts": interrupts_out,
        "dispels": dispels_out,
        "heals_by_player": heals_by_player,
        "heal_details": heal_details,
        "casts_by_player": casts_by_player,
        "cast_timeline": cast_timeline,
        "spell_casts": spell_casts,
        "spell_cast_times": spell_cast_times,
        "cancelled_casts": cancelled_casts,
        "damage_done": damage_done_out,
        "damage_totals": damage_totals,
        "damage_sources": damage_sources,
        "player_damage_taken": player_damage_taken,
        "player_damage_taken_amounts": player_damage_taken_amounts,
        "player_damage_taken_total": player_damage_taken_total,
        "enemy_casts_completed": enemy_casts_completed,
        "buff_events": buff_events,
        "threat_events": threat_events,
        "conflagrations": conflagrations,
        "whirlwind_analysis": whirlwind_analysis,
        "clutch_heals": clutch_heals[:10],
        "biggest_heals": biggest_heals[:5],
        "biggest_crits": biggest_crits[:5],
        "players": participants,
    }
