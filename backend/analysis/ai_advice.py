"""AI-powered individual player advice using Azure OpenAI."""

from __future__ import annotations

import httpx
from typing import Any

from backend.config import get_settings


SYSTEM_PROMPT = """You are an expert World of Warcraft: The Burning Crusade raid analyst. 
You are reviewing a specific player's performance on a specific boss fight.

Your job is to give actionable, specific advice for THIS player on THIS fight.

Rules:
- Focus ONLY on things this player can personally improve
- Be specific to the boss mechanics, their role, and their class
- Reference the actual data provided (deaths, damage taken sources, spell usage)
- Do NOT give generic advice that applies to all fights
- Do NOT comment on raid-wide strategy or other players' mistakes
- Consider the boss's specific mechanics and what this player's role should be doing
- Keep advice concise: 3-5 bullet points max
- If the player performed well, say so briefly and suggest minor optimizations
- Use WoW terminology naturally (don't over-explain basics)
- Consider class-specific abilities they could have used
- If they died, analyze what killed them and how to prevent it

OUTPUT FORMAT:
- Use plain text only. No markdown, no bold, no asterisks, no headers.
- Use simple dashes (-) for bullet points.
- Keep each point on its own line.
- Do not use any special formatting characters.
"""


async def get_ai_advice(
    player_name: str,
    player_class: str,
    player_role: str,
    boss_name: str,
    pull_data: dict[str, Any],
) -> str:
    """Call Azure OpenAI for personalized player advice."""
    settings = get_settings()
    if not settings.azure_openai_endpoint or not settings.azure_openai_key:
        return "AI advice is not configured. Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY."

    # Build context from pull data
    context = _build_player_context(player_name, player_class, player_role, boss_name, pull_data)

    endpoint = settings.azure_openai_endpoint.rstrip("/")
    deployment = settings.azure_openai_deployment
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-12-01-preview"

    headers = {
        "Content-Type": "application/json",
        "api-key": settings.azure_openai_key,
    }

    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        "temperature": 0.7,
        "max_completion_tokens": 600,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _build_player_context(
    player_name: str,
    player_class: str,
    player_role: str,
    boss_name: str,
    pull_data: dict[str, Any],
) -> str:
    """Build a concise context string for the LLM from pull data."""
    lines = [
        f"Player: {player_name} ({player_class}, {player_role})",
        f"Boss: {boss_name}",
        f"Kill: {'Yes' if pull_data.get('kill') else 'No (wipe)'}",
        f"Duration: {pull_data.get('duration', 0):.0f}s",
    ]

    # Deaths
    raw_deaths = pull_data.get("deaths", [])
    deaths = [d for d in raw_deaths if isinstance(d, dict) and d.get("name") == player_name]
    if deaths:
        lines.append(f"\nDeaths ({len(deaths)}):")
        for d in deaths[:3]:
            time_s = d.get("relative_time", 0) or 0
            killer = d.get("killingAbility", "Unknown")
            lines.append(f"  - Died at {time_s:.1f}s from {killer}")

    # Damage taken breakdown
    raw_dmg_taken = pull_data.get("damage_taken_detail", {})
    dmg_taken = raw_dmg_taken.get(player_name, {}) if isinstance(raw_dmg_taken, dict) else {}
    if dmg_taken and isinstance(dmg_taken, dict):
        sorted_sources = sorted(dmg_taken.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)[:8]
        lines.append(f"\nDamage Taken (top sources):")
        for source, amount in sorted_sources:
            lines.append(f"  - {source}: {amount:,}" if isinstance(amount, (int, float)) else f"  - {source}")

    # Spell casts
    raw_casts = pull_data.get("spell_casts", {})
    spell_casts = raw_casts.get(player_name, {}) if isinstance(raw_casts, dict) else {}
    if spell_casts and isinstance(spell_casts, dict):
        sorted_casts = sorted(spell_casts.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)[:10]
        lines.append(f"\nSpell Casts:")
        for spell, count in sorted_casts:
            lines.append(f"  - {spell}: {count}")

    # Healing done (if healer)
    if player_role == "Healer":
        raw_heals = pull_data.get("heal_details", {})
        heal_details = raw_heals.get(player_name, {}) if isinstance(raw_heals, dict) else {}
        if heal_details and isinstance(heal_details, dict):
            sorted_heals = sorted(heal_details.items(), key=lambda x: x[1].get("total", 0) if isinstance(x[1], dict) else 0, reverse=True)[:6]
            lines.append(f"\nHealing Done:")
            for spell, info in sorted_heals:
                if isinstance(info, dict):
                    lines.append(f"  - {spell}: {info.get('total', 0):,} ({info.get('casts', 0)} casts)")

    # Damage done (if DPS/Tank)
    if player_role in ("DPS", "Tank"):
        raw_dmg = pull_data.get("damage_done", {})
        dmg_done = raw_dmg.get(player_name, {}) if isinstance(raw_dmg, dict) else {}
        if dmg_done and isinstance(dmg_done, dict):
            sorted_dmg = sorted(dmg_done.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)[:8]
            total = sum(v for v in dmg_done.values() if isinstance(v, (int, float)))
            lines.append(f"\nDamage Done ({total:,} total):")
            for spell, amount in sorted_dmg:
                lines.append(f"  - {spell}: {amount:,}" if isinstance(amount, (int, float)) else f"  - {spell}")

    # Interrupts / Dispels (may be dict or list in different data shapes)
    raw_interrupts = pull_data.get("interrupts", {})
    raw_dispels = pull_data.get("dispels", {})
    interrupts = raw_interrupts.get(player_name, 0) if isinstance(raw_interrupts, dict) else 0
    dispels = raw_dispels.get(player_name, 0) if isinstance(raw_dispels, dict) else 0
    if interrupts or dispels:
        lines.append(f"\nUtility: {interrupts} interrupts, {dispels} dispels")

    lines.append("\nGive specific, actionable advice for this player on this fight.")
    return "\n".join(lines)
