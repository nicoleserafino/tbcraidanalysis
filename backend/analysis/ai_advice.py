"""AI-powered individual player advice using Azure OpenAI."""

from __future__ import annotations

import httpx
from typing import Any

from backend.config import get_settings


SYSTEM_PROMPT = """You are an elite World of Warcraft: The Burning Crusade raid coach.
You are reviewing a specific player's performance on a specific boss fight pull.
Your job is to provide constructive, actionable coaching for THIS player on THIS pull.

ANALYSIS FRAMEWORK — evaluate ALL of these for the player's role:

FOR ALL PLAYERS:
- Deaths: What killed them? Was it avoidable? What cooldowns/consumables could have saved them?
- Damage Taken: Are they taking unnecessary damage? Standing in mechanics? Getting hit by avoidable abilities?
- Positioning: Based on damage sources, were they in the wrong spot? (e.g., getting Spout on Lurker, Conflag on Kael)
- Boss Mechanics: Did they handle the boss's specific mechanics properly based on their role?
- Consumable/Buff usage: Are they using healthstones, potions, or cooldowns when in danger?

FOR HEALERS:
- Healing targets: Are they healing the correct assignments? (tanks vs raid healing)
- Spell selection: Are they using the right heals? (e.g., big heals on tanks, AoE heals during raid damage)
- Overheal percentage: Are they wasting mana on overhealing?
- Healing throughput: Is their HPS appropriate for the fight duration?
- Mana management: Are they running out? Using mana pots/innervates effectively?
- Clutch moments: Did they save anyone at low HP? Did someone die they could have saved?

FOR TANKS:
- Damage taken spikes: Are they using cooldowns at the right time?
- Threat generation: Based on cast data, are they maintaining threat rotation?
- Positioning: Are they keeping the boss faced correctly? Managing adds?
- Survivability: Shield Block/Ironshield Pot/trinket usage timing

FOR DPS:
- Rotation efficiency: Are they casting their damage spells optimally? Any missing key abilities?
- Uptime: Based on cast count vs fight duration, are they actively DPSing?
- Target priority: On multi-target fights, are they on the right target?
- Mechanics handling: Are they interrupting, moving for mechanics, avoiding damage?

BOSS-SPECIFIC KNOWLEDGE (use when relevant):
- Hydross: Phase transitions, nature/frost resist tank swaps, don't pull aggro during transitions
- Lurker: Spout dodge (jump in water or run behind), submerge phase adds
- Leotheras: Demon phase (raid spread), whirlwind (melee out), inner demons
- Karathress: Kill order priorities, interrupt Tidalvess heals
- Morogrim: Murloc waves (AoE ready), Tidal Wave (melee beware), earthquake
- Vashj: P2 cores, P3 bats/striders, interrupt Enchanted Elementals
- Kael'thas: Phase-specific (advisors, weapons, advisors revive, Kael). Conflag spread. Flamestrike dodge. MC break. Pyroblast interrupts/shield wall.
- Al'ar: Platform transitions, meteor dive, adds in P2
- Void Reaver: Arcane Orbs (move away), simple tank-and-spank with knockback
- Solarian: Wrath of Astromancer (run out), adds, split phase

RULES:
- Be specific — reference actual numbers from the data (damage amounts, death times, specific spells)
- Be constructive — frame advice as coaching, not criticism
- Consider fight context — dying at 90% boss HP vs 5% is very different
- If the player performed well, acknowledge it and suggest only minor optimizations
- Don't comment on other players' mistakes unless it directly affected this player
- Consider the kill/wipe status — on wipes, focus on what could change the outcome
- Prioritize the highest-impact improvements first

OUTPUT FORMAT:
- Use plain text only. No markdown, no bold, no asterisks, no headers.
- Start with a one-sentence overall assessment.
- Then give 3-6 specific coaching points as dashed bullet points.
- Keep it concise but specific. Each point should be actionable.
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
        "max_completion_tokens": 800,
    }

    async with httpx.AsyncClient(timeout=45) as client:
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
    """Build comprehensive context for the LLM from pull data."""
    duration = pull_data.get("duration_sec", 0) or 0
    kill = pull_data.get("kill", False)

    lines = [
        f"=== FIGHT CONTEXT ===",
        f"Player: {player_name} ({player_class}, Role: {player_role})",
        f"Boss: {boss_name}",
        f"Result: {'KILL' if kill else 'WIPE'}",
        f"Duration: {duration:.0f}s",
    ]

    # Other players and their roles for context
    roles = pull_data.get("roles", {})
    if roles and isinstance(roles, dict):
        tanks = [n for n, r in roles.items() if r == "Tank"]
        healers = [n for n, r in roles.items() if r == "Healer"]
        if tanks:
            lines.append(f"Tanks: {', '.join(tanks)}")
        if healers:
            lines.append(f"Healers: {', '.join(healers)}")

    # === DEATHS (all deaths for timeline context + player's specifically) ===
    raw_deaths = pull_data.get("deaths", [])
    if raw_deaths and isinstance(raw_deaths, list):
        all_deaths = [d for d in raw_deaths if isinstance(d, dict)]
        player_deaths = [d for d in all_deaths if d.get("player") == player_name]

        if player_deaths:
            lines.append(f"\n=== PLAYER DEATHS ({len(player_deaths)}) ===")
            for d in player_deaths:
                time_s = d.get("relative_time", 0) or 0
                lines.append(f"  - Died at {time_s:.1f}s into the fight")

        # Show death timeline for context (who died before/after)
        if all_deaths:
            lines.append(f"\n=== RAID DEATH TIMELINE ===")
            for d in all_deaths[:10]:
                lines.append(f"  - {d.get('player', '?')} died at {d.get('relative_time', 0):.1f}s")

    # === DAMAGE TAKEN (detailed per-source) ===
    raw_dmg_taken = pull_data.get("player_damage_taken", {})
    dmg_taken = raw_dmg_taken.get(player_name, {}) if isinstance(raw_dmg_taken, dict) else {}
    if dmg_taken and isinstance(dmg_taken, dict):
        sorted_sources = sorted(
            dmg_taken.items(),
            key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0,
            reverse=True
        )[:12]
        total_taken = sum(v for _, v in sorted_sources if isinstance(v, (int, float)))
        lines.append(f"\n=== DAMAGE TAKEN ({total_taken:,} total) ===")
        for source, amount in sorted_sources:
            if isinstance(amount, (int, float)) and amount > 0:
                pct = round(amount / max(total_taken, 1) * 100)
                lines.append(f"  - {source}: {amount:,} ({pct}%)")

    # Total damage taken compared to others (for positioning context)
    raw_totals = pull_data.get("player_damage_taken_total", {})
    if raw_totals and isinstance(raw_totals, dict):
        sorted_all = sorted(raw_totals.items(), key=lambda x: x[1] if isinstance(x[1], (int,float)) else 0, reverse=True)
        player_total = raw_totals.get(player_name, 0)
        rank = next((i+1 for i, (n, _) in enumerate(sorted_all) if n == player_name), 0)
        if player_total and rank:
            lines.append(f"  Rank: #{rank}/{len(sorted_all)} damage taken ({player_total:,} total)")

    # === SPELL CASTS (rotation analysis) ===
    raw_casts = pull_data.get("spell_casts", {})
    spell_casts = raw_casts.get(player_name, {}) if isinstance(raw_casts, dict) else {}
    if spell_casts and isinstance(spell_casts, dict):
        sorted_casts = sorted(spell_casts.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)[:15]
        total_casts = sum(v for _, v in sorted_casts if isinstance(v, (int, float)))
        cpm = round(total_casts / max(duration / 60, 1), 1) if duration > 0 else 0
        lines.append(f"\n=== SPELL CASTS ({total_casts} total, {cpm} casts/min) ===")
        for spell, count in sorted_casts:
            lines.append(f"  - {spell}: {count}")

    # === HEALING (detailed for healers, summary for self-healing) ===
    raw_heals = pull_data.get("heal_details", {})
    heal_details = raw_heals.get(player_name, {}) if isinstance(raw_heals, dict) else {}
    if heal_details and isinstance(heal_details, dict):
        sorted_heals = sorted(
            heal_details.items(),
            key=lambda x: x[1].get("total", 0) if isinstance(x[1], dict) else 0,
            reverse=True
        )[:10]
        total_healing = sum(info.get("total", 0) for _, info in sorted_heals if isinstance(info, dict))
        total_overheal = sum(info.get("overheal", 0) for _, info in sorted_heals if isinstance(info, dict))
        overheal_pct = round(total_overheal / max(total_healing + total_overheal, 1) * 100)
        hps = round(total_healing / max(duration, 1))

        lines.append(f"\n=== HEALING DONE ({total_healing:,} effective, {hps} HPS, {overheal_pct}% overheal) ===")
        for spell, info in sorted_heals:
            if isinstance(info, dict):
                eff = info.get("total", 0)
                oh = info.get("overheal", 0)
                count = info.get("count", 0)
                is_hot = info.get("is_hot", False)
                spell_oh_pct = round(oh / max(eff + oh, 1) * 100)
                hot_tag = " [HoT]" if is_hot else ""
                lines.append(f"  - {spell}{hot_tag}: {eff:,} effective, {count} casts, {spell_oh_pct}% overheal")

    # === DAMAGE DONE (for DPS/Tank context) ===
    if player_role in ("DPS", "Tank"):
        raw_dmg = pull_data.get("damage_done", {})
        dmg_done = raw_dmg.get(player_name, {}) if isinstance(raw_dmg, dict) else {}
        if dmg_done and isinstance(dmg_done, dict):
            sorted_dmg = sorted(dmg_done.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)[:10]
            total = sum(v for v in dmg_done.values() if isinstance(v, (int, float)))
            dps = round(total / max(duration, 1))
            lines.append(f"\n=== DAMAGE DONE ({total:,} total, {dps} DPS) ===")
            for spell, amount in sorted_dmg:
                if isinstance(amount, (int, float)):
                    lines.append(f"  - {spell}: {amount:,}")

    # === INTERRUPTS AND DISPELS ===
    raw_interrupts = pull_data.get("interrupts", [])
    raw_dispels = pull_data.get("dispels", [])

    player_interrupts = []
    player_dispels = []
    if isinstance(raw_interrupts, list):
        player_interrupts = [i for i in raw_interrupts if isinstance(i, dict) and i.get("source") == player_name]
    if isinstance(raw_dispels, list):
        player_dispels = [d for d in raw_dispels if isinstance(d, dict) and d.get("source") == player_name]

    if player_interrupts or player_dispels:
        lines.append(f"\n=== UTILITY ===")
        if player_interrupts:
            lines.append(f"  Interrupts: {len(player_interrupts)}")
            for i in player_interrupts[:5]:
                lines.append(f"    - {i.get('ability', '?')} at {i.get('relative_time', 0):.1f}s")
        if player_dispels:
            lines.append(f"  Dispels: {len(player_dispels)}")
            for d in player_dispels[:5]:
                lines.append(f"    - {d.get('ability', '?')} at {d.get('relative_time', 0):.1f}s")

    # === BUFF EVENTS (consumables, cooldowns, relevant buffs) ===
    raw_buffs = pull_data.get("buff_events", {})
    player_buffs = raw_buffs.get(player_name, []) if isinstance(raw_buffs, dict) else []
    if player_buffs and isinstance(player_buffs, list):
        # Filter to meaningful buffs (cooldowns, consumables, procs)
        meaningful_buffs = [b for b in player_buffs if isinstance(b, dict) and b.get("type") == "applybuff"]
        if meaningful_buffs:
            lines.append(f"\n=== BUFFS APPLIED (notable) ===")
            seen = set()
            for b in meaningful_buffs[:20]:
                spell = b.get("spell", "")
                if spell and spell not in seen:
                    seen.add(spell)
                    lines.append(f"  - {spell} at {b.get('time', 0):.1f}s")

    # === CLUTCH HEALS (if this player was involved) ===
    clutch_heals = pull_data.get("clutch_heals", [])
    if clutch_heals and isinstance(clutch_heals, list):
        player_saved = [h for h in clutch_heals if isinstance(h, dict) and h.get("target") == player_name]
        player_clutch = [h for h in clutch_heals if isinstance(h, dict) and h.get("healer") == player_name]
        if player_saved:
            lines.append(f"\n=== CLUTCH SAVES (player was saved) ===")
            for h in player_saved[:3]:
                lines.append(f"  - {h.get('healer','?')} healed them at {h.get('hp_pct',0)}% HP with {h.get('spell','?')}")
        if player_clutch and player_role == "Healer":
            lines.append(f"\n=== CLUTCH SAVES (player made) ===")
            for h in player_clutch[:5]:
                lines.append(f"  - Saved {h.get('target','?')} at {h.get('hp_pct',0)}% HP with {h.get('spell','?')}")

    lines.append(f"\n=== COACHING REQUEST ===")
    lines.append(f"Based on the above data, provide specific coaching for {player_name} ({player_class} {player_role}) on this {boss_name} {'kill' if kill else 'wipe'}.")
    lines.append(f"Focus on their biggest areas for improvement. Be constructive and specific.")

    return "\n".join(lines)
