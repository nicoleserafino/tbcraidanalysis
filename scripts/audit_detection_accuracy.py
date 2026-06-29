from __future__ import annotations

import asyncio
import io
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.analysis.guild import (
    BATTLE_ELIXIRS,
    CHEAP_ENCHANT_NAMES,
    CHEAP_ENCHANTS,
    CHEAP_SHOULDER_ENCHANTS,
    ENCHANTABLE_SLOTS,
    FLASK_BUFFS,
    FOOD_BUFFS,
    GUARDIAN_ELIXIRS,
    TEMP_ENCHANT_NAMES,
    UNCOMMON_GEM_IDS,
    _audit_consumables,
    _audit_gear,
    fetch_guild_reports,
)
from backend.analysis.report import fetch_events_paginated, fetch_report_metadata
from backend.analysis.utils import infer_role, spell_name

GUILD_ID = 821862
GUILD_NAME = "Lower City Discotek"
SERVER_NAME = "Dreamscythe"
OUTPUT_DIR = Path("data/audits")

FULL_SLOT_NAMES = {
    0: "Head",
    1: "Neck",
    2: "Shoulder",
    3: "Shirt",
    4: "Chest",
    5: "Waist",
    6: "Legs",
    7: "Feet",
    8: "Wrist",
    9: "Hands",
    10: "Finger 1",
    11: "Finger 2",
    12: "Trinket 1",
    13: "Trinket 2",
    14: "Back",
    15: "Main Hand",
    16: "Off Hand",
    17: "Ranged",
}

DRUMS_RE = re.compile(r"Drums of (Battle|War|Restoration|Speed)", re.I)
HEALTHSTONE_RE = re.compile(r"Healthstone", re.I)
RUNE_RE = re.compile(r"Dark Rune|Demonic Rune", re.I)
POTION_RE = re.compile(
    r"Super Mana Potion|Destruction Potion|Haste Potion|Ironshield Potion|Super Healing Potion",
    re.I,
)
CONSUMABLE_CANDIDATE_RE = re.compile(
    r"drums|healthstone|rune|potion|flask|elixir|well fed|oil|stone|poison|cap",
    re.I,
)


def slot_label(slot_idx: int) -> str:
    actual = FULL_SLOT_NAMES.get(slot_idx, f"Slot {slot_idx}")
    configured = ENCHANTABLE_SLOTS.get(slot_idx)
    if configured:
        return f"{slot_idx} ({actual}; configured={configured})"
    return f"{slot_idx} ({actual})"


def simplify_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {
        "id": item.get("id"),
        "itemLevel": item.get("itemLevel"),
        "permanentEnchant": item.get("permanentEnchant", 0),
        "temporaryEnchant": item.get("temporaryEnchant", 0),
        "gems": [gem.get("id") for gem in item.get("gems", []) if gem and gem.get("id")],
    }


async def build_role_map(
    report_code: str,
    fight: dict[str, Any],
    players_by_id: dict[int, dict[str, Any]],
    ability_names: dict[int, str],
) -> dict[int, str]:
    start = int(fight["startTime"])
    end = int(fight["endTime"])
    fight_id = int(fight["id"])
    casts, healing, damage_done, damage_taken = await asyncio.gather(
        fetch_events_paginated(report_code, [fight_id], "Casts", start, end),
        fetch_events_paginated(report_code, [fight_id], "Healing", start, end),
        fetch_events_paginated(report_code, [fight_id], "DamageDone", start, end),
        fetch_events_paginated(report_code, [fight_id], "DamageTaken", start, end),
    )

    spell_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_healing: dict[int, int] = defaultdict(int)
    total_damage_done: dict[int, int] = defaultdict(int)
    total_damage_taken: dict[int, int] = defaultdict(int)

    for ev in casts:
        if ev.get("type") != "cast":
            continue
        source_id = ev.get("sourceID")
        if source_id not in players_by_id:
            continue
        spell_counts[source_id][spell_name(ev, ability_names)] += 1

    for ev in healing:
        if ev.get("type") != "heal":
            continue
        source_id = ev.get("sourceID")
        if source_id not in players_by_id:
            continue
        total_healing[source_id] += int(ev.get("amount", 0) or 0)

    for ev in damage_done:
        if ev.get("type") != "damage":
            continue
        source_id = ev.get("sourceID")
        if source_id not in players_by_id:
            continue
        total_damage_done[source_id] += int(ev.get("amount", 0) or 0)

    for ev in damage_taken:
        if ev.get("type") != "damage":
            continue
        target_id = ev.get("targetID")
        if target_id not in players_by_id:
            continue
        total_damage_taken[target_id] += int(ev.get("amount", 0) or 0) + int(ev.get("absorbed", 0) or 0)

    roles = {}
    for player_id, actor in players_by_id.items():
        roles[player_id] = infer_role(
            actor.get("subType", ""),
            spell_counts={k: int(v) for k, v in spell_counts[player_id].items()},
            total_healing=int(total_healing[player_id]),
            total_damage_done=int(total_damage_done[player_id]),
            total_damage_taken=int(total_damage_taken[player_id]),
        )
    return roles


def classify_spell_casts(
    cast_events: list[dict[str, Any]],
    players_by_id: dict[int, dict[str, Any]],
    ability_names: dict[int, str],
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, dict[str, int]]], dict[str, list[str]], dict[str, list[str]]]:
    spell_casts: dict[str, dict[str, int]] = {}
    matches: dict[str, dict[str, dict[str, int]]] = {}
    candidates: dict[str, list[str]] = defaultdict(list)
    unmatched_candidates: dict[str, list[str]] = defaultdict(list)

    for ev in cast_events:
        if ev.get("type") != "cast":
            continue
        source_id = ev.get("sourceID")
        if source_id not in players_by_id:
            continue
        player = players_by_id[source_id]["name"]
        spell = spell_name(ev, ability_names)
        spell_casts.setdefault(player, {})
        spell_casts[player][spell] = spell_casts[player].get(spell, 0) + 1

    for player, spells in spell_casts.items():
        matches[player] = {"drums": {}, "healthstone": {}, "dark_rune": {}, "potion": {}}
        for spell, count in sorted(spells.items()):
            is_candidate = bool(CONSUMABLE_CANDIDATE_RE.search(spell))
            matched = False
            if DRUMS_RE.search(spell):
                matches[player]["drums"][spell] = count
                matched = True
            if HEALTHSTONE_RE.search(spell):
                matches[player]["healthstone"][spell] = count
                matched = True
            if RUNE_RE.search(spell):
                matches[player]["dark_rune"][spell] = count
                matched = True
            if POTION_RE.search(spell):
                matches[player]["potion"][spell] = count
                matched = True
            if is_candidate:
                candidates[player].append(spell)
                if not matched:
                    unmatched_candidates[player].append(spell)

    return spell_casts, matches, candidates, unmatched_candidates


async def audit() -> dict[str, Path]:
    reports = await fetch_guild_reports(GUILD_ID, limit=1, page=1)
    if not reports.get("reports"):
        raise RuntimeError(f"No reports found for guild {GUILD_ID}")

    report = reports["reports"][0]
    report_code = report["code"]
    metadata = await fetch_report_metadata(report_code)
    fights = metadata.get("fights", []) or []
    boss_fights = [fight for fight in fights if int(fight.get("encounterID", 0) or 0) > 0]
    if not boss_fights:
        raise RuntimeError(f"Report {report_code} has no boss fights")
    fight = boss_fights[0]

    actors = metadata.get("masterData", {}).get("actors", []) or []
    abilities = metadata.get("masterData", {}).get("abilities", []) or []
    ability_names = {a["gameID"]: a["name"] for a in abilities if a.get("gameID")}
    players_by_id = {
        int(actor["id"]): actor
        for actor in actors
        if actor.get("type") == "Player" and actor.get("id") is not None
    }

    start = int(fight["startTime"])
    end = int(fight["endTime"])
    fight_id = int(fight["id"])

    combatant_info_events, cast_events, role_by_id = await asyncio.gather(
        fetch_events_paginated(report_code, [fight_id], "CombatantInfo", start, end),
        fetch_events_paginated(report_code, [fight_id], "Casts", start, end),
        build_role_map(report_code, fight, players_by_id, ability_names),
    )

    ci_players = [
        ev for ev in combatant_info_events
        if ev.get("sourceID") in players_by_id
    ]
    ci_players.sort(key=lambda ev: players_by_id[ev["sourceID"]]["name"])

    spell_casts, spell_matches, spell_candidates, spell_unmatched_candidates = classify_spell_casts(
        cast_events,
        players_by_id,
        ability_names,
    )

    output = io.StringIO()

    def p(*args: Any, **kwargs: Any) -> None:
        print(*args, **kwargs, file=output)

    p("=" * 100)
    p("DETECTION / CLASSIFICATION ACCURACY AUDIT")
    p("=" * 100)
    p(f"Guild: {GUILD_NAME} ({GUILD_ID})")
    p(f"Server: {SERVER_NAME}")
    p(f"Report code: {report_code}")
    p(f"Fight: {fight['name']} (fight_id={fight_id}, encounterID={fight.get('encounterID')})")
    p(f"Players with CombatantInfo: {len(ci_players)}")
    p()
    p("Current backend constants:")
    p(f"  ENCHANTABLE_SLOTS={ENCHANTABLE_SLOTS}")
    p(f"  CHEAP_ENCHANTS={CHEAP_ENCHANTS}")
    p(f"  CHEAP_ENCHANT_NAMES={CHEAP_ENCHANT_NAMES}")
    p(f"  CHEAP_SHOULDER_ENCHANTS={CHEAP_SHOULDER_ENCHANTS}")
    p(f"  UNCOMMON_GEM_IDS={sorted(UNCOMMON_GEM_IDS)}")
    p(f"  TEMP_ENCHANT_NAMES={TEMP_ENCHANT_NAMES}")
    p(f"  FLASK_BUFFS={sorted(FLASK_BUFFS)}")
    p(f"  BATTLE_ELIXIRS={sorted(BATTLE_ELIXIRS)}")
    p(f"  GUARDIAN_ELIXIRS={sorted(GUARDIAN_ELIXIRS)}")
    p(f"  FOOD_BUFFS={sorted(FOOD_BUFFS)}")

    all_perm_enchants_by_slot: dict[int, set[int]] = defaultdict(set)
    all_temp_enchants_by_slot: dict[int, set[int]] = defaultdict(set)
    all_gem_ids: set[int] = set()
    all_aura_names: set[str] = set()
    all_candidate_cast_names: set[str] = set()
    unmatched_candidate_cast_names: set[str] = set()
    non_configured_slots_with_perm_enchants: dict[int, set[int]] = defaultdict(set)
    shoulder_rows: list[dict[str, Any]] = []
    player_rows: list[dict[str, Any]] = []

    for ev in ci_players:
        source_id = ev["sourceID"]
        actor = players_by_id[source_id]
        player_name = actor["name"]
        player_class = actor.get("subType", "Unknown")
        player_role = role_by_id.get(source_id, "Unknown")
        gear = ev.get("gear", []) or []
        auras = ev.get("auras", []) or []

        gear_audit = _audit_gear(gear)
        consumable_audit = _audit_consumables(auras, gear, player_class)

        p()
        p("=" * 100)
        p(f"PLAYER: {player_name} | class={player_class} | role={player_role} | sourceID={source_id}")
        p("=" * 100)
        p("Code classification:")
        p(json.dumps(
            {
                "gear_audit": gear_audit,
                "consumable_audit": consumable_audit,
                "spell_cast_pattern_matches": spell_matches.get(
                    player_name,
                    {"drums": {}, "healthstone": {}, "dark_rune": {}, "potion": {}},
                ),
            },
            indent=2,
            sort_keys=True,
        ))
        p("Raw CombatantInfo fields used by classification:")
        p(json.dumps(
            {
                "sourceID": source_id,
                "auras": sorted(a.get("name", "") for a in auras if a.get("name")),
                "gear": [
                    {
                        "slot_index": idx,
                        "slot_name": FULL_SLOT_NAMES.get(idx, f"Slot {idx}"),
                        "configured_slot_name": ENCHANTABLE_SLOTS.get(idx),
                        "item": simplify_item(item),
                    }
                    for idx, item in enumerate(gear)
                    if item and item.get("id")
                ],
            },
            indent=2,
            sort_keys=False,
        ))

        p("Human-readable audit view:")
        for slot_idx, item in enumerate(gear):
            if not item or not item.get("id"):
                continue
            perm = int(item.get("permanentEnchant", 0) or 0)
            temp = int(item.get("temporaryEnchant", 0) or 0)
            gem_ids = [gem.get("id") for gem in item.get("gems", []) if gem and gem.get("id")]
            if perm > 0:
                all_perm_enchants_by_slot[slot_idx].add(perm)
                if slot_idx not in ENCHANTABLE_SLOTS:
                    non_configured_slots_with_perm_enchants[slot_idx].add(perm)
            if temp > 0:
                all_temp_enchants_by_slot[slot_idx].add(temp)
            for gem_id in gem_ids:
                all_gem_ids.add(gem_id)
            slot_name = FULL_SLOT_NAMES.get(slot_idx, f"Slot {slot_idx}")
            configured = ENCHANTABLE_SLOTS.get(slot_idx)
            cheap = perm in CHEAP_ENCHANTS.get(slot_idx, set())
            shoulder_flag = slot_idx == 2 and perm in CHEAP_SHOULDER_ENCHANTS
            uncommon_here = [gem_id for gem_id in gem_ids if gem_id in UNCOMMON_GEM_IDS]
            p(
                f"  {slot_idx:>2} {slot_name:<10} item={item.get('id')} ilvl={item.get('itemLevel', 0)} "
                f"perm={perm or '-'} temp={temp or '-'} gems={gem_ids or '-'} "
                f"configured={configured or '-'} cheap={cheap} shoulder_flag={shoulder_flag} "
                f"uncommon_gems={uncommon_here or '-'}"
            )

        aura_names = sorted(a.get("name", "") for a in auras if a.get("name"))
        for aura_name in aura_names:
            all_aura_names.add(aura_name)
        known_auras = []
        unknown_consumableish_auras = []
        for aura_name in aura_names:
            if aura_name in FLASK_BUFFS:
                known_auras.append(f"flask:{aura_name}")
            elif aura_name in BATTLE_ELIXIRS:
                known_auras.append(f"battle:{aura_name}")
            elif aura_name in GUARDIAN_ELIXIRS:
                known_auras.append(f"guardian:{aura_name}")
            elif aura_name in FOOD_BUFFS:
                known_auras.append(f"food:{aura_name}")
            elif aura_name in {"Brilliant Wizard Oil", "Superior Wizard Oil", "Blessed Wizard Oil", "Adamantite Weightstone", "Adamantite Sharpening Stone", "Superior Mana Oil", "Brilliant Mana Oil"}:
                known_auras.append(f"weapon:{aura_name}")
            elif CONSUMABLE_CANDIDATE_RE.search(aura_name):
                unknown_consumableish_auras.append(aura_name)
        p(f"  Aura names ({len(aura_names)}): {aura_names}")
        if known_auras:
            p(f"  Known consumable auras matched by code: {known_auras}")
        if unknown_consumableish_auras:
            p(f"  Potential consumable auras NOT matched by current sets: {unknown_consumableish_auras}")

        player_spell_casts = spell_casts.get(player_name, {})
        player_candidates = sorted(spell_candidates.get(player_name, []))
        player_unmatched = sorted(spell_unmatched_candidates.get(player_name, []))
        for spell in player_candidates:
            all_candidate_cast_names.add(spell)
        for spell in player_unmatched:
            unmatched_candidate_cast_names.add(spell)
        p(f"  spell_casts entries ({len(player_spell_casts)} unique spells)")
        if player_candidates:
            p(f"  Consumable-ish cast names seen for awards: {player_candidates}")
        if player_unmatched:
            p(f"  Consumable-ish cast names MISSED by current regexes: {player_unmatched}")

        shoulder_perm = 0
        if len(gear) > 2 and gear[2] and gear[2].get("id"):
            shoulder_perm = int(gear[2].get("permanentEnchant", 0) or 0)
            shoulder_rows.append(
                {
                    "player": player_name,
                    "class": player_class,
                    "role": player_role,
                    "enchant_id": shoulder_perm,
                    "flagged": shoulder_perm in CHEAP_SHOULDER_ENCHANTS,
                    "message": CHEAP_SHOULDER_ENCHANTS.get(shoulder_perm),
                }
            )

        player_rows.append(
            {
                "player": player_name,
                "class": player_class,
                "role": player_role,
                "source_id": source_id,
                "gear_audit": gear_audit,
                "consumable_audit": consumable_audit,
                "spell_casts": player_spell_casts,
                "spell_matches": spell_matches.get(player_name, {}),
                "candidate_spells": player_candidates,
                "unmatched_candidate_spells": player_unmatched,
                "raw_auras": aura_names,
                "raw_gear": [
                    {
                        "slot_index": idx,
                        "slot_name": FULL_SLOT_NAMES.get(idx, f"Slot {idx}"),
                        "configured_slot_name": ENCHANTABLE_SLOTS.get(idx),
                        "item": simplify_item(item),
                    }
                    for idx, item in enumerate(gear)
                    if item and item.get("id")
                ],
            }
        )

    p()
    p("=" * 100)
    p("ROLL-UP SUMMARY")
    p("=" * 100)
    p("Permanent enchant IDs seen by slot:")
    for slot_idx in sorted(all_perm_enchants_by_slot):
        p(f"  {slot_label(slot_idx)} -> {sorted(all_perm_enchants_by_slot[slot_idx])}")
    p("Temporary enchant IDs seen by slot:")
    for slot_idx in sorted(all_temp_enchants_by_slot):
        p(f"  {slot_label(slot_idx)} -> {sorted(all_temp_enchants_by_slot[slot_idx])}")
    p(f"All unique gem IDs seen ({len(all_gem_ids)}): {sorted(all_gem_ids)}")
    p(f"Gem IDs flagged as uncommon and actually seen: {sorted(all_gem_ids & UNCOMMON_GEM_IDS)}")
    p(f"Gem IDs seen but NOT flagged as uncommon: {sorted(all_gem_ids - UNCOMMON_GEM_IDS)}")
    p()
    p("Shoulder enchant rows:")
    p(json.dumps(shoulder_rows, indent=2, sort_keys=True))
    p()
    p(f"All unique aura names ({len(all_aura_names)}):")
    for aura_name in sorted(all_aura_names):
        tags = []
        if aura_name in FLASK_BUFFS:
            tags.append("FLASK")
        if aura_name in BATTLE_ELIXIRS:
            tags.append("BATTLE")
        if aura_name in GUARDIAN_ELIXIRS:
            tags.append("GUARDIAN")
        if aura_name in FOOD_BUFFS:
            tags.append("FOOD")
        if aura_name in {"Brilliant Wizard Oil", "Superior Wizard Oil", "Blessed Wizard Oil", "Adamantite Weightstone", "Adamantite Sharpening Stone", "Superior Mana Oil", "Brilliant Mana Oil"}:
            tags.append("WEAPON_AURA")
        if CONSUMABLE_CANDIDATE_RE.search(aura_name) and not tags:
            tags.append("POTENTIAL_MISS")
        suffix = f" [{', '.join(tags)}]" if tags else ""
        p(f"  - {aura_name}{suffix}")
    p()
    p("Consumable-ish cast names seen across spell_casts:")
    for spell_name_ in sorted(all_candidate_cast_names):
        tags = []
        if DRUMS_RE.search(spell_name_):
            tags.append("DRUMS")
        if HEALTHSTONE_RE.search(spell_name_):
            tags.append("HEALTHSTONE")
        if RUNE_RE.search(spell_name_):
            tags.append("RUNE")
        if POTION_RE.search(spell_name_):
            tags.append("POTION")
        if not tags:
            tags.append("MISSED_BY_REGEX")
        p(f"  - {spell_name_} [{', '.join(tags)}]")
    p()
    p("Configured-slot gaps:")
    if non_configured_slots_with_perm_enchants:
        for slot_idx in sorted(non_configured_slots_with_perm_enchants):
            p(
                f"  Slot {slot_idx} ({FULL_SLOT_NAMES.get(slot_idx, '?')}) has permanent enchants "
                f"but is missing from ENCHANTABLE_SLOTS: {sorted(non_configured_slots_with_perm_enchants[slot_idx])}"
            )
    else:
        p("  None")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = OUTPUT_DIR / f"detection_accuracy_audit_{timestamp}.txt"
    json_path = OUTPUT_DIR / f"detection_accuracy_audit_{timestamp}.json"

    audit_text = output.getvalue()
    txt_path.write_text(audit_text, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "guild_id": GUILD_ID,
                "guild_name": GUILD_NAME,
                "server_name": SERVER_NAME,
                "report_code": report_code,
                "fight": fight,
                "players": player_rows,
                "perm_enchants_by_slot": {str(k): sorted(v) for k, v in all_perm_enchants_by_slot.items()},
                "temp_enchants_by_slot": {str(k): sorted(v) for k, v in all_temp_enchants_by_slot.items()},
                "all_gem_ids": sorted(all_gem_ids),
                "all_aura_names": sorted(all_aura_names),
                "all_candidate_cast_names": sorted(all_candidate_cast_names),
                "unmatched_candidate_cast_names": sorted(unmatched_candidate_cast_names),
                "non_configured_slots_with_perm_enchants": {
                    str(k): sorted(v) for k, v in non_configured_slots_with_perm_enchants.items()
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print(audit_text)
    print(f"\nSaved full audit output to: {txt_path}")
    print(f"Saved structured audit JSON to: {json_path}")
    return {"txt": txt_path, "json": json_path}


if __name__ == "__main__":
    asyncio.run(audit())
