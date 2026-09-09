"""Reconstruct maintained raid debuff uptime on encounter bosses."""

from __future__ import annotations

from collections import defaultdict

from backend.analysis.utils import actor_name, spell_name


TRACKED_DEBUFFS = {
    "Annihilator",
    "Curse of Elements",
    "Curse of Recklessness",
    "Curse of Shadows",
    "Curse of Tongues",
    "Curse of Weakness",
    "Demoralizing Roar",
    "Demoralizing Shout",
    "Expose Armor",
    "Fire Vulnerability",
    "Faerie Fire",
    "Faerie Fire (Feral)",
    "Gift of Arthas",
    "Hunter's Mark",
    "Improved Scorch",
    "Insect Swarm",
    "Judgement of Light",
    "Judgement of the Crusader",
    "Judgement of Wisdom",
    "Scorpid Sting",
    "Screech",
    "Sunder Armor",
    "Thunder Clap",
}

FULL_STACKS = {
    "Fire Vulnerability": 5,
    "Sunder Armor": 5,
}

DEBUFF_CATEGORIES = {
    "Demoralizing Roar": "Attack Power Reduction",
    "Demoralizing Shout": "Attack Power Reduction",
    "Screech": "Attack Power Reduction",
    "Expose Armor": "Major Armor Reduction",
    "Sunder Armor": "Major Armor Reduction",
    "Faerie Fire": "Faerie Fire",
    "Faerie Fire (Feral)": "Faerie Fire",
}

TARGET_UPTIME = {
    "Annihilator": 80,
    "Major Armor Reduction": 90,
}

REQUIRED_CATEGORIES = {
    "Attack Power Reduction": {
        "spells": ["Demoralizing Roar", "Demoralizing Shout", "Screech"],
        "target_uptime_pct": 95,
    },
}

# Encounters whose report name is not the name of an attackable boss unit.
BOSS_TARGET_ALIASES = {
    "Fathom-Lord Karathress": {
        "Fathom-Guard Caribdis",
        "Fathom-Guard Sharkkis",
        "Fathom-Guard Tidalvess",
    },
    "High King Maulgar": {
        "Blindeye the Seer",
        "Kiggler the Crazed",
        "Krosh Firehand",
        "Olm the Summoner",
    },
    "Kael'thas Sunstrider": {
        "Grand Astromancer Capernian",
        "Lord Sanguinar",
        "Master Engineer Telonicus",
        "Thaladred the Darkener",
    },
    "The Illidari Council": {
        "Gathios the Shatterer",
        "High Nethermancer Zerevor",
        "Lady Malande",
        "Veras Darkshadow",
    },
    "Reliquary of Souls": {
        "Essence of Suffering",
        "Essence of Desire",
        "Essence of Anger",
    },
}

_APPLY_TYPES = {"applydebuff"}
_REFRESH_TYPES = {"refreshdebuff"}
_REMOVE_TYPES = {"removedebuff"}
_APPLY_STACK_TYPES = {"applydebuffstack"}
_REMOVE_STACK_TYPES = {"removedebuffstack"}
_EVENT_TYPES = (
    _APPLY_TYPES | _REFRESH_TYPES | _REMOVE_TYPES
    | _APPLY_STACK_TYPES | _REMOVE_STACK_TYPES
)

_ACTIVITY_GAP_MS = 15_000
_MIN_LAPSE_MS = 1_000


def compute_boss_debuffs(
    fight: dict,
    actors_by_id: dict,
    players_by_id: dict,
    ability_names: dict,
    events: list[dict],
    damage_events: list[dict],
) -> tuple[list[dict], list[str]]:
    """Return uptime and lapse details for maintained debuffs on boss targets."""
    start = fight["startTime"]
    end = fight["endTime"]
    if end <= start:
        return [], []

    boss_name = fight.get("name", "")
    target_names = {boss_name}
    target_names.update(BOSS_TARGET_ALIASES.get(boss_name, set()))

    target_damage_times: dict[str, list[int]] = defaultdict(list)
    for event in damage_events:
        if event.get("sourceID") not in players_by_id:
            continue
        target_name = actor_name(event.get("targetID"), actors_by_id)
        if target_name not in target_names:
            continue
        timestamp = event.get("timestamp")
        if timestamp is None:
            continue
        target_damage_times[target_name].append(timestamp)

    target_windows = {
        target: _build_activity_windows(timestamps, start, end)
        for target, timestamps in target_damage_times.items()
    }

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        event_type = event.get("type")
        if event_type not in _EVENT_TYPES:
            continue
        if event.get("sourceID") not in players_by_id:
            continue

        target_name = actor_name(event.get("targetID"), actors_by_id)
        if target_name not in target_names:
            continue

        name = spell_name(event, ability_names)
        if name not in TRACKED_DEBUFFS:
            continue

        grouped[(target_name, name)].append(event)

    results = []
    for (target, name), aura_events in grouped.items():
        activity_windows = target_windows.get(target)
        if not activity_windows:
            continue
        duration = sum((window_end - window_start) / 1000 for window_start, window_end in activity_windows)
        if duration <= 0:
            continue

        aura_events.sort(key=lambda event: event.get("timestamp", start))
        active_since = None
        intervals = []
        full_since = None
        full_intervals = []
        desired_stacks = FULL_STACKS.get(name)
        current_stacks = 0
        max_stacks = 0
        saw_stack_data = False
        sources = set()

        # A first refresh/removal means the aura was already active when logging began.
        if aura_events[0].get("type") in _REFRESH_TYPES | _REMOVE_TYPES | _REMOVE_STACK_TYPES:
            active_since = start

        for event in aura_events:
            event_type = event.get("type")
            timestamp = min(max(event.get("timestamp", start), start), end)
            source_id = event.get("sourceID")
            if source_id in players_by_id:
                sources.add(players_by_id[source_id]["name"])

            if event_type in _APPLY_TYPES:
                if active_since is None:
                    active_since = timestamp
                current_stacks = int(event.get("stack") or 1)
            elif event_type in _APPLY_STACK_TYPES:
                saw_stack_data = True
                if active_since is None:
                    active_since = timestamp
                current_stacks = int(event.get("stack") or current_stacks + 1)
            elif event_type in _REFRESH_TYPES:
                if active_since is None:
                    active_since = start
                if event.get("stack") is not None:
                    saw_stack_data = True
                    current_stacks = int(event["stack"])
                elif current_stacks == 0:
                    current_stacks = 1
            elif event_type in _REMOVE_STACK_TYPES:
                saw_stack_data = True
                if event.get("stack") is not None:
                    current_stacks = int(event["stack"])
                else:
                    current_stacks = max(current_stacks - 1, 1)
            elif event_type in _REMOVE_TYPES and active_since is not None:
                intervals.append((active_since, timestamp))
                active_since = None
                current_stacks = 0

            max_stacks = max(max_stacks, current_stacks)
            if desired_stacks:
                at_full_strength = active_since is not None and current_stacks >= desired_stacks
                if at_full_strength and full_since is None:
                    full_since = timestamp
                elif not at_full_strength and full_since is not None:
                    full_intervals.append((full_since, timestamp))
                    full_since = None

        if active_since is not None:
            intervals.append((active_since, end))
        if full_since is not None:
            full_intervals.append((full_since, end))

        intervals = _intersect_intervals(_merge_intervals(intervals), activity_windows)
        full_intervals = _intersect_intervals(_merge_intervals(full_intervals), activity_windows)
        effective_intervals = full_intervals if desired_stacks and saw_stack_data else intervals
        gaps = [
            gap
            for window_start, window_end in activity_windows
            for gap in _find_gaps(effective_intervals, window_start, window_end)
        ]
        active_seconds = sum((interval_end - interval_start) / 1000 for interval_start, interval_end in intervals)
        effective_seconds = sum((interval_end - interval_start) / 1000 for interval_start, interval_end in effective_intervals)
        first_window_start = activity_windows[0][0]
        initial_delay = gaps[0][1] - gaps[0][0] if gaps and gaps[0][0] == first_window_start else 0
        lapse_gaps = [
            gap for gap in gaps
            if gap[0] != first_window_start and gap[1] - gap[0] >= _MIN_LAPSE_MS
        ]
        full_uptime_pct = None
        if desired_stacks and saw_stack_data:
            full_uptime_pct = round(effective_seconds / duration * 100, 1)

        results.append({
            "spell": name,
            "spells": [name],
            "category": DEBUFF_CATEGORIES.get(name),
            "target_uptime_pct": TARGET_UPTIME.get(
                DEBUFF_CATEGORIES.get(name) or name, 95,
            ),
            "target": target,
            "sources": sorted(sources),
            "uptime_pct": round(active_seconds / duration * 100, 1),
            "effective_uptime_pct": round(effective_seconds / duration * 100, 1),
            "full_uptime_pct": full_uptime_pct,
            "max_stacks": max_stacks if desired_stacks else None,
            "required_stacks": desired_stacks,
            "active_sec": round(active_seconds, 1),
            "downtime_sec": round(duration - effective_seconds, 1),
            "initial_delay_sec": round(initial_delay / 1000, 1),
            "longest_gap_sec": round(max(((b - a) / 1000 for a, b in gaps), default=0), 1),
            "lapse_count": len(lapse_gaps),
            "drops": [
                {
                    "at_sec": round((gap_start - start) / 1000, 1),
                    "duration_sec": round((gap_end - gap_start) / 1000, 1),
                }
                for gap_start, gap_end in lapse_gaps
            ],
            "_activity_windows": activity_windows,
            "_active_intervals": intervals,
            "_effective_intervals": effective_intervals,
        })

    results = _combine_category_rows(results, start)
    observed_keys = {
        (row["target"], row.get("category") or row["spell"])
        for row in results
    }
    for target in target_windows:
        for category, policy in REQUIRED_CATEGORIES.items():
            if (target, category) in observed_keys:
                continue
            results.append({
                "spell": " / ".join(policy["spells"]),
                "spells": list(policy["spells"]),
                "category": category,
                "target": target,
                "sources": [],
                "target_uptime_pct": policy["target_uptime_pct"],
                "uptime_pct": 0.0,
                "effective_uptime_pct": 0.0,
                "full_uptime_pct": None,
                "max_stacks": None,
                "required_stacks": None,
                "active_sec": 0.0,
                "downtime_sec": round(sum(
                    (window_end - window_start) / 1000
                    for window_start, window_end in target_windows[target]
                ), 1),
                "initial_delay_sec": round(
                    (target_windows[target][-1][1] - target_windows[target][0][0]) / 1000,
                    1,
                ),
                "longest_gap_sec": round(max(
                    (window_end - window_start) / 1000
                    for window_start, window_end in target_windows[target]
                ), 1),
                "lapse_count": 0,
                "drops": [],
                "missing": True,
            })
    return (
        sorted(results, key=lambda row: (row["effective_uptime_pct"], row["spell"], row["target"])),
        sorted(target_windows),
    )


def _build_activity_windows(
    timestamps: list[int],
    fight_start: int,
    fight_end: int,
) -> list[tuple[int, int]]:
    """Split target activity around long periods with no player damage."""
    if not timestamps:
        return []
    ordered = sorted(set(min(max(timestamp, fight_start), fight_end) for timestamp in timestamps))
    windows = []
    window_start = ordered[0]
    previous = ordered[0]
    for timestamp in ordered[1:]:
        if timestamp - previous > _ACTIVITY_GAP_MS:
            windows.append((window_start, min(previous + 1000, fight_end)))
            window_start = timestamp
        previous = timestamp
    windows.append((window_start, min(previous + 1000, fight_end)))
    return [(start, end) for start, end in windows if end > start]


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _find_gaps(intervals: list[tuple[int, int]], start: int, end: int) -> list[tuple[int, int]]:
    gaps = []
    cursor = start
    for interval_start, interval_end in intervals:
        if interval_end <= start:
            continue
        if interval_start >= end:
            break
        overlap_start = max(interval_start, start)
        overlap_end = min(interval_end, end)
        if overlap_start > cursor:
            gaps.append((cursor, overlap_start))
        cursor = max(cursor, overlap_end)
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


def _intersect_intervals(
    intervals: list[tuple[int, int]],
    windows: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    intersections = []
    for interval_start, interval_end in intervals:
        for window_start, window_end in windows:
            overlap_start = max(interval_start, window_start)
            overlap_end = min(interval_end, window_end)
            if overlap_end > overlap_start:
                intersections.append((overlap_start, overlap_end))
    return _merge_intervals(intersections)


def _combine_category_rows(rows: list[dict], fight_start: int) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["target"], row.get("category") or row["spell"])].append(row)

    combined = []
    for (_, category), category_rows in grouped.items():
        if len(category_rows) == 1 and not category_rows[0].get("category"):
            row = category_rows[0]
            row.pop("_activity_windows", None)
            row.pop("_active_intervals", None)
            row.pop("_effective_intervals", None)
            combined.append(row)
            continue

        activity_windows = category_rows[0]["_activity_windows"]
        active_intervals = _merge_intervals([
            interval
            for row in category_rows
            for interval in row["_active_intervals"]
        ])
        effective_intervals = _merge_intervals([
            interval
            for row in category_rows
            for interval in row["_effective_intervals"]
        ])
        duration = sum((end - start) / 1000 for start, end in activity_windows)
        active_seconds = sum((end - start) / 1000 for start, end in active_intervals)
        effective_seconds = sum((end - start) / 1000 for start, end in effective_intervals)
        gaps = [
            gap
            for window_start, window_end in activity_windows
            for gap in _find_gaps(effective_intervals, window_start, window_end)
        ]
        first_window_start = activity_windows[0][0]
        initial_delay = gaps[0][1] - gaps[0][0] if gaps and gaps[0][0] == first_window_start else 0
        lapse_gaps = [
            gap for gap in gaps
            if gap[0] != first_window_start and gap[1] - gap[0] >= _MIN_LAPSE_MS
        ]
        spells = sorted({spell for row in category_rows for spell in row["spells"]})
        required_stacks = max((row.get("required_stacks") or 0 for row in category_rows), default=0) or None
        max_stacks = max((row.get("max_stacks") or 0 for row in category_rows), default=0) or None

        combined.append({
            "spell": " / ".join(spells),
            "spells": spells,
            "category": category,
            "target_uptime_pct": TARGET_UPTIME.get(category, 95),
            "target": category_rows[0]["target"],
            "sources": sorted({source for row in category_rows for source in row["sources"]}),
            "uptime_pct": round(active_seconds / duration * 100, 1),
            "effective_uptime_pct": round(effective_seconds / duration * 100, 1),
            "full_uptime_pct": (
                round(effective_seconds / duration * 100, 1)
                if required_stacks else None
            ),
            "max_stacks": max_stacks,
            "required_stacks": required_stacks,
            "active_sec": round(active_seconds, 1),
            "downtime_sec": round(duration - effective_seconds, 1),
            "initial_delay_sec": round(initial_delay / 1000, 1),
            "longest_gap_sec": round(max(((end - start) / 1000 for start, end in gaps), default=0), 1),
            "lapse_count": len(lapse_gaps),
            "drops": [
                {
                    "at_sec": round((gap_start - fight_start) / 1000, 1),
                    "duration_sec": round((gap_end - gap_start) / 1000, 1),
                }
                for gap_start, gap_end in lapse_gaps
            ],
        })
    return combined
