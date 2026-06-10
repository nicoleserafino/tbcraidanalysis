#!/usr/bin/env python3
"""Fetch Warcraft Logs v1 raid data and build the frontend report payload."""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

API_BASE = "https://fresh.warcraftlogs.com/v1"
REQUEST_DELAY_SEC = 0.5
CONFLAGRATION_SPELL_ID = 37018
PLAYER_CLASSES = {
    "Warrior",
    "Paladin",
    "Hunter",
    "Rogue",
    "Priest",
    "Shaman",
    "Mage",
    "Warlock",
    "Druid",
}
TANK_SPELLS = {
    "Shield Slam",
    "Devastate",
    "Revenge",
    "Shield Block",
    "Taunt",
    "Thunder Clap",
    "Holy Shield",
    "Righteous Defense",
    "Avenger's Shield",
    "Maul",
    "Lacerate",
    "Mangle (Bear)",
    "Swipe",
    "Growl",
    "Challenging Roar",
}
HEAL_SPELLS = {
    "Flash of Light",
    "Holy Light",
    "Flash Heal",
    "Greater Heal",
    "Prayer of Healing",
    "Prayer of Mending",
    "Circle of Healing",
    "Chain Heal",
    "Healing Wave",
    "Lesser Healing Wave",
    "Rejuvenation",
    "Lifebloom",
    "Regrowth",
    "Swiftmend",
    "Earth Shield",
    "Binding Heal",
    "Renew",
}
DPS_SPELLS = {
    "Fireball",
    "Frostbolt",
    "Arcane Blast",
    "Arcane Missiles",
    "Shadow Bolt",
    "Incinerate",
    "Seed of Corruption",
    "Corruption",
    "Mind Blast",
    "Shadow Word: Pain",
    "Mind Flay",
    "Vampiric Touch",
    "Sinister Strike",
    "Backstab",
    "Eviscerate",
    "Slice and Dice",
    "Steady Shot",
    "Arcane Shot",
    "Multi-Shot",
    "Kill Command",
    "Lightning Bolt",
    "Chain Lightning",
    "Earth Shock",
    "Flame Shock",
    "Stormstrike",
    "Wrath",
    "Starfire",
    "Moonfire",
    "Mortal Strike",
    "Bloodthirst",
    "Whirlwind",
    "Slam",
    "Crusader Strike",
    "Judgement of Blood",
    "Judgement of the Crusader",
    "Judgement of Righteousness",
    "Seal of Blood",
    "Seal of Command",
    "Heroic Strike",
    "Execute",
    "Shred",
    "Ferocious Bite",
    "Rip",
    "Mangle (Cat)",
}


class WCLClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _request(self, path: str, **params: Any) -> dict[str, Any]:
        query = {"api_key": self.api_key, **params}
        url = f"{API_BASE}{path}?{urlencode(query)}"
        request = Request(url, headers={"User-Agent": "kael-analysis/1.0"})
        with urlopen(request, timeout=120) as response:
            payload = json.load(response)
        time.sleep(REQUEST_DELAY_SEC)
        return payload

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self._request(path, **params)

    def get_paginated_events(self, event_type: str, report_id: str, *, start: int, end: int, **params: Any) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        seen: set[str] = set()
        next_start = start
        page = 1
        while True:
            payload = self._request(f"/report/events/{event_type}/{report_id}", start=next_start, end=end, **params)
            page_events = payload.get("events", [])
            added = 0
            for event in page_events:
                marker = json.dumps(event, sort_keys=True, separators=(",", ":"))
                if marker in seen:
                    continue
                seen.add(marker)
                events.append(event)
                added += 1
            print(f"      {event_type}: page {page}, {added} events")
            next_page = payload.get("nextPageTimestamp")
            if not next_page or next_page >= end or next_page == next_start:
                break
            next_start = next_page
            page += 1
        return events


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_api_key(root: Path) -> str:
    env_path = root / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f"Missing .env at {env_path}")
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("API_KEY="):
            return line.split("=", 1)[1].strip()
    raise ValueError("API_KEY not found in .env")


def extract_report_id(url: str) -> str:
    match = re.search(r"/reports/([A-Za-z0-9]+)", url)
    if match:
        return match.group(1)
    parsed = urlparse(url)
    candidate = parsed.path.strip("/")
    if re.fullmatch(r"[A-Za-z0-9]+", candidate):
        return candidate
    raise ValueError(f"Could not extract report ID from {url}")


def format_timestamp(report_start_ms: int, offset_ms: int) -> str:
    dt = datetime.fromtimestamp((report_start_ms + offset_ms) / 1000)
    return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def relative_seconds(start_ms: int, timestamp_ms: int) -> float:
    return round((timestamp_ms - start_ms) / 1000, 1)


def actor_name(actor: dict[str, Any] | None, actor_id: int | None, actors_by_id: dict[int, dict[str, Any]]) -> str:
    if actor and actor.get("name"):
        return actor["name"]
    if actor_id is not None and actor_id in actors_by_id:
        return actors_by_id[actor_id].get("name", f"ID {actor_id}")
    if actor_id == -1:
        return "Environment"
    return f"ID {actor_id}" if actor_id is not None else "Unknown"


def is_player_actor(actor: dict[str, Any] | None) -> bool:
    return bool(actor and actor.get("type") in PLAYER_CLASSES)


def role_from_icon(player_class: str, icon: str | None) -> str | None:
    icon = icon or ""
    if "-Holy" in icon or "-Restoration" in icon or "-Discipline" in icon:
        return "Healer"
    if "-Protection" in icon or "-Guardian" in icon:
        return "Tank"
    dps_specs = ("-Shadow", "-Balance", "-Feral", "-Enhancement", "-Elemental", "-Retribution",
                 "-Arms", "-Fury", "-Combat", "-Assassination", "-Subtlety", "-Frost", "-Fire",
                 "-Arcane", "-Marksmanship", "-BeastMastery", "-Survival", "-Affliction",
                 "-Demonology", "-Destruction")
    if any(spec in icon for spec in dps_specs):
        return "DPS"
    if player_class in {"Mage", "Warlock", "Rogue", "Hunter"}:
        return "DPS"
    return None


def infer_role(player_class: str, icon: str | None, spell_counts: dict[str, int], total_healing: int, total_damage_taken: int, total_damage_done: int) -> str:
    icon_role = role_from_icon(player_class, icon)
    if icon_role:
        return icon_role
    tank_score = sum(count for spell, count in spell_counts.items() if spell in TANK_SPELLS)
    heal_score = sum(count for spell, count in spell_counts.items() if spell in HEAL_SPELLS)
    dps_score = sum(count for spell, count in spell_counts.items() if spell in DPS_SPELLS)
    if player_class in {"Warrior", "Paladin", "Druid"} and tank_score > 20 and total_damage_taken > total_damage_done:
        return "Tank"
    if player_class in {"Paladin", "Priest", "Shaman", "Druid"} and total_healing > total_damage_done * 3:
        return "Healer"
    if player_class in {"Warrior", "Paladin", "Druid"} and total_damage_taken > total_damage_done * 3 and total_damage_taken > 50000:
        return "Tank"
    return "DPS"


def pull_participants(friendlies: list[dict[str, Any]], fight_id: int) -> list[dict[str, Any]]:
    output = []
    for friendly in friendlies:
        if friendly.get("type") not in PLAYER_CLASSES:
            continue
        fight_ids = {fight.get("id") for fight in friendly.get("fights", [])}
        if fight_id in fight_ids:
            output.append(friendly)
    return sorted(output, key=lambda item: item["name"])


def build_actor_maps(fights_payload: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], list[dict[str, Any]]]:
    actors_by_id: dict[int, dict[str, Any]] = {}
    players_by_id: dict[int, dict[str, Any]] = {}
    all_friendlies = fights_payload.get("friendlies", []) + fights_payload.get("friendlyPets", [])
    all_enemies = fights_payload.get("enemies", []) + fights_payload.get("enemyPets", [])
    for actor in all_friendlies + all_enemies:
        actor_id = actor.get("id")
        if actor_id is None:
            continue
        actors_by_id[actor_id] = actor
        if actor.get("type") in PLAYER_CLASSES:
            players_by_id[actor_id] = actor
    friendlies = [actor for actor in fights_payload.get("friendlies", []) if actor.get("type") in PLAYER_CLASSES]
    return actors_by_id, players_by_id, friendlies


def analyze_pull(
    client: WCLClient,
    report_id: str,
    report_start_ms: int,
    fight: dict[str, Any],
    actors_by_id: dict[int, dict[str, Any]],
    players_by_id: dict[int, dict[str, Any]],
    friendlies: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    start = fight["start_time"]
    end = fight["end_time"]
    print(f"  Pull {fight['id']}: {fight['name']} ({round((end - start) / 1000, 1)}s)")

    damage_done_table = client.get(f"/report/tables/damage-done/{report_id}", start=start, end=end)
    deaths = client.get_paginated_events("deaths", report_id, start=start, end=end)
    enemy_deaths = client.get_paginated_events("deaths", report_id, start=start, end=end, hostility=1)
    interrupts = client.get_paginated_events("interrupts", report_id, start=start, end=end)
    dispels = client.get_paginated_events("dispels", report_id, start=start, end=end)
    healing = client.get_paginated_events("healing", report_id, start=start, end=end)
    casts = client.get_paginated_events("casts", report_id, start=start, end=end)
    damage_taken = client.get_paginated_events("damage-taken", report_id, start=start, end=end)
    buff_events = client.get_paginated_events("buffs", report_id, start=start, end=end)
    conflagration_events = client.get_paginated_events(
        "damage-taken",
        report_id,
        start=start,
        end=end,
        filter=f"ability.id={CONFLAGRATION_SPELL_ID}",
    )

    participants = pull_participants(friendlies, fight["id"])
    pull_player_names = [item["name"] for item in participants]

    damage_sources: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    damage_abilities: dict[str, int] = defaultdict(int)
    player_damage_taken: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    heals_by_player: dict[str, int] = defaultdict(int)
    heal_details: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {"total": 0, "overheal": 0, "count": 0, "is_hot": False}))
    casts_by_player: dict[str, int] = defaultdict(int)
    cast_timeline: dict[str, list[float]] = defaultdict(list)
    spell_casts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    damage_done: dict[str, dict[str, int]] = defaultdict(dict)
    deaths_out: list[dict[str, Any]] = []
    creature_deaths: list[dict[str, Any]] = []
    interrupts_out: list[dict[str, Any]] = []
    dispels_out: list[dict[str, Any]] = []
    conflagrations: list[dict[str, Any]] = []

    for event in deaths:
        if event.get("type") != "death":
            continue
        ts = event["timestamp"]
        target_id = event.get("targetID")
        if not event.get("targetIsFriendly") or target_id not in players_by_id:
            continue
        deaths_out.append(
            {
                "time": format_timestamp(report_start_ms, ts),
                "relative_time": relative_seconds(start, ts),
                "player": players_by_id[target_id]["name"],
            }
        )

    for event in enemy_deaths:
        if event.get("type") != "death":
            continue
        ts = event["timestamp"]
        target_id = event.get("targetID")
        if event.get("targetIsFriendly") or target_id is None:
            continue
        creature_deaths.append(
            {
                "time": format_timestamp(report_start_ms, ts),
                "relative_time": relative_seconds(start, ts),
                "name": actor_name(event.get("target"), target_id, actors_by_id),
            }
        )

    for event in damage_taken:
        if event.get("type") != "damage":
            continue
        target_id = event.get("targetID")
        source_id = event.get("sourceID")
        if not event.get("targetIsFriendly") or target_id not in players_by_id:
            continue
        source = actor_name(event.get("source"), source_id, actors_by_id)
        target = players_by_id[target_id]["name"]
        ability = event.get("ability", {}).get("name") or "Unknown"
        damage_sources[source][target] += 1
        damage_abilities[ability] += 1
        player_damage_taken[target][f"{source}: {ability}"] += 1

    seen_conflag_keys: set[tuple[int, str]] = set()
    last_conflag_by_target: dict[str, int] = {}
    for event in sorted(conflagration_events, key=lambda item: (item.get("timestamp", 0), item.get("targetID", -1))):
        if event.get("type") != "damage":
            continue
        target_id = event.get("targetID")
        if not event.get("targetIsFriendly") or target_id not in players_by_id:
            continue
        target = players_by_id[target_id]["name"]
        ts = event["timestamp"]
        last_ts = last_conflag_by_target.get(target)
        if last_ts is not None and ts - last_ts <= 5000:
            continue
        key = (round((ts - start) / 1000), target)
        if key in seen_conflag_keys:
            continue
        seen_conflag_keys.add(key)
        last_conflag_by_target[target] = ts
        conflagrations.append(
            {
                "time": format_timestamp(report_start_ms, ts),
                "relative_time": relative_seconds(start, ts),
                "target": target,
            }
        )

    for event in interrupts:
        if event.get("type") != "interrupt" or not event.get("sourceIsFriendly"):
            continue
        ts = event["timestamp"]
        source = actor_name(event.get("source"), event.get("sourceID"), actors_by_id)
        target = actor_name(event.get("target"), event.get("targetID"), actors_by_id)
        interrupts_out.append(
            {
                "time": format_timestamp(report_start_ms, ts),
                "relative_time": relative_seconds(start, ts),
                "source": source,
                "target": target,
            }
        )

    for event in dispels:
        if event.get("type") != "dispel" or not event.get("sourceIsFriendly"):
            continue
        ts = event["timestamp"]
        source = actor_name(event.get("source"), event.get("sourceID"), actors_by_id)
        dispels_out.append(
            {
                "time": format_timestamp(report_start_ms, ts),
                "relative_time": relative_seconds(start, ts),
                "source": source,
            }
        )

    for event in healing:
        if event.get("type") != "heal" or not event.get("sourceIsFriendly"):
            continue
        source_id = event.get("sourceID")
        if source_id not in players_by_id:
            continue
        player = players_by_id[source_id]["name"]
        spell = event.get("ability", {}).get("name") or "Unknown"
        heals_by_player[player] += 1
        info = heal_details[player][spell]
        info["total"] += int(event.get("amount") or 0)
        info["overheal"] += int(event.get("overheal") or 0)
        info["count"] += 1
        info["is_hot"] = info["is_hot"] or bool(event.get("tick"))

    for event in casts:
        if event.get("type") != "cast" or not event.get("sourceIsFriendly"):
            continue
        source_id = event.get("sourceID")
        if source_id not in players_by_id:
            continue
        player = players_by_id[source_id]["name"]
        spell = event.get("ability", {}).get("name") or "Unknown"
        casts_by_player[player] += 1
        cast_timeline[player].append(relative_seconds(start, event["timestamp"]))
        spell_casts[player][spell] += 1

    for entry in damage_done_table.get("entries", []):
        player_id = entry.get("id")
        if player_id not in players_by_id:
            continue
        player = players_by_id[player_id]["name"]
        for ability in entry.get("abilities", []):
            spell = ability.get("name") or "Unknown"
            if spell == "Melee":
                spell = "Melee (Auto Attack)"
            damage_done[player][spell] = int(ability.get("total") or 0)

    # Process buff events (applybuff, removebuff, refreshbuff)
    player_buff_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in buff_events:
        event_type = event.get("type", "")
        if event_type not in ("applybuff", "removebuff", "refreshbuff", "applydebuff", "removedebuff"):
            continue
        target_id = event.get("targetID")
        if target_id not in players_by_id:
            continue
        player = players_by_id[target_id]["name"]
        spell = event.get("ability", {}).get("name") or "Unknown"
        player_buff_events[player].append({
            "spell": spell,
            "type": event_type,
            "time": relative_seconds(start, event["timestamp"]),
        })

    pull = {
        "encounter_id": fight["boss"],
        "boss_name": fight["name"],
        "start_time": format_timestamp(report_start_ms, start),
        "end_time": format_timestamp(report_start_ms, end),
        "duration_sec": round((end - start) / 1000, 3),
        "kill": bool(fight.get("kill")),
        "deaths": deaths_out,
        "damage_sources": {source: dict(targets) for source, targets in sorted(damage_sources.items())},
        "damage_abilities": dict(sorted(damage_abilities.items())),
        "player_damage_taken": {player: dict(sources) for player, sources in sorted(player_damage_taken.items())},
        "player_positions": {},
        "creature_deaths": creature_deaths,
        "interrupts": interrupts_out,
        "dispels": dispels_out,
        "conflagrations": conflagrations,
        "players": pull_player_names,
        "heals_by_player": dict(sorted(heals_by_player.items())),
        "heal_details": {player: dict(sorted(spells.items())) for player, spells in sorted(heal_details.items())},
        "casts_by_player": dict(sorted(casts_by_player.items())),
        "cast_timeline": {player: times for player, times in sorted(cast_timeline.items())},
        "spell_casts": {player: dict(sorted(spells.items())) for player, spells in sorted(spell_casts.items())},
        "damage_done": {player: dict(sorted(spells.items())) for player, spells in sorted(damage_done.items())},
        "buff_events": {player: events for player, events in sorted(player_buff_events.items())},
        "consumables": {},
    }

    summary = {
        "spell_casts": {player: dict(spells) for player, spells in spell_casts.items()},
        "total_healing": {player: sum(info["total"] for info in spells.values()) for player, spells in heal_details.items()},
        "total_damage_done": {player: sum(spells.values()) for player, spells in damage_done.items()},
        "total_damage_taken": {player: sum(sources.values()) for player, sources in player_damage_taken.items()},
    }
    return pull, summary


def rebuild_index_html(index_path: Path, report: dict[str, Any]) -> None:
    html = index_path.read_text()
    replacement = "<script>window.__REPORT_DATA__ = " + json.dumps(report, indent=2) + ";</script>"
    updated, count = re.subn(
        r"<script>window\.__REPORT_DATA__ = .*?;</script>",
        replacement,
        html,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("Could not find embedded report block in index.html")
    index_path.write_text(updated)


def generate_report(report_url: str) -> dict[str, Any]:
    root = project_root()
    api_key = load_api_key(root)
    report_id = extract_report_id(report_url)
    client = WCLClient(api_key)

    print(f"Fetching report metadata for {report_id}...")
    fights_payload = client.get(f"/report/fights/{report_id}")
    fights = [fight for fight in fights_payload.get("fights", []) if fight.get("boss", 0) > 0]
    actors_by_id, players_by_id, friendlies = build_actor_maps(fights_payload)
    report_start_ms = int(fights_payload["start"])

    bosses: dict[str, dict[str, Any]] = {}
    aggregate_spell_casts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    aggregate_healing: dict[str, int] = defaultdict(int)
    aggregate_damage_done: dict[str, int] = defaultdict(int)
    aggregate_damage_taken: dict[str, int] = defaultdict(int)
    pull_summaries: list[dict[str, Any]] = []

    for fight in fights:
        pull, summary = analyze_pull(client, report_id, report_start_ms, fight, actors_by_id, players_by_id, friendlies)
        summary["players"] = pull["players"]
        pull_summaries.append(summary)
        for player, spells in summary["spell_casts"].items():
            for spell, count in spells.items():
                aggregate_spell_casts[player][spell] += count
        for player, total in summary["total_healing"].items():
            aggregate_healing[player] += total
        for player, total in summary["total_damage_done"].items():
            aggregate_damage_done[player] += total
        for player, total in summary["total_damage_taken"].items():
            aggregate_damage_taken[player] += total
        boss_entry = bosses.setdefault(
            fight["name"],
            {"total_pulls": 0, "kills": 0, "wipes": 0, "pulls": []},
        )
        boss_entry["pulls"].append(pull)
        boss_entry["total_pulls"] += 1
        if pull["kill"]:
            boss_entry["kills"] += 1
        else:
            boss_entry["wipes"] += 1

    # Build a lookup of class/icon per player from friendlies
    friendly_info: dict[str, dict[str, str]] = {}
    for friendly in sorted(friendlies, key=lambda item: item["name"]):
        name = friendly["name"]
        friendly_info[name] = {
            "class": friendly.get("type", "Unknown"),
            "icon": friendly.get("icon"),
        }

    # Infer roles per pull so spec swaps between pulls are detected
    per_pull_roles: list[dict[str, str]] = []
    for pull_summary in pull_summaries:
        pull_roles: dict[str, str] = {}
        for player_name in pull_summary["players"]:
            info = friendly_info.get(player_name)
            if not info:
                continue
            pull_roles[player_name] = infer_role(
                info["class"],
                info.get("icon"),
                dict(pull_summary["spell_casts"].get(player_name, {})),
                pull_summary["total_healing"].get(player_name, 0),
                pull_summary["total_damage_taken"].get(player_name, 0),
                pull_summary["total_damage_done"].get(player_name, 0),
            )
        per_pull_roles.append(pull_roles)

    # Assign per-pull roles to each pull and determine primary (most common) role per player
    player_role_counts: dict[str, Counter] = defaultdict(Counter)
    pull_idx = 0
    for boss_entry in bosses.values():
        for pull in boss_entry["pulls"]:
            roles = per_pull_roles[pull_idx]
            pull["roles"] = roles
            for player_name, role in roles.items():
                player_role_counts[player_name][role] += 1
            pull_idx += 1

    # Global players dict uses most-common role as fallback
    players: dict[str, dict[str, str]] = {}
    for name, info in friendly_info.items():
        if player_role_counts[name]:
            primary_role = player_role_counts[name].most_common(1)[0][0]
        else:
            primary_role = infer_role(
                info["class"],
                info.get("icon"),
                dict(aggregate_spell_casts.get(name, {})),
                aggregate_healing.get(name, 0),
                aggregate_damage_taken.get(name, 0),
                aggregate_damage_done.get(name, 0),
            )
        players[name] = {
            "role": primary_role,
            "class": info["class"],
        }

    return {
        "log_info": {
            "file": report_url,
            "total_lines": 0,
            "total_encounters": len(fights),
            "report_id": report_id,
            "title": fights_payload.get("title", ""),
        },
        "players": players,
        "bosses": bosses,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/fetch_from_api.py <warcraftlogs_report_url>")
        return 1

    report_url = sys.argv[1]
    root = project_root()
    report = generate_report(report_url)

    report_path = root / "data" / "report.json"
    index_path = root / "index.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Writing {report_path}...")
    report_path.write_text(json.dumps(report, indent=2))
    print(f"Rebuilding {index_path}...")
    rebuild_index_html(index_path, report)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
