"""Shared analysis helpers."""

from __future__ import annotations

from typing import Any

PURE_DPS_CLASSES = {"Mage", "Warlock", "Rogue", "Hunter"}
HEAL_CAPABLE_CLASSES = {"Priest", "Paladin", "Shaman", "Druid"}
TANK_CAPABLE_CLASSES = {"Warrior", "Paladin", "Druid"}

TANK_SPELLS = {
    "Shield Slam", "Devastate", "Revenge", "Shield Block", "Taunt",
    "Thunder Clap", "Holy Shield", "Righteous Defense", "Avenger's Shield",
    "Maul", "Lacerate", "Mangle (Bear)", "Swipe", "Growl", "Challenging Roar",
}
HEAL_SPELLS = {
    "Flash of Light", "Holy Light", "Flash Heal", "Greater Heal",
    "Prayer of Healing", "Prayer of Mending", "Circle of Healing",
    "Chain Heal", "Healing Wave", "Lesser Healing Wave", "Rejuvenation",
    "Lifebloom", "Regrowth", "Swiftmend", "Earth Shield", "Binding Heal", "Renew",
}

# Canonical names for spell IDs that WCL's ability database mislabels, so that
# every rank of an ability collapses to one consistent name for cast counting
# and buff-uptime tracking. Notably the "fresh classic" DB shows Holy Shield
# Rank 1 (20925) as "Sacred Shield" (an ability that does not exist in TBC),
# which otherwise splits a Paladin's Holy Shield across two names.
# Holy Shield ranks: R1 20925, R2 20927, R3 20928, R4 27179.
CANONICAL_SPELL_NAMES: dict[int, str] = {
    20925: "Holy Shield",
    20927: "Holy Shield",
    20928: "Holy Shield",
    27179: "Holy Shield",
}


def spell_name(payload: dict[str, Any], ability_names: dict[int, str]) -> str:
    """Resolve an ability name from a v2 table row or event.

    Applies CANONICAL_SPELL_NAMES overrides (by spell/game ID) first so known
    WCL naming quirks (e.g. Holy Shield Rank 1 shown as "Sacred Shield") do not
    fragment an ability's ranks across different display names.
    """
    game_id: int | None = None
    for key in ("abilityGameID", "gameID", "guid", "id"):
        value = payload.get(key)
        if isinstance(value, int):
            game_id = value
            break
    ability = payload.get("ability")
    if game_id is None and isinstance(ability, dict):
        guid = ability.get("guid")
        if isinstance(guid, int):
            game_id = guid
    if game_id is not None and game_id in CANONICAL_SPELL_NAMES:
        return CANONICAL_SPELL_NAMES[game_id]

    if payload.get("name"):
        return str(payload["name"])

    if isinstance(ability, dict) and ability.get("name"):
        return str(ability["name"])

    if game_id is not None and game_id in ability_names:
        return ability_names[game_id]

    return f"Spell {game_id}" if game_id else "Unknown"


def actor_name(actor_id: int | None, actors_by_id: dict[int, dict[str, Any]]) -> str:
    """Resolve an actor id to a display name."""
    actor = actors_by_id.get(actor_id) if actor_id is not None else None
    if actor and actor.get("name"):
        return str(actor["name"])
    return f"Unknown ({actor_id})" if actor_id is not None else "Unknown"


def infer_role(
    player_class: str,
    spell_counts: dict[str, int] | None = None,
    total_healing: int = 0,
    total_damage_done: int = 0,
    total_damage_taken: int = 0,
) -> str:
    """Infer a raid role from spell usage when available, else aggregate ratios."""
    if player_class in PURE_DPS_CLASSES:
        return "DPS"

    spell_counts = spell_counts or {}
    tank_score = sum(count for spell, count in spell_counts.items() if spell in TANK_SPELLS)
    heal_score = sum(count for spell, count in spell_counts.items() if spell in HEAL_SPELLS)

    if player_class in TANK_CAPABLE_CLASSES and tank_score > 20 and total_damage_taken > total_damage_done:
        return "Tank"
    # High tank spell usage alone is definitive (bear tanks deal significant damage)
    if player_class in TANK_CAPABLE_CLASSES and tank_score > 50:
        return "Tank"

    if player_class in HEAL_CAPABLE_CLASSES:
        # Strong heal spell usage + healing at least matches damage = healer
        if heal_score > 20 and total_healing >= total_damage_done:
            return "Healer"
        # Overwhelming healing output relative to damage
        if total_healing > total_damage_done * 3:
            return "Healer"
        # Meaningful healing that isn't just incidental (e.g. Vampiric Embrace)
        if heal_score > 10 and total_healing > total_damage_done * 0.5:
            return "Healer"

    if player_class in TANK_CAPABLE_CLASSES and total_damage_taken > max(total_damage_done * 2, total_healing * 2, 100000):
        return "Tank"
    if player_class in TANK_CAPABLE_CLASSES and total_damage_taken > total_damage_done * 3 and total_damage_taken > 50000:
        return "Tank"
    if player_class in TANK_CAPABLE_CLASSES and total_damage_taken > max(total_damage_done * 1.2, 80000):
        return "Tank"

    return "DPS"
