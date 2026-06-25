"""Report fetching and normalization using WCL v2 API."""

from __future__ import annotations

from backend.wcl.client import graphql_query
from backend.wcl.queries import REPORT_FIGHTS, REPORT_EVENTS, REPORT_TABLE


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

        data = await graphql_query(REPORT_EVENTS, variables)
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
    return data["reportData"]["report"]["table"]


async def fetch_full_report(report_code: str) -> dict:
    """Fetch a complete report: metadata + per-fight event data.

    Returns a structure compatible with the frontend's expected data shape.
    """
    metadata = await fetch_report_metadata(report_code)
    fights = metadata["fights"]
    actors = metadata["masterData"]["actors"]

    # Build actor lookup
    actors_by_id = {a["id"]: a for a in actors}
    players = [a for a in actors if a["type"] == "Player"]
    players_by_id = {p["id"]: p for p in players}

    bosses = {}
    for fight in fights:
        boss_name = fight["name"]
        fight_id = fight["id"]
        start = fight["startTime"]
        end = fight["endTime"]

        # Fetch events in parallel-ish (sequentially for now, can optimize later)
        deaths = await fetch_events_paginated(report_code, [fight_id], "Deaths", start, end)
        interrupts = await fetch_events_paginated(report_code, [fight_id], "Interrupts", start, end)
        dispels = await fetch_events_paginated(report_code, [fight_id], "Dispels", start, end)
        healing = await fetch_events_paginated(report_code, [fight_id], "Healing", start, end)
        casts = await fetch_events_paginated(report_code, [fight_id], "Casts", start, end)
        damage_taken = await fetch_events_paginated(report_code, [fight_id], "DamageTaken", start, end)
        damage_done = await fetch_events_paginated(report_code, [fight_id], "DamageDone", start, end)
        buffs = await fetch_events_paginated(report_code, [fight_id], "Buffs", start, end)
        threat = await fetch_events_paginated(report_code, [fight_id], "Threat", start, end)

        # Fetch tables
        dmg_table = await fetch_table(report_code, [fight_id], "DamageDone", start, end)
        heal_table = await fetch_table(report_code, [fight_id], "Healing", start, end)

        pull = build_pull_data(
            fight, actors_by_id, players_by_id,
            deaths, interrupts, dispels, healing, casts,
            damage_taken, damage_done, buffs, threat,
            dmg_table, heal_table, metadata["startTime"],
        )

        if boss_name not in bosses:
            bosses[boss_name] = {"name": boss_name, "pulls": []}
        bosses[boss_name]["pulls"].append(pull)

    return {
        "title": metadata.get("title", report_code),
        "report_id": report_code,
        "start_time": metadata["startTime"],
        "end_time": metadata["endTime"],
        "bosses": bosses,
        "players": {p["name"]: {"id": p["id"], "class": p["subType"]} for p in players},
    }


def build_pull_data(
    fight: dict,
    actors_by_id: dict,
    players_by_id: dict,
    deaths: list,
    interrupts: list,
    dispels: list,
    healing: list,
    casts: list,
    damage_taken: list,
    damage_done_events: list,
    buffs: list,
    threat: list,
    report_start_ms: int,
    dmg_table: dict | None = None,
    heal_table: dict | None = None,
) -> dict:
    """Build a normalized pull data structure from raw events."""
    start = fight["startTime"]
    end = fight["endTime"]
    duration_sec = round((end - start) / 1000, 2)

    def actor_name(actor_id: int) -> str:
        a = actors_by_id.get(actor_id)
        return a["name"] if a else f"Unknown ({actor_id})"

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

    # Process interrupts
    interrupts_out = []
    for ev in interrupts:
        if ev.get("type") != "interrupt":
            continue
        source_id = ev.get("sourceID")
        if source_id in players_by_id:
            interrupts_out.append({
                "source": players_by_id[source_id]["name"],
                "ability": ev.get("ability", {}).get("name", "Unknown"),
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
                "source": players_by_id[source_id]["name"],
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
        player = players_by_id[source_id]["name"]
        spell = ev.get("ability", {}).get("name", "Unknown")
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
                "spell": ev.get("ability", {}).get("name", "Unknown"),
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
        player = players_by_id[source_id]["name"]
        spell = ev.get("ability", {}).get("name", "Unknown")
        casts_by_player[player] = casts_by_player.get(player, 0) + 1
        cast_timeline.setdefault(player, []).append(rel_sec(ev["timestamp"]))
        spell_casts.setdefault(player, {})
        spell_casts[player][spell] = spell_casts[player].get(spell, 0) + 1

    # Process damage taken
    player_damage_taken = {}
    damage_sources = {}
    for ev in damage_taken:
        if ev.get("type") != "damage":
            continue
        target_id = ev.get("targetID")
        if target_id not in players_by_id:
            continue
        player = players_by_id[target_id]["name"]
        source = ev.get("ability", {}).get("name", "Unknown")
        player_damage_taken.setdefault(player, {})
        player_damage_taken[player][source] = player_damage_taken[player].get(source, 0) + 1
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
            "spell": ev.get("ability", {}).get("name", "Unknown"),
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
        "encounter_id": fight.get("encounterID"),
        "boss_name": fight["name"],
        "duration_sec": duration_sec,
        "kill": bool(fight.get("kill")),
        "deaths": deaths_out,
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
        "buff_events": buff_events,
        "threat_events": threat_events,
        "clutch_heals": clutch_heals[:10],
        "biggest_heals": biggest_heals[:5],
        "biggest_crits": biggest_crits[:5],
        "players": participants,
    }
