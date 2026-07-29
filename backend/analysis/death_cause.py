"""Evidence-based death-cause classification using the Threat table (aggro bands).

This replaces the frontend's heuristic ``likelyCause`` guessing (which never looked
at the real threat table) with a data-driven classifier. For every player death it
determines *why* the player died and, in particular, whether a DPS died because they
took threat before it was safe — split into:

  * ``attacked_first`` — opened on a mob before any tank had it (incl. fresh pulls
    after a threat reset/respawn), so any threat = instant aggro.
  * ``ripped_threat``  — out-threated a tank who already held the mob contiguously.

These "threat mistake" deaths are the ones a raid generally *cannot* heal through
(unlike avoidable mechanic damage such as Conflagration), so the pull summary weights
them as the more likely wipe cause when present.

Design: classification is split in two so it can plug into the existing pipeline,
where raid roles are only known *after* every pull has been processed.

  1. :func:`build_death_context` — role-independent per-death facts, computed inside
     ``build_pull_data`` from the fight's threat bands + damage events.
  2. :func:`classify_deaths` — role-dependent categorisation, run in a post-pass once
     :func:`infer_role` has labelled tanks/healers/DPS across the night.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

# --- TBC-specific mob/ability knowledge (safe defaults; being meleed by these, or
#     doing only these abilities, is NOT a DPS threat mistake) -------------------
FIXATE_MOBS = {"Thaladred the Darkener"}  # fixates a random target — cannot be tanked
WEAPON_MOBS = {
    "Infinity Blades", "Cosmic Infuser", "Staff of Disintegration", "Warp Slicer",
    "Devastation", "Phaseshift Bulwark", "Netherstrand Longbow",
}  # Kael weapons have no assigned tank -> engaging them is always "attacked first"
TANK_FACING = {"Saw Blade"}  # frontal/directional — tank must face the mob away, not a DPS fault
# Priest DoTs / passive threat that don't represent actively attacking a mob.
DOT_ONLY = {
    "Shadow Word: Pain", "Vampiric Touch", "Devouring Plague", "Holy Fire",
    "Touch of Weakness", "Melee",
}
# Passive/non-attack "damage" that still generates threat (e.g. Power Word: Shield reflect).
NON_ENGAGING = {"Reflective Shield"}

MELEE_ABILITY = "Melee"  # normalized name for auto-attacks (abilityGameID 0/1/None)

# Correlation windows (ms)
_DEATH_WINDOW = 6000   # look this far back from a death for what was hitting the player
_BAND_SLOP = 1500      # tolerance around a death for "held aggro at time of death"
_RESET_GAP = 3000      # a hole in the aggro timeline this long = threat was dropped/reset


def _abil(ability_game_id: Any, ability_names: dict) -> str:
    if ability_game_id in (0, 1, None):
        return MELEE_ABILITY
    return ability_names.get(ability_game_id, f"#{ability_game_id}")


def build_death_context(
    fight: dict,
    actors_by_id: dict,
    players_by_id: dict,
    ability_names: dict,
    deaths: list,
    damage_taken: list,
    damage_done: list,
    threat_table: Any,
) -> list[dict]:
    """Compute role-independent facts about each player death.

    Returns one dict per player death with everything :func:`classify_deaths` needs
    without knowing raid roles yet.
    """
    start = fight["startTime"]

    def pname(i):
        return actors_by_id.get(i, {}).get("name", f"#{i}")

    player_deaths = [
        d for d in deaths
        if d.get("type") == "death" and d.get("targetID") in players_by_id
    ]
    if not player_deaths:
        return []

    # Aggro bands: bands[player_id][enemy_id] = [(start,end)],
    # enemy_timeline[enemy_id] = sorted [(start,end,holder_player_id)]
    threat_entries = []
    if isinstance(threat_table, dict):
        threat_entries = threat_table.get("threat", []) or []
    elif isinstance(threat_table, list):
        threat_entries = threat_table
    bands: dict[int, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    enemy_timeline: dict[int, list] = defaultdict(list)
    for pe in threat_entries:
        pid = pe.get("id")
        for t in pe.get("targets", []):
            eid = t.get("id")
            for b in t.get("bands", []):
                bands[pid][eid].append((b["startTime"], b["endTime"]))
                enemy_timeline[eid].append((b["startTime"], b["endTime"], pid))
    for eid in enemy_timeline:
        enemy_timeline[eid].sort(key=lambda x: x[0])

    # Damage taken per player: [(ts, ability, source_name, source_type)]
    dt: dict[int, list] = defaultdict(list)
    for ev in damage_taken:
        if ev.get("type") != "damage":
            continue
        tid = ev.get("targetID")
        if tid not in players_by_id:
            continue
        src = actors_by_id.get(ev.get("sourceID"), {})
        dt[tid].append((
            ev["timestamp"], _abil(ev.get("abilityGameID"), ability_names),
            src.get("name", ""), src.get("type"),
        ))

    # Damage done by each player to each enemy: set of ability names
    dd_ab: dict[tuple, set] = defaultdict(set)
    for ev in damage_done:
        if ev.get("type") != "damage":
            continue
        sid = ev.get("sourceID")
        if sid not in players_by_id:
            continue
        dd_ab[(sid, ev.get("targetID"))].add(_abil(ev.get("abilityGameID"), ability_names))

    contexts = []
    for ev in player_deaths:
        tid = ev["targetID"]
        ts = ev["timestamp"]

        recent = [x for x in dt.get(tid, []) if 0 <= ts - x[0] <= _DEATH_WINDOW]
        melee_npcs = set()
        meleed_by_friendly = False  # a friendly player meleeing us => Mind Control
        for _, an, sn, st in recent:
            if an == MELEE_ABILITY and st == "NPC":
                melee_npcs.add(sn)
            if an == MELEE_ABILITY and st == "Player" and sn != pname(tid):
                meleed_by_friendly = True

        # Which meleeing NPCs did this player hold aggro on at time of death?
        ripped = []
        for eid, wins in bands.get(tid, {}).items():
            if actors_by_id.get(eid, {}).get("type") != "NPC":
                continue
            en = pname(eid)
            if en not in melee_npcs:
                continue
            for bstart, bend in wins:
                if bstart - 1000 <= ts <= bend + _BAND_SLOP:
                    # holder whose band ends closest before this player's band starts
                    prev_holder, prev_end = None, None
                    for (bs2, be2, holder) in enemy_timeline.get(eid, []):
                        if bs2 < bstart - 200 and holder != tid:
                            if prev_end is None or be2 > prev_end:
                                prev_holder, prev_end = holder, be2
                    ripped.append({
                        "enemy_id": eid,
                        "enemy_name": en,
                        "prev_holder_name": pname(prev_holder) if prev_holder is not None else None,
                        "prev_gap_ms": (bstart - prev_end) if prev_end is not None else None,
                    })

        # Top mechanic ability (non-melee) hitting the player near death — for the
        # avoidable-mechanic / tank-facing bucket when it's not a threat rip.
        agg = defaultdict(int)
        for x in recent:
            if x[1] != MELEE_ABILITY:
                agg[x[1]] += 1
        top_mechanic = max(agg, key=agg.get) if agg else None

        # Damage abilities this player dealt to the mobs they held.
        did_to_ripped = set()
        for r in ripped:
            did_to_ripped |= dd_ab.get((tid, r["enemy_id"]), set())

        contexts.append({
            "player": pname(tid),
            "player_class": players_by_id.get(tid, {}).get("subType", ""),
            "timestamp": ts,
            "relative_time": round((ts - start) / 1000, 1),
            "meleed_by_friendly": meleed_by_friendly,
            "ripped": ripped,
            "top_mechanic_ability": top_mechanic,
            "dmg_abilities_to_ripped": sorted(did_to_ripped),
        })
    return contexts


# Human-readable labels for each machine category.
CAUSE_LABELS = {
    "tank": "Tank death",
    "mind_control": "Mind Control (killed by an MC'd raider)",
    "mechanic": "Avoidable mechanic damage",
    "tank_facing": "Tank-facing mechanic (not a DPS fault)",
    "fixate": "Fixate mob (cannot be tanked)",
    "forced_aggro": "Forced aggro after all tanks died",
    "healer_aggro": "Pulled aggro without attacking (heal/shield threat or loose add)",
    "priest_dot": "Priest DoT only (not actively attacking)",
    "attacked_first": "Threat — attacked before a tank had the mob",
    "ripped_threat": "Threat — out-threated the tank who had the mob",
}
# Categories that count as a DPS "threat mistake" wipe driver.
THREAT_CATEGORIES = ("attacked_first", "ripped_threat")


def classify_deaths(contexts: list[dict], roles: dict[str, str]) -> dict:
    """Assign a cause category to each death and summarise the pull.

    ``roles`` maps player name -> "Tank"/"Healer"/"DPS" (from :func:`infer_role`).
    Returns ``{"deaths": [...], "summary": {...}}``.
    """
    def is_tank(name):
        return roles.get(name) == "Tank"

    # Time after which every tank that showed up is dead -> deaths past it are forced aggro.
    tank_death_times = {
        c["player"]: c["timestamp"]
        for c in contexts if is_tank(c["player"])
    }
    tanks_present = {n for n, r in roles.items() if r == "Tank"}
    if tanks_present and tanks_present.issubset(set(tank_death_times)):
        no_tank_time = max(tank_death_times[t] for t in tanks_present)
    else:
        no_tank_time = None

    out = []
    for c in contexts:
        cat = _classify_one(c, roles, is_tank, no_tank_time)
        out.append({
            "player": c["player"],
            "relative_time": c["relative_time"],
            "category": cat,
            "cause": CAUSE_LABELS.get(cat, cat),
        })

    # --- pull summary --------------------------------------------------------
    counts: dict[str, int] = defaultdict(int)
    per_player: dict[str, dict] = defaultdict(lambda: {"attacked_first": 0, "ripped_threat": 0, "total": 0})
    mechanic_abilities: dict[str, int] = defaultdict(int)
    for d, c in zip(out, contexts):
        counts[d["category"]] += 1
        if d["category"] in THREAT_CATEGORIES:
            pp = per_player[d["player"]]
            pp[d["category"]] += 1
            pp["total"] += 1
        elif d["category"] in ("mechanic", "tank_facing") and c.get("top_mechanic_ability"):
            mechanic_abilities[c["top_mechanic_ability"]] += 1

    threat_total = counts.get("attacked_first", 0) + counts.get("ripped_threat", 0)
    mechanic_total = counts.get("mechanic", 0)
    summary = {
        "counts": dict(counts),
        "threat_death_total": threat_total,
        "attacked_first_total": counts.get("attacked_first", 0),
        "ripped_threat_total": counts.get("ripped_threat", 0),
        "mechanic_death_total": mechanic_total,
        "mechanic_abilities": dict(mechanic_abilities),
        "threat_players": {k: v for k, v in per_player.items()},
    }
    return {"deaths": out, "summary": summary}


def _classify_one(c, roles, is_tank, no_tank_time):
    nm = c["player"]
    if is_tank(nm):
        return "tank"
    if c["meleed_by_friendly"]:
        return "mind_control"

    ripped = c["ripped"]
    if not ripped:
        # not a threat pickup -> it was a mechanic (or tank-facing) death
        if c.get("top_mechanic_ability") in TANK_FACING:
            return "tank_facing"
        return "mechanic"

    real = [r for r in ripped if r["enemy_name"] not in FIXATE_MOBS]
    if not real:
        return "fixate"

    if no_tank_time is not None and c["timestamp"] > no_tank_time + 500:
        return "forced_aggro"

    did = set(c["dmg_abilities_to_ripped"])
    # Priest who only had a DoT on the mob = not actively attacking.
    if c["player_class"] == "Priest" and (not did or did.issubset(DOT_ONLY)):
        return "priest_dot"
    # Anyone whose only "damage" was passive/non-attack = heal/shield threat or loose add.
    if not (did - NON_ENGAGING):
        return "healer_aggro"

    # Ripped off a tank vs attacked first. A rip only counts if a tank held the mob
    # contiguously up to this player's band; a gap in the timeline = fresh pull.
    off_tank = False
    for r in real:
        if r["enemy_name"] in FIXATE_MOBS:
            continue
        gap = r["prev_gap_ms"]
        if (r["prev_holder_name"] and is_tank(r["prev_holder_name"])
                and gap is not None and gap <= _RESET_GAP):
            off_tank = True
    if any(r["enemy_name"] in WEAPON_MOBS for r in real):
        off_tank = False  # weapons have no assigned tank -> attacked first
    return "ripped_threat" if off_tank else "attacked_first"
