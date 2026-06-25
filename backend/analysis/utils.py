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


def spell_name(payload: dict[str, Any], ability_names: dict[int, str]) -> str:
    """Resolve an ability name from a v2 table row or event."""
    if payload.get("name"):
        return str(payload["name"])

    ability = payload.get("ability")
    if isinstance(ability, dict) and ability.get("name"):
        return str(ability["name"])

    game_id: int | None = None
    for key in ("abilityGameID", "gameID", "guid", "id"):
        value = payload.get(key)
        if isinstance(value, int):
            game_id = value
            if value in ability_names:
                return ability_names[value]

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

    if player_class == "Priest" and (heal_score > 0 or total_healing > 100000):
        return "Healer"

    if player_class in HEAL_CAPABLE_CLASSES:
        if heal_score > 20 and total_healing >= total_damage_done:
            return "Healer"
        if total_healing > total_damage_done * 3:
            return "Healer"
        if total_healing > total_damage_done * 0.15 and total_healing > 50000:
            return "Healer"

    if player_class in TANK_CAPABLE_CLASSES and total_damage_taken > max(total_damage_done * 2, total_healing * 2, 100000):
        return "Tank"
    if player_class in TANK_CAPABLE_CLASSES and total_damage_taken > total_damage_done * 3 and total_damage_taken > 50000:
        return "Tank"
    if player_class in TANK_CAPABLE_CLASSES and total_damage_taken > max(total_damage_done * 1.2, 80000):
        return "Tank"

    return "DPS"
