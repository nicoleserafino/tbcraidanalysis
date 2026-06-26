"""Report fetching and normalization using WCL v2 API."""

from __future__ import annotations

import asyncio

from backend.analysis.utils import actor_name, infer_role, spell_name
from backend.wcl.client import graphql_query
from backend.wcl.queries import REPORT_FIGHTS, REPORT_EVENTS, REPORT_EVENTS_ENEMY_DEATHS, REPORT_TABLE


async def fetch_report_metadata(report_code: str) -> dict:
    """Fetch report fights and actors."""
    data = await graphql_query(REPORT_FIGHTS, {"code": report_code})
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

    while current_start is not None:
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
        current_start = events_data.get("nextPageTimestamp")

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
    while current_start is not None:
        variables = {
            "code": report_code,
            "fightIDs": fight_ids,
            "startTime": current_start,
            "endTime": end_time,
        }
        data = await graphql_query(REPORT_EVENTS_ENEMY_DEATHS, variables)
        events_data = data["reportData"]["report"]["events"]
        all_events.extend(events_data.get("data", []))
        current_start = events_data.get("nextPageTimestamp")
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

    bosses: dict[str, dict] = {}
    for fight in fights:
        boss_name = fight["name"]
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

        pull = build_pull_data(
            fight, actors_by_id, players_by_id, ability_names,
            deaths, enemy_deaths, interrupts, dispels, healing, casts,
            damage_taken, damage_done, buffs, threat,
            dmg_table, heal_table,
        )

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

    player_info = {}
    for p in sorted(players, key=lambda x: x["name"]):
        name = p["name"]
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
            deaths_out.append({
                "player": players_by_id[target_id]["name"],
                "relative_time": rel_sec(ev["timestamp"]),
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
            interrupts_out.append({
                "source": actor_name(source_id, actors_by_id),
                "ability": spell_name(ev, ability_names),
                "relative_time": rel_sec(ev["timestamp"]),
            })

    # Process dispels
    dispels_out = []
    for ev in dispels:
        if ev.get("type") != "dispel":
            continue
        source_id = ev.get("sourceID")
        if source_id in players_by_id:
            dispels_out.append({
                "source": actor_name(source_id, actors_by_id),
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

        heals_by_player[player] = heals_by_player.get(player, 0) + 1
        if player not in heal_details:
            heal_details[player] = {}
        if spell not in heal_details[player]:
            heal_details[player][spell] = {"total": 0, "overheal": 0, "count": 0, "is_hot": False}
        heal_details[player][spell]["total"] += amount
        heal_details[player][spell]["overheal"] += overheal
        heal_details[player][spell]["count"] += 1
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
                    })

        if amount > 0:
            biggest_heals.append({
                "player": player, "target": target_name or "Unknown",
                "spell": spell, "amount": amount,
                "crit": ev.get("hitType") == 2, "time": rel_sec(ev["timestamp"]),
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
    for ev in casts:
        if ev.get("type") != "cast":
            continue
        source_id = ev.get("sourceID")
        if source_id not in players_by_id:
            continue
        player = actor_name(source_id, actors_by_id)
        spell = spell_name(ev, ability_names)
        casts_by_player[player] = casts_by_player.get(player, 0) + 1
        cast_timeline.setdefault(player, []).append(rel_sec(ev["timestamp"]))
        spell_casts.setdefault(player, {})
        spell_casts[player][spell] = spell_casts[player].get(spell, 0) + 1

    # Process damage taken
    player_damage_taken = {}
    player_damage_taken_total = {}
    damage_sources = {}
    for ev in damage_taken:
        if ev.get("type") != "damage":
            continue
        target_id = ev.get("targetID")
        if target_id not in players_by_id:
            continue
        player = actor_name(target_id, actors_by_id)
        source = spell_name(ev, ability_names)
        amount = ev.get("amount", 0) + ev.get("absorbed", 0)
        player_damage_taken.setdefault(player, {})
        player_damage_taken[player][source] = player_damage_taken[player].get(source, 0) + 1
        player_damage_taken_total[player] = player_damage_taken_total.get(player, 0) + amount
        damage_sources[source] = damage_sources.get(source, 0) + 1

    # Process damage done table
    damage_done_out = {}
    if dmg_table and "entries" in dmg_table:
        for entry in dmg_table["entries"]:
            pid = entry.get("id")
            if pid not in players_by_id:
                continue
            player = players_by_id[pid]["name"]
            damage_done_out[player] = {}
            for ab in entry.get("abilities", []):
                name = ab.get("name", "Unknown")
                if name == "Melee":
                    name = "Melee (Auto Attack)"
                damage_done_out[player][name] = ab.get("total", 0)

    # Process buff events
    buff_events = {}
    for ev in buffs:
        if ev.get("type") not in ("applybuff", "removebuff", "refreshbuff", "applydebuff", "removedebuff"):
            continue
        target_id = ev.get("targetID")
        if target_id not in players_by_id:
            continue
        player = players_by_id[target_id]["name"]
        buff_events.setdefault(player, []).append({
            "spell": spell_name(ev, ability_names),
            "type": ev["type"],
            "time": rel_sec(ev["timestamp"]),
        })

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

    # Determine participants
    participants = sorted(set(
        players_by_id[pid]["name"] for pid in players_by_id
    ))

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
        "damage_done": damage_done_out,
        "damage_sources": damage_sources,
        "player_damage_taken": player_damage_taken,
        "player_damage_taken_total": player_damage_taken_total,
        "buff_events": buff_events,
        "threat_events": threat_events,
        "clutch_heals": clutch_heals[:10],
        "biggest_heals": biggest_heals[:5],
        "biggest_crits": biggest_crits[:5],
        "players": participants,
    }
