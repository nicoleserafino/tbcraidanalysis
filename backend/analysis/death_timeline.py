"""Per-death forensic timeline: what killed a player and who was (or wasn't) healing them.

For every player death this reconstructs the final seconds leading up to it:

  * every point of **damage taken** — ability, the source that dealt it, and amount,
  * every **heal received** — spell, the healer who cast it, effective amount, overheal
    and the target's HP% right after the heal (from ``includeResources`` healing events).

The goal is to answer, at a glance, "at the moment they died, what was hitting them,
how hard, and what healing (and from whom) did they get?" — most useful for tanks, but
computed for every player death. This is intentionally role-independent so it can be
built inside :func:`build_pull_data` alongside the other per-pull data.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

# How far back from the moment of death to reconstruct (ms).
_WINDOW_MS = 10000
# Cap the raw event lists per death so the payload stays reasonable on heavy melee
# tanks; aggregates (totals / by-source / by-healer) always use every event in window.
_MAX_EVENTS = 80

MELEE_ABILITY = "Melee"


def _abil(ev: dict, ability_names: dict) -> str:
    aid = ev.get("abilityGameID")
    if aid in (0, 1, None):
        aid = (ev.get("ability") or {}).get("guid")
    if aid in (0, 1, None):
        return MELEE_ABILITY
    return ability_names.get(aid, f"#{aid}")


def _damage_label(ability: str, source_name: str) -> str:
    """Match the labeling used elsewhere: ``Ability (Source NPC)`` when informative."""
    if source_name and source_name.lower() != ability.lower():
        return f"{ability} ({source_name})"
    return ability


def build_death_timelines(
    fight: dict,
    actors_by_id: dict,
    players_by_id: dict,
    ability_names: dict,
    deaths: list,
    damage_taken: list,
    healing: list,
) -> list[dict[str, Any]]:
    """Build a forensic timeline for each player death.

    Returns one dict per player death (chronological), each describing the damage
    taken and healing received in the ``_WINDOW_MS`` before that death.
    """
    start = fight["startTime"]

    def rel_sec(ts: int) -> float:
        return round((ts - start) / 1000, 1)

    player_deaths = [
        ev for ev in deaths
        if ev.get("type") == "death" and ev.get("targetID") in players_by_id
    ]
    if not player_deaths:
        return []

    # Index damage-taken and healing events by target player for windowed lookups.
    dmg_by_target: dict[int, list] = defaultdict(list)
    for ev in damage_taken:
        if ev.get("type") != "damage":
            continue
        tid = ev.get("targetID")
        if tid not in players_by_id:
            continue
        dmg_by_target[tid].append(ev)

    heal_by_target: dict[int, list] = defaultdict(list)
    for ev in healing:
        if ev.get("type") != "heal":
            continue
        tid = ev.get("targetID")
        if tid not in players_by_id:
            continue
        heal_by_target[tid].append(ev)

    def sname(sid):
        if sid is None:
            return ""
        return actors_by_id.get(sid, {}).get("name", "")

    timelines = []
    for dev in player_deaths:
        tid = dev["targetID"]
        death_ts = dev["timestamp"]
        lo = death_ts - _WINDOW_MS

        # --- damage taken in window -----------------------------------------
        dmg_events = []
        dmg_by_source: dict[str, dict] = defaultdict(lambda: {"amount": 0, "count": 0})
        dmg_total = 0
        biggest_hit = None
        for ev in dmg_by_target.get(tid, []):
            ts = ev["timestamp"]
            if not (lo <= ts <= death_ts):
                continue
            amount = ev.get("amount", 0) + ev.get("absorbed", 0)
            source_id = ev.get("sourceID")
            source_npc = ""
            if source_id and source_id not in players_by_id:
                source_npc = sname(source_id)
            ability = _abil(ev, ability_names)
            label = _damage_label(ability, source_npc)
            entry = {
                "t": rel_sec(ts),
                "dt_ms": death_ts - ts,
                "ability": label,
                "source": source_npc or sname(source_id),
                "amount": amount,
                "mitigated": ev.get("mitigated", 0),
                "overkill": ev.get("overkill", 0),
            }
            dmg_events.append(entry)
            agg = dmg_by_source[label]
            agg["amount"] += amount
            agg["count"] += 1
            dmg_total += amount
            if biggest_hit is None or amount > biggest_hit["amount"]:
                biggest_hit = {"ability": label, "source": entry["source"], "amount": amount, "t": entry["t"]}

        # --- healing received in window -------------------------------------
        heal_events = []
        heal_by_healer: dict[str, dict] = defaultdict(lambda: {"amount": 0, "overheal": 0, "count": 0})
        heal_total = 0
        overheal_total = 0
        for ev in heal_by_target.get(tid, []):
            ts = ev["timestamp"]
            if not (lo <= ts <= death_ts):
                continue
            amount = ev.get("amount", 0)
            overheal = ev.get("overheal", 0)
            source_id = ev.get("sourceID")
            healer = sname(source_id) if source_id in players_by_id else (sname(source_id) or "Unknown")
            spell = _abil(ev, ability_names)
            hp_after = ev.get("hitPoints")
            entry = {
                "t": rel_sec(ts),
                "dt_ms": death_ts - ts,
                "spell": spell,
                "healer": healer,
                "amount": amount,
                "overheal": overheal,
                "hp_after": round(hp_after, 1) if isinstance(hp_after, (int, float)) else None,
                "is_hot": bool(ev.get("tick")),
                "self_heal": source_id == tid,
            }
            heal_events.append(entry)
            agg = heal_by_healer[healer]
            agg["amount"] += amount
            agg["overheal"] += overheal
            agg["count"] += 1
            heal_total += amount
            overheal_total += overheal

        # Chronological, oldest first, so reading top->bottom leads up to the death.
        # Sorting by descending dt_ms also means [-_MAX_EVENTS:] keeps the events
        # closest to death when a heavy-melee window has to be trimmed.
        dmg_events.sort(key=lambda x: -x["dt_ms"])
        heal_events.sort(key=lambda x: -x["dt_ms"])

        killing_ability = ""
        if dev.get("killingAbility"):
            killing_ability = dev["killingAbility"].get("name", "") or ability_names.get(
                (dev.get("killingAbility") or {}).get("guid", 0), ""
            )
        elif dev.get("ability"):
            killing_ability = dev["ability"].get("name", "") or ability_names.get(
                (dev.get("ability") or {}).get("guid", 0), ""
            )

        timelines.append({
            "player": players_by_id[tid]["name"],
            "player_class": players_by_id[tid].get("subType", ""),
            "relative_time": rel_sec(death_ts),
            "window_sec": _WINDOW_MS / 1000,
            "killing_blow": killing_ability,
            "damage_taken_total": dmg_total,
            "healing_received_total": heal_total,
            "overhealing_total": overheal_total,
            "biggest_hit": biggest_hit,
            "damage_by_source": sorted(
                ({"label": k, **v} for k, v in dmg_by_source.items()),
                key=lambda x: -x["amount"],
            ),
            "healing_by_healer": sorted(
                ({"healer": k, **v} for k, v in heal_by_healer.items()),
                key=lambda x: -x["amount"],
            ),
            # Keep the most recent events (closest to death) if we have to trim.
            "damage_events": dmg_events[-_MAX_EVENTS:],
            "healing_events": heal_events[-_MAX_EVENTS:],
        })

    timelines.sort(key=lambda x: x["relative_time"])
    return timelines
