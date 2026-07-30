"""Enhancement Shaman weapon-sync analysis.

Reconstructs main-hand / off-hand auto-attack timing to grade how well a
dual-wielding enhancement shaman keeps its two weapons synced. Keeping both
swings inside a ~500ms window means the pair spends a single Flurry charge
instead of two, preserving Flurry uptime.

IMPORTANT ACCURACY NOTE: Warcraft Logs does not flag main-hand vs off-hand
auto-attacks (both log as "Melee", abilityGameID 1). So anything that needs
hand identity — the offset *shape* and "main hand leads" read — is INFERRED
from swing timing and hit size, not measured. The graded metrics (sync %,
Flurry uptime, Windfury procs) rely only on directly-observed data.

No extra WCL calls are needed: swings and Windfury come from the DamageDone
event stream and Flurry comes from the Buffs stream, both already fetched.
"""

from __future__ import annotations

import statistics
from typing import Any

# A main-hand and off-hand swing count as "synced" when they land within this
# window, so the pair consumes one Flurry charge instead of two.
SYNC_WINDOW_MS = 500

# A single Windfury proc grants two extra attacks that land within a few ms of
# each other. Attacks closer than this are collapsed into one proc so we count
# procs, not individual extra swings.
WF_PROC_WINDOW_MS = 200

# Minimum melee auto-attack activity for a shaman to be treated as Enhancement.
# Resto/Elemental shamans essentially never melee; enhancement swings ~50+/min.
_MIN_SWINGS = 15
_MIN_SWINGS_PER_MIN = 15

# Offset buckets (ms) for the inferred offset-shape insight.
_OFFSET_BUCKETS = (
    ("together", 0, 50),
    ("tight", 50, 200),
    ("lead", 200, 400),
    ("wide", 400, SYNC_WINDOW_MS),
)


def _flurry_uptime_pct(flurry_events: list[dict], start: int, end: int) -> float | None:
    """Reconstruct Flurry buff uptime from apply/refresh/remove events.

    Mirrors the frontend computeBuffUptime convention: if the first event is a
    refresh/remove, the buff was already active at pull start.
    """
    if not flurry_events:
        return None
    total_ms = end - start
    if total_ms <= 0:
        return None

    active = 0.0
    on = False
    last = start
    if flurry_events[0]["type"] in ("removebuff", "refreshbuff"):
        on = True
        last = start
    for ev in flurry_events:
        t = ev["timestamp"]
        etype = ev["type"]
        if etype == "applybuff":
            if not on:
                on = True
                last = t
        elif etype == "removebuff":
            if on:
                active += t - last
                on = False
        elif etype == "refreshbuff":
            if not on:
                on = True
                last = t
    if on:
        active += end - last
    return max(0.0, min(100.0, active / total_ms * 100))


def _pair_swings(swings: list[tuple[int, int]]) -> tuple[list[tuple], int]:
    """Greedily pair adjacent swings that land within the sync window.

    swings: sorted list of (timestamp_ms, amount). Returns (pairs, lone_count)
    where each pair is ((t1, amt1), (t2, amt2)).
    """
    pairs: list[tuple] = []
    lone = 0
    i = 0
    n = len(swings)
    while i < n:
        if i + 1 < n and swings[i + 1][0] - swings[i][0] <= SYNC_WINDOW_MS:
            pairs.append((swings[i], swings[i + 1]))
            i += 2
        else:
            lone += 1
            i += 1
    return pairs, lone


def _count_wf_procs(timestamps: list[int]) -> int:
    """Collapse paired Windfury extra-attacks into distinct procs.

    A Windfury proc grants two extra attacks logged a few ms apart, so raw event
    counts double the real proc count. Attacks within WF_PROC_WINDOW_MS of the
    previous one belong to the same proc.
    """
    if not timestamps:
        return 0
    ordered = sorted(timestamps)
    procs = 1
    prev = ordered[0]
    for t in ordered[1:]:
        if t - prev > WF_PROC_WINDOW_MS:
            procs += 1
        prev = t
    return procs


def compute_weapon_sync(
    fight: dict,
    players_by_id: dict,
    ability_names: dict,
    damage_done_events: list,
    buffs: list,
) -> dict:
    """Compute per-enhancement-shaman weapon-sync metrics for a pull.

    Returns a dict keyed by player name. Only shamans with sustained melee
    auto-attack activity (i.e. Enhancement) are included.
    """
    start = fight["startTime"]
    end = fight["endTime"]
    duration_sec = (end - start) / 1000
    if duration_sec <= 0:
        return {}
    duration_min = duration_sec / 60

    # Collect per-player melee swings (ability 1) and Windfury Attack timestamps.
    swings_by_player: dict[int, list[tuple[int, int]]] = {}
    wf_ts_by_player: dict[int, list[int]] = {}
    for ev in damage_done_events:
        if ev.get("type") != "damage":
            continue
        sid = ev.get("sourceID")
        if sid not in players_by_id:
            continue
        if players_by_id[sid].get("subType") != "Shaman":
            continue
        gid = ev.get("abilityGameID")
        if gid == 1:
            swings_by_player.setdefault(sid, []).append(
                (ev["timestamp"], ev.get("amount", 0) or 0)
            )
        elif ability_names.get(gid) == "Windfury Attack":
            wf_ts_by_player.setdefault(sid, []).append(ev["timestamp"])

    # Collect per-player Flurry buff events.
    flurry_by_player: dict[int, list[dict]] = {}
    for ev in buffs:
        if ev.get("type") not in ("applybuff", "removebuff", "refreshbuff"):
            continue
        tid = ev.get("targetID")
        if tid not in players_by_id:
            continue
        if ability_names.get(ev.get("abilityGameID")) == "Flurry":
            flurry_by_player.setdefault(tid, []).append(ev)

    out: dict[str, Any] = {}
    for sid, swings in swings_by_player.items():
        if len(swings) < _MIN_SWINGS or (len(swings) / duration_min) < _MIN_SWINGS_PER_MIN:
            continue
        swings.sort(key=lambda s: s[0])
        pairs, lone = _pair_swings(swings)
        total = len(swings)
        pct_synced = round(2 * len(pairs) / total * 100, 1) if total else 0.0

        # Offset shape (INFERRED, not graded).
        offsets = [b[0] - a[0] for a, b in pairs]
        buckets = {name: 0 for name, _, _ in _OFFSET_BUCKETS}
        for off in offsets:
            for name, lo, hi in _OFFSET_BUCKETS:
                if lo <= off < hi or (hi == SYNC_WINDOW_MS and off == hi):
                    buckets[name] += 1
                    break
        pair_ct = len(pairs)
        offset_buckets = {
            name: round(cnt / pair_ct * 100, 0) if pair_ct else 0
            for name, cnt in buckets.items()
        }
        median_offset = round(statistics.median(offsets)) if offsets else 0

        # Main-hand lead read: within a pair the bigger hit is inferred to be the
        # main hand (off-hand takes a damage penalty). Only pairs where both hits
        # connected are usable.
        lead_pairs = [(a, b) for a, b in pairs if a[1] > 0 and b[1] > 0]
        mh_leads = sum(1 for a, b in lead_pairs if a[1] > b[1])
        mh_leads_pct = round(mh_leads / len(lead_pairs) * 100) if lead_pairs else 0

        flurry_uptime = _flurry_uptime_pct(
            sorted(flurry_by_player.get(sid, []), key=lambda e: e["timestamp"]),
            start,
            end,
        )
        wf_count = _count_wf_procs(wf_ts_by_player.get(sid, []))
        wf_per_min = round(wf_count / duration_min, 1) if duration_min else 0.0
        wf_gap_sec = round(duration_sec / wf_count, 1) if wf_count else None

        name = players_by_id[sid]["name"]
        out[name] = {
            "score": round(pct_synced),
            "pct_synced": pct_synced,
            "swings": total,
            "synced_pairs": pair_ct,
            "lone_swings": lone,
            "flurry_uptime": round(flurry_uptime, 1) if flurry_uptime is not None else None,
            "wf_procs": wf_count,
            "wf_per_min": wf_per_min,
            "wf_gap_sec": wf_gap_sec,
            "median_offset_ms": median_offset,
            "offset_buckets": offset_buckets,
            "mh_leads_pct": mh_leads_pct,
        }
    return out
