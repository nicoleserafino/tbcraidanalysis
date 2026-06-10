#!/usr/bin/env python3
"""Compare two WarcraftLogs v1 raid reports and generate a comparison payload."""

from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

API_BASE = "https://fresh.warcraftlogs.com/v1"
REQUEST_DELAY_SEC = 0.5

PLAYER_CLASSES = {
    "Warrior", "Paladin", "Hunter", "Rogue", "Priest",
    "Shaman", "Mage", "Warlock", "Druid",
}

MAJOR_COOLDOWNS = {
    "Bloodlust", "Heroism", "Innervate", "Rebirth",
    "Soulstone Resurrection", "Divine Shield", "Lay on Hands",
    "Shield Wall", "Last Stand", "Recklessness",
}

CONSUMABLE_BUFFS = {
    # Flasks
    "Flask of Pure Death", "Flask of Blinding Light", "Flask of Supreme Power",
    "Flask of Relentless Assault", "Flask of Mighty Versatility",
    "Flask of Fortification", "Flask of the Titans",
    "Unstable Flask of the Bandit", "Unstable Flask of the Elder",
    "Unstable Flask of the Beast", "Unstable Flask of the Physician",
    "Unstable Flask of the Soldier", "Unstable Flask of the Sorcerer",
    # Food
    "Well Fed",
    # Weapon oils / stones
    "Brilliant Wizard Oil", "Superior Wizard Oil",
    "Adamantite Weightstone", "Adamantite Sharpening Stone",
    # Battle/Guardian Elixirs
    "Elixir of Major Agility", "Elixir of Major Firepower",
    "Elixir of Major Shadow Power", "Elixir of Healing Power",
    "Elixir of Draenic Wisdom", "Elixir of Major Mageblood",
    "Elixir of Major Strength", "Elixir of Mastery",
    "Elixir of Major Fortitude", "Elixir of Major Defense",
    # Potions (show as used-during-fight)
    "Haste Potion", "Destruction Potion", "Super Mana Potion",
    "Ironshield Potion", "Free Action Potion",
}

RAID_BUFFS = {
    "Arcane Brilliance", "Mark of the Wild", "Gift of the Wild",
    "Power Word: Fortitude", "Prayer of Fortitude",
    "Shadow Protection", "Prayer of Shadow Protection",
    "Divine Spirit", "Prayer of Spirit",
    "Blessing of Kings", "Greater Blessing of Kings",
    "Blessing of Might", "Greater Blessing of Might",
    "Blessing of Wisdom", "Greater Blessing of Wisdom",
    "Blessing of Salvation", "Greater Blessing of Salvation",
    "Blessing of Light", "Greater Blessing of Light",
    "Windfury Totem", "Grace of Air Totem", "Strength of Earth Totem",
    "Mana Spring Totem", "Wrath of Air Totem", "Totem of Wrath",
    "Moonkin Aura", "Leader of the Pack", "Trueshot Aura",
    "Ferocious Inspiration", "Unleashed Rage", "Vampiric Embrace",
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


def fmt_duration(ms: int) -> str:
    """Format milliseconds as M:SS or H:MM:SS."""
    total_sec = ms / 1000
    if total_sec >= 3600:
        h = int(total_sec // 3600)
        m = int((total_sec % 3600) // 60)
        s = int(total_sec % 60)
        return f"{h}:{m:02d}:{s:02d}"
    m = int(total_sec // 60)
    s = int(total_sec % 60)
    return f"{m}:{s:02d}"


def role_from_icon(player_class: str, icon: str | None) -> str:
    icon = icon or ""
    if "-Holy" in icon or "-Restoration" in icon or "-Discipline" in icon:
        return "Healer"
    if "-Protection" in icon or "-Guardian" in icon:
        return "Tank"
    if player_class in {"Mage", "Warlock", "Rogue", "Hunter"}:
        return "DPS"
    dps_specs = ("-Shadow", "-Balance", "-Feral", "-Enhancement", "-Elemental", "-Retribution",
                 "-Arms", "-Fury", "-Combat", "-Assassination", "-Subtlety", "-Frost", "-Fire",
                 "-Arcane", "-Marksmanship", "-BeastMastery", "-Survival", "-Affliction",
                 "-Demonology", "-Destruction")
    if any(spec in icon for spec in dps_specs):
        return "DPS"
    return "DPS"


# ------------------------------------------------------------------
# Data fetching per report
# ------------------------------------------------------------------

def fetch_report_data(client: WCLClient, report_url: str) -> dict[str, Any]:
    """Fetch all comparison-relevant data for one report."""
    report_id = extract_report_id(report_url)
    print(f"\n{'='*60}")
    print(f"Fetching report: {report_id}")
    print(f"{'='*60}")

    fights_payload = client.get(f"/report/fights/{report_id}")
    all_fights = fights_payload.get("fights", [])
    boss_fights = [f for f in all_fights if f.get("boss", 0) > 0]
    trash_fights = [f for f in all_fights if f.get("boss", 0) == 0 and f.get("name") != "Unknown"]

    friendlies = fights_payload.get("friendlies", [])
    players_by_id: dict[int, dict[str, Any]] = {}
    for actor in friendlies:
        if actor.get("type") in PLAYER_CLASSES:
            players_by_id[actor["id"]] = actor

    report_start_ms = int(fights_payload.get("start", 0))
    report_end_ms = int(fights_payload.get("end", 0))
    title = fights_payload.get("title", "")
    owner = fights_payload.get("owner", "")

    # Build roster with roles
    roster: dict[str, dict[str, str]] = {}
    for actor in friendlies:
        if actor.get("type") not in PLAYER_CLASSES:
            continue
        name = actor["name"]
        player_class = actor.get("type", "Unknown")
        role = role_from_icon(player_class, actor.get("icon"))
        roster[name] = {"class": player_class, "role": role, "icon": actor.get("icon", "")}

    # Per-boss data
    bosses: list[dict[str, Any]] = []
    boss_order: list[str] = []

    for fight in boss_fights:
        if not fight.get("kill"):
            continue
        boss_name = fight["name"]
        # Only keep the fastest kill per boss
        existing = next((b for b in bosses if b["name"] == boss_name), None)
        duration_ms = fight["end_time"] - fight["start_time"]
        if existing and existing["duration_ms"] <= duration_ms:
            continue
        if existing:
            bosses.remove(existing)

        start = fight["start_time"]
        end = fight["end_time"]

        # Damage done table
        print(f"  {boss_name}: fetching damage-done...")
        dmg_table = client.get(f"/report/tables/damage-done/{report_id}", start=start, end=end)
        total_damage = 0
        player_damage: dict[str, int] = {}
        for entry in dmg_table.get("entries", []):
            pid = entry.get("id")
            if pid in players_by_id:
                player_name = players_by_id[pid]["name"]
                dmg = int(entry.get("total", 0))
                player_damage[player_name] = dmg
                total_damage += dmg

        # Healing table
        print(f"  {boss_name}: fetching healing...")
        heal_table = client.get(f"/report/tables/healing/{report_id}", start=start, end=end)
        total_healing = 0
        total_overheal = 0
        player_healing: dict[str, dict[str, int]] = {}
        for entry in heal_table.get("entries", []):
            pid = entry.get("id")
            if pid in players_by_id:
                player_name = players_by_id[pid]["name"]
                healing = int(entry.get("total", 0))
                overheal = int(entry.get("overheal", 0))
                player_healing[player_name] = {"healing": healing, "overheal": overheal}
                total_healing += healing
                total_overheal += overheal

        # Buffs table
        print(f"  {boss_name}: fetching buffs...")
        buff_table = client.get(f"/report/tables/buffs/{report_id}", start=start, end=end)
        buffs_present: set[str] = set()
        for entry in buff_table.get("auras", []):
            buff_name = entry.get("name", "")
            if buff_name in CONSUMABLE_BUFFS or buff_name in RAID_BUFFS:
                buffs_present.add(buff_name)

        # Major cooldown casts (Bloodlust/Heroism timing)
        print(f"  {boss_name}: fetching cooldown casts...")
        cooldown_events: list[dict[str, Any]] = []
        for cd_spell in ["Bloodlust", "Heroism"]:
            cd_casts = client.get_paginated_events(
                "casts", report_id, start=start, end=end,
                filter=f'ability.name="{cd_spell}"'
            )
            for event in cd_casts:
                if event.get("type") == "cast":
                    cooldown_events.append({
                        "spell": cd_spell,
                        "time_sec": round((event["timestamp"] - start) / 1000, 1),
                        "time_pct": round((event["timestamp"] - start) / (end - start) * 100, 1),
                    })

        duration_sec = duration_ms / 1000
        raid_dps = round(total_damage / duration_sec) if duration_sec > 0 else 0
        raid_hps = round(total_healing / duration_sec) if duration_sec > 0 else 0
        overheal_pct = round(total_overheal / (total_healing + total_overheal) * 100, 1) if (total_healing + total_overheal) > 0 else 0

        boss_data = {
            "name": boss_name,
            "fight_id": fight["id"],
            "duration_ms": duration_ms,
            "duration_str": fmt_duration(duration_ms),
            "start_time": fight["start_time"],
            "end_time": fight["end_time"],
            "total_damage": total_damage,
            "raid_dps": raid_dps,
            "total_healing": total_healing,
            "total_overheal": total_overheal,
            "overheal_pct": overheal_pct,
            "raid_hps": raid_hps,
            "player_damage": dict(sorted(player_damage.items(), key=lambda x: -x[1])),
            "player_healing": {k: v for k, v in sorted(player_healing.items(), key=lambda x: -x[1]["healing"])},
            "buffs_present": sorted(buffs_present),
            "cooldowns": cooldown_events,
        }
        bosses.append(boss_data)
        if boss_name not in boss_order:
            boss_order.append(boss_name)

    # Sort bosses by kill order (start_time)
    bosses.sort(key=lambda b: b["start_time"])
    boss_order = [b["name"] for b in bosses]

    # Wipe/pull counts per boss
    boss_pull_counts: dict[str, dict[str, int]] = {}
    for fight in boss_fights:
        bname = fight["name"]
        if bname not in boss_pull_counts:
            boss_pull_counts[bname] = {"total_pulls": 0, "kills": 0, "wipes": 0}
        boss_pull_counts[bname]["total_pulls"] += 1
        if fight.get("kill"):
            boss_pull_counts[bname]["kills"] += 1
        else:
            boss_pull_counts[bname]["wipes"] += 1

    # Trash analysis
    trash_data: dict[str, Any] = {"logged": False, "total_time_ms": 0, "pull_count": 0, "deaths": 0}
    if trash_fights:
        trash_data["logged"] = True
        trash_data["pull_count"] = len(trash_fights)
        trash_total = sum(f["end_time"] - f["start_time"] for f in trash_fights)
        trash_data["total_time_ms"] = trash_total
        trash_data["total_time_str"] = fmt_duration(trash_total)

    # Pacing: time between boss kills
    pacing: list[dict[str, Any]] = []
    for i, boss in enumerate(bosses):
        entry: dict[str, Any] = {
            "boss": boss["name"],
            "kill_time_ms": boss["end_time"],
            "fight_duration_ms": boss["duration_ms"],
        }
        if i > 0:
            gap_ms = boss["start_time"] - bosses[i - 1]["end_time"]
            entry["gap_from_prev_ms"] = gap_ms
            entry["gap_from_prev_str"] = fmt_duration(max(0, gap_ms))
        pacing.append(entry)

    # Total raid time
    if bosses:
        # From first event to last boss kill
        first_event_ms = min(f["start_time"] for f in all_fights) if all_fights else bosses[0]["start_time"]
        last_kill_ms = bosses[-1]["end_time"]
        total_raid_ms = last_kill_ms - first_event_ms
    else:
        total_raid_ms = report_end_ms - report_start_ms

    # Inter-boss gap total (non-combat time)
    total_gap_ms = sum(p.get("gap_from_prev_ms", 0) for p in pacing if p.get("gap_from_prev_ms", 0) > 0)

    # Deaths per boss (all pulls)
    deaths_per_boss: dict[str, int] = defaultdict(int)
    for fight in boss_fights:
        if fight.get("fightPercentage") is not None or fight.get("kill"):
            deaths_per_boss[fight["name"]] += len(fight.get("deaths", []) if "deaths" in fight else [])

    return {
        "report_id": report_id,
        "url": report_url,
        "title": title,
        "owner": owner,
        "report_start_ms": report_start_ms,
        "total_raid_ms": total_raid_ms,
        "total_raid_str": fmt_duration(total_raid_ms),
        "total_gap_ms": total_gap_ms,
        "total_gap_str": fmt_duration(total_gap_ms),
        "roster": roster,
        "bosses": bosses,
        "boss_order": boss_order,
        "boss_pull_counts": boss_pull_counts,
        "trash": trash_data,
        "pacing": pacing,
    }


# ------------------------------------------------------------------
# Comparison logic
# ------------------------------------------------------------------

def compare_reports(ours: dict[str, Any], theirs: dict[str, Any]) -> dict[str, Any]:
    """Build the comparison payload from two fetched reports."""

    # Comp comparison
    def comp_summary(roster: dict) -> dict[str, Any]:
        role_counts = {"Tank": 0, "Healer": 0, "DPS": 0}
        class_counts: dict[str, int] = defaultdict(int)
        for info in roster.values():
            role_counts[info.get("role", "DPS")] += 1
            class_counts[info["class"]] += 1
        return {"total": len(roster), "roles": role_counts, "classes": dict(sorted(class_counts.items()))}

    our_comp = comp_summary(ours["roster"])
    their_comp = comp_summary(theirs["roster"])

    # Boss-by-boss comparison
    boss_comparison: list[dict[str, Any]] = []
    all_boss_names = []
    for name in ours["boss_order"]:
        if name not in all_boss_names:
            all_boss_names.append(name)
    for name in theirs["boss_order"]:
        if name not in all_boss_names:
            all_boss_names.append(name)

    for boss_name in all_boss_names:
        our_boss = next((b for b in ours["bosses"] if b["name"] == boss_name), None)
        their_boss = next((b for b in theirs["bosses"] if b["name"] == boss_name), None)

        entry: dict[str, Any] = {"name": boss_name}

        if our_boss:
            entry["ours"] = {
                "duration_ms": our_boss["duration_ms"],
                "duration_str": our_boss["duration_str"],
                "raid_dps": our_boss["raid_dps"],
                "raid_hps": our_boss["raid_hps"],
                "overheal_pct": our_boss["overheal_pct"],
                "buffs": our_boss["buffs_present"],
                "cooldowns": our_boss["cooldowns"],
                "top_dps": list(our_boss["player_damage"].items())[:5],
                "top_healers": [(k, v["healing"]) for k, v in list(our_boss["player_healing"].items())[:5]],
                "pulls": ours["boss_pull_counts"].get(boss_name, {}),
                "all_player_damage": our_boss["player_damage"],
                "all_player_healing": our_boss["player_healing"],
            }
        if their_boss:
            entry["theirs"] = {
                "duration_ms": their_boss["duration_ms"],
                "duration_str": their_boss["duration_str"],
                "raid_dps": their_boss["raid_dps"],
                "raid_hps": their_boss["raid_hps"],
                "overheal_pct": their_boss["overheal_pct"],
                "buffs": their_boss["buffs_present"],
                "cooldowns": their_boss["cooldowns"],
                "top_dps": list(their_boss["player_damage"].items())[:5],
                "top_healers": [(k, v["healing"]) for k, v in list(their_boss["player_healing"].items())[:5]],
                "pulls": theirs["boss_pull_counts"].get(boss_name, {}),
                "all_player_damage": their_boss["player_damage"],
                "all_player_healing": their_boss["player_healing"],
            }

        # Deltas
        if our_boss and their_boss:
            time_delta = our_boss["duration_ms"] - their_boss["duration_ms"]
            entry["delta"] = {
                "time_ms": time_delta,
                "time_str": f"{'+' if time_delta > 0 else ''}{fmt_duration(abs(time_delta))}",
                "time_favorable": time_delta < 0,  # negative = we're faster
                "dps_diff": our_boss["raid_dps"] - their_boss["raid_dps"],
                "hps_diff": our_boss["raid_hps"] - their_boss["raid_hps"],
                "overheal_diff": round(our_boss["overheal_pct"] - their_boss["overheal_pct"], 1),
            }
            # Buffs they have that we don't
            entry["delta"]["missing_buffs"] = sorted(set(their_boss["buffs_present"]) - set(our_boss["buffs_present"]))
            entry["delta"]["extra_buffs"] = sorted(set(our_boss["buffs_present"]) - set(their_boss["buffs_present"]))

        boss_comparison.append(entry)

    # Pacing comparison
    pacing_comparison: dict[str, Any] = {
        "ours": {
            "total_raid_ms": ours["total_raid_ms"],
            "total_raid_str": ours["total_raid_str"],
            "total_gap_ms": ours["total_gap_ms"],
            "total_gap_str": ours["total_gap_str"],
            "pacing": ours["pacing"],
            "trash": ours["trash"],
        },
        "theirs": {
            "total_raid_ms": theirs["total_raid_ms"],
            "total_raid_str": theirs["total_raid_str"],
            "total_gap_ms": theirs["total_gap_ms"],
            "total_gap_str": theirs["total_gap_str"],
            "pacing": theirs["pacing"],
            "trash": theirs["trash"],
        },
        "delta_total_ms": ours["total_raid_ms"] - theirs["total_raid_ms"],
        "delta_gap_ms": ours["total_gap_ms"] - theirs["total_gap_ms"],
    }

    # Generate recommendations
    recommendations = generate_recommendations(ours, theirs, boss_comparison, pacing_comparison)

    return {
        "ours": {
            "report_id": ours["report_id"],
            "url": ours["url"],
            "title": ours["title"],
            "owner": ours["owner"],
        },
        "theirs": {
            "report_id": theirs["report_id"],
            "url": theirs["url"],
            "title": theirs["title"],
            "owner": theirs["owner"],
        },
        "comp": {"ours": our_comp, "theirs": their_comp},
        "roster": {"ours": ours["roster"], "theirs": theirs["roster"]},
        "bosses": boss_comparison,
        "pacing": pacing_comparison,
        "recommendations": recommendations,
    }


def generate_recommendations(ours: dict, theirs: dict, boss_comparison: list, pacing: dict) -> list[dict[str, str]]:
    """Auto-generate actionable tips from the biggest deltas."""
    tips: list[dict[str, str]] = []

    # Pacing
    gap_delta = pacing["delta_gap_ms"]
    if gap_delta > 30000:  # More than 30s slower on non-combat time
        tips.append({
            "category": "Pacing",
            "severity": "high",
            "title": f"Non-combat time is {fmt_duration(gap_delta)} longer",
            "detail": "Time between boss kills (trash, running, rebuffing) is significantly higher. Consider: pre-positioning, faster rebuffs, pulling trash while buffing, or assigning a pull leader.",
        })

    # Per-boss time savings
    for boss in boss_comparison:
        delta = boss.get("delta")
        if not delta:
            continue
        if delta["time_ms"] > 15000:  # We're 15s+ slower
            tips.append({
                "category": "Kill Speed",
                "severity": "high" if delta["time_ms"] > 30000 else "medium",
                "title": f"{boss['name']}: {fmt_duration(delta['time_ms'])} slower",
                "detail": f"Their raid DPS was {delta['dps_diff']:+,} compared to yours. "
                         + (f"Missing buffs: {', '.join(delta['missing_buffs'])}. " if delta.get("missing_buffs") else "")
                         + (f"Their overheal was {delta['overheal_diff']:+.1f}% different." if abs(delta.get("overheal_diff", 0)) > 5 else ""),
            })

    # Comp differences
    our_comp = ours.get("roster", {})
    their_comp = theirs.get("roster", {})
    our_roles = {"Tank": 0, "Healer": 0, "DPS": 0}
    their_roles = {"Tank": 0, "Healer": 0, "DPS": 0}
    for info in our_comp.values():
        our_roles[info.get("role", "DPS")] += 1
    for info in their_comp.values():
        their_roles[info.get("role", "DPS")] += 1

    healer_diff = our_roles["Healer"] - their_roles["Healer"]
    if healer_diff > 0:
        tips.append({
            "category": "Composition",
            "severity": "medium",
            "title": f"Running {healer_diff} more healer(s) than them",
            "detail": "Extra healers reduce raid DPS. If healing is comfortable, consider swapping a healer to a DPS spec for faster kills.",
        })

    # Overheal
    for boss in boss_comparison:
        delta = boss.get("delta")
        if delta and delta.get("overheal_diff", 0) > 10:
            tips.append({
                "category": "Healing Efficiency",
                "severity": "medium",
                "title": f"{boss['name']}: {delta['overheal_diff']:.1f}% more overheal",
                "detail": "High overheal suggests healers could downrank, use fewer GCDs on healing, or one healer could swap to DPS.",
            })
            break  # Only flag once

    # Cooldown timing
    for boss in boss_comparison:
        ours_cds = boss.get("ours", {}).get("cooldowns", [])
        theirs_cds = boss.get("theirs", {}).get("cooldowns", [])
        our_lust = [cd for cd in ours_cds if cd["spell"] in ("Bloodlust", "Heroism")]
        their_lust = [cd for cd in theirs_cds if cd["spell"] in ("Bloodlust", "Heroism")]
        if their_lust and not our_lust:
            tips.append({
                "category": "Cooldowns",
                "severity": "high",
                "title": f"{boss['name']}: They used Bloodlust/Heroism, you didn't",
                "detail": "Bloodlust/Heroism provides 30% haste to the group. Consider using it on this boss.",
            })
        elif our_lust and their_lust:
            our_time = our_lust[0]["time_pct"]
            their_time = their_lust[0]["time_pct"]
            if abs(our_time - their_time) > 20:
                tips.append({
                    "category": "Cooldowns",
                    "severity": "low",
                    "title": f"{boss['name']}: Different Bloodlust timing ({our_time:.0f}% vs {their_time:.0f}%)",
                    "detail": f"You used Bloodlust at {our_time:.0f}% of the fight, they used it at {their_time:.0f}%. Earlier usage generally yields more total value unless there's a burn phase.",
                })

    # Trash
    our_trash = ours.get("trash", {})
    their_trash = theirs.get("trash", {})
    if our_trash.get("logged") and their_trash.get("logged"):
        trash_delta = our_trash["total_time_ms"] - their_trash["total_time_ms"]
        if trash_delta > 60000:
            tips.append({
                "category": "Trash",
                "severity": "medium",
                "title": f"Trash pulls took {fmt_duration(trash_delta)} longer",
                "detail": f"Your raid spent {fmt_duration(our_trash['total_time_ms'])} on trash vs their {fmt_duration(their_trash['total_time_ms'])}. Consider bigger pulls, more AoE, or skipping optional packs.",
            })

    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    tips.sort(key=lambda t: severity_order.get(t["severity"], 9))

    return tips


# ------------------------------------------------------------------
# HTML generation
# ------------------------------------------------------------------

def rebuild_compare_html(compare_path: Path, data: dict[str, Any]) -> None:
    """Embed comparison data into compare.html."""
    html = compare_path.read_text()
    replacement = "<script>window.__COMPARE_DATA__ = " + json.dumps(data, indent=2) + ";</script>"
    updated, count = re.subn(
        r"<script>window\.__COMPARE_DATA__ = .*?;</script>",
        replacement,
        html,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("Could not find embedded compare block in compare.html")
    compare_path.write_text(updated)


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/compare_logs.py <our_report_url> <their_report_url>")
        print("  Compares two WarcraftLogs reports and generates a comparison report.")
        return 1

    our_url = sys.argv[1]
    their_url = sys.argv[2]
    root = project_root()
    api_key = load_api_key(root)
    client = WCLClient(api_key)

    print("Fetching OUR report...")
    our_data = fetch_report_data(client, our_url)
    print("\nFetching THEIR report...")
    their_data = fetch_report_data(client, their_url)

    print("\nComparing reports...")
    comparison = compare_reports(our_data, their_data)

    output_path = root / "data" / "comparison.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {output_path}...")
    output_path.write_text(json.dumps(comparison, indent=2))

    compare_html = root / "compare.html"
    if compare_html.exists():
        print(f"Rebuilding {compare_html}...")
        rebuild_compare_html(compare_html, comparison)

    print("\nDone! Open compare.html to view the comparison.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
