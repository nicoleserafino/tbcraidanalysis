"""
Parse WoW TBC combat log into structured JSON data for all encounters.
Extracts: encounters, phases, deaths, damage events, positioning, buffs/debuffs.
"""

import re
import json
import sys
from collections import defaultdict, Counter
from pathlib import Path


def parse_timestamp(ts_str):
    """Convert timestamp string to seconds since midnight."""
    m = re.match(r'(\d+):(\d+):(\d+\.?\d*)', ts_str)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return 0


def extract_player_name(full_name):
    """Extract just the player name from 'Name-Server' format."""
    return full_name.split('-')[0] if full_name else full_name


def parse_log_file(filepath):
    """Parse the combat log file and return structured data."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    # Find all encounters
    encounters = []
    current_encounter = None

    for line_num, line in enumerate(lines):
        ts_match = re.match(r'\d+/\d+/\d+ (\d+:\d+:\d+\.\d+)', line)
        if not ts_match:
            continue
        timestamp = ts_match.group(1)

        if 'ENCOUNTER_START' in line:
            m = re.search(r'ENCOUNTER_START,(\d+),"([^"]+)",(\d+),(\d+)', line)
            if m:
                current_encounter = {
                    'id': int(m.group(1)),
                    'name': m.group(2),
                    'difficulty': int(m.group(3)),
                    'raid_size': int(m.group(4)),
                    'start_time': timestamp,
                    'start_line': line_num,
                    'end_time': None,
                    'end_line': None,
                    'kill': False,
                }

        elif 'ENCOUNTER_END' in line and current_encounter:
            m = re.search(r'ENCOUNTER_END,(\d+),"([^"]+)",\d+,\d+,(\d+)', line)
            if m and int(m.group(1)) == current_encounter['id']:
                current_encounter['end_time'] = timestamp
                current_encounter['end_line'] = line_num
                current_encounter['kill'] = int(m.group(3)) == 1
                encounters.append(current_encounter)
                current_encounter = None

    # If last encounter didn't end (log cut off)
    if current_encounter:
        current_encounter['end_time'] = timestamp
        current_encounter['end_line'] = len(lines) - 1
        current_encounter['kill'] = False
        encounters.append(current_encounter)

    return lines, encounters


def analyze_encounter(lines, encounter):
    """Analyze a single encounter pull."""
    start = encounter['start_line']
    end = encounter['end_line'] or len(lines) - 1
    pull_lines = lines[start:end + 1]
    start_sec = parse_timestamp(encounter['start_time'])

    # Scan pre-pull lines (up to 120 lines before encounter) for consumable buffs
    pre_pull_consumables = {}
    consumable_categories = {
        'Flask of Blinding Light': 'flask', 'Flask of Supreme Power': 'flask',
        'Flask of Mighty Versatility': 'flask', 'Flask of Relentless Assault': 'flask',
        'Flask of Fortification': 'flask', 'Flask of Pure Death': 'flask',
        'Flask of Chromatic Wonder': 'flask', 'Flask of Distilled Wisdom': 'flask',
        'Elixir of Major Agility': 'battle_elixir', 'Elixir of Major Firepower': 'battle_elixir',
        'Elixir of Major Shadow Power': 'battle_elixir', 'Elixir of Healing Power': 'battle_elixir',
        'Elixir of Major Strength': 'battle_elixir', 'Elixir of Mastery': 'battle_elixir',
        "Adept's Elixir": 'battle_elixir', 'Onslaught Elixir': 'battle_elixir',
        'Elixir of Major Defense': 'guardian_elixir', 'Elixir of Major Fortitude': 'guardian_elixir',
        'Elixir of Major Mageblood': 'guardian_elixir', 'Elixir of Draenic Wisdom': 'guardian_elixir',
        'Elixir of Ironskin': 'guardian_elixir',
        'Well Fed': 'food',
        'Brilliant Wizard Oil': 'weapon_oil', 'Superior Wizard Oil': 'weapon_oil',
        'Brilliant Mana Oil': 'weapon_oil', 'Superior Mana Oil': 'weapon_oil',
        'Adamantite Weightstone': 'weapon_oil', 'Adamantite Sharpening Stone': 'weapon_oil',
        'Drums of Battle': 'drums', 'Drums of War': 'drums',
        'Drums of Restoration': 'drums', 'Drums of Speed': 'drums',
    }
    pre_start = max(0, start - 200)
    for line in lines[pre_start:start]:
        if 'SPELL_AURA_APPLIED' in line and 'BUFF' in line:
            m = re.search(r'SPELL_AURA_APPLIED,Player-[^,]*,"([^"]+)",[^,]*,[^,]*,Player-[^,]*,"([^"]+)",[^,]*,[^,]*,(\d+),"([^"]+)"', line)
            if m:
                target = extract_player_name(m.group(2))
                spell_name = m.group(4)
                if spell_name in consumable_categories:
                    pre_pull_consumables.setdefault(target, {})[consumable_categories[spell_name]] = spell_name

    result = {
        'encounter_id': encounter['id'],
        'boss_name': encounter['name'],
        'start_time': encounter['start_time'],
        'end_time': encounter['end_time'],
        'duration_sec': parse_timestamp(encounter['end_time']) - start_sec,
        'kill': encounter['kill'],
        'deaths': [],
        'damage_sources': defaultdict(lambda: defaultdict(int)),
        'damage_abilities': defaultdict(int),
        'player_damage_taken': defaultdict(lambda: defaultdict(int)),
        'player_positions': defaultdict(list),
        'creature_deaths': [],
        'interrupts': [],
        'dispels': [],
        'conflagrations': [],
        'players': set(),
        'heals_by_player': defaultdict(int),
        'heal_details': defaultdict(lambda: defaultdict(lambda: {'total': 0, 'overheal': 0, 'count': 0, 'is_hot': False})),
        'casts_by_player': defaultdict(int),
        'cast_timeline': defaultdict(list),
        'spell_casts': defaultdict(lambda: defaultdict(int)),  # player -> spell -> count
        'damage_done': defaultdict(lambda: defaultdict(int)),  # player -> spell -> total damage
        'buff_events': defaultdict(list),  # player -> [{spell, time}]
    }

    for line in pull_lines:
        ts_match = re.match(r'\d+/\d+/\d+ (\d+:\d+:\d+\.\d+)', line)
        if not ts_match:
            continue
        timestamp = ts_match.group(1)
        relative_time = parse_timestamp(timestamp) - start_sec

        # Track all players
        player_matches = re.findall(r'Player-[^,]*,"([^"]+)"', line)
        for p in player_matches:
            result['players'].add(extract_player_name(p))

        # Player deaths
        if 'UNIT_DIED' in line and 'Player' in line:
            m = re.search(r'Player-([^,]+),"([^"]+)".*?,(\d+)$', line.strip())
            if m:
                flag = int(m.group(3))
                if flag == 0:  # Real death, not feign death
                    result['deaths'].append({
                        'time': timestamp,
                        'relative_time': round(relative_time, 1),
                        'player': extract_player_name(m.group(2)),
                    })

        # Creature deaths
        if 'UNIT_DIED' in line and 'Creature' in line:
            m = re.search(r'Creature-[^,]*,"([^"]+)"', line)
            if m:
                result['creature_deaths'].append({
                    'time': timestamp,
                    'relative_time': round(relative_time, 1),
                    'name': m.group(1),
                })

        # Damage from creatures to players
        for dmg_type in ['SPELL_DAMAGE', 'RANGE_DAMAGE', 'SWING_DAMAGE', 'SPELL_PERIODIC_DAMAGE']:
            if dmg_type in line:
                m = re.search(
                    rf'{dmg_type},Creature-[^,]*,"([^"]+)".*?Player-[^,]*,"([^"]+)"',
                    line
                )
                if m:
                    source = m.group(1)
                    target = extract_player_name(m.group(2))
                    # Get ability name
                    if dmg_type == 'SWING_DAMAGE':
                        ability = 'Melee'
                    else:
                        am = re.search(r'(\d+),"([^"]+)",0x', line)
                        ability = am.group(2) if am else 'Unknown'

                    result['damage_sources'][source][target] += 1
                    result['damage_abilities'][ability] += 1
                    result['player_damage_taken'][target][f"{source}: {ability}"] += 1

        # Damage from players to players (MC, Conflag spread)
        for dmg_type in ['SPELL_DAMAGE', 'SPELL_PERIODIC_DAMAGE']:
            if dmg_type in line:
                m = re.search(
                    rf'{dmg_type},Player-[^,]*,"([^"]+)".*?Player-[^,]*,"([^"]+)"',
                    line
                )
                if m:
                    source = extract_player_name(m.group(1))
                    target = extract_player_name(m.group(2))
                    if source != target:
                        am = re.search(r'(\d+),"([^"]+)",0x', line)
                        ability = am.group(2) if am else 'Unknown'
                        if ability == 'Conflagration':
                            result['player_damage_taken'][target][f"{source} (MC/Conflag): {ability}"] += 1

        # Conflagration tracking
        if 'Conflagration' in line and 'SPELL_AURA_APPLIED' in line:
            m = re.search(r'Player-[^,]*,"([^"]+)".*?Conflagration', line)
            if m:
                result['conflagrations'].append({
                    'time': timestamp,
                    'relative_time': round(relative_time, 1),
                    'target': extract_player_name(m.group(1)),
                })

        # Interrupts
        if 'SPELL_INTERRUPT' in line:
            source_m = re.search(r'SPELL_INTERRUPT,Player-[^,]*,"([^"]+)"', line)
            target_m = re.search(r'SPELL_INTERRUPT.*?(?:Creature|Player)-[^,]*,"([^"]+)".*?(\d+),"([^"]+)"', line)
            if source_m:
                result['interrupts'].append({
                    'time': timestamp,
                    'relative_time': round(relative_time, 1),
                    'source': extract_player_name(source_m.group(1)),
                    'target': target_m.group(1) if target_m else 'Unknown',
                })

        # Dispels
        if 'SPELL_DISPEL' in line:
            m = re.search(r'SPELL_DISPEL,Player-[^,]*,"([^"]+)"', line)
            if m:
                result['dispels'].append({
                    'time': timestamp,
                    'relative_time': round(relative_time, 1),
                    'source': extract_player_name(m.group(1)),
                })

        # Healing tracking
        if 'SPELL_HEAL' in line or 'SPELL_PERIODIC_HEAL' in line:
            m = re.search(r'(?:SPELL_HEAL|SPELL_PERIODIC_HEAL),Player-[^,]*,"([^"]+)"', line)
            if m:
                player = extract_player_name(m.group(1))
                result['heals_by_player'][player] += 1
                # Extract spell name and overheal amount
                spell_m = re.search(r',(\d+),"([^"]+)"', line)
                is_hot = 'SPELL_PERIODIC_HEAL' in line
                if spell_m:
                    spell_name = spell_m.group(2)
                    # Overheal is second-to-last number field before nil/crit
                    parts = line.rstrip().split(',')
                    # Last fields: amount, overheal, absorbed, nil
                    try:
                        overheal = int(parts[-3])
                        amount = int(parts[-4])
                        result['heal_details'][player][spell_name]['total'] += amount
                        result['heal_details'][player][spell_name]['overheal'] += overheal
                        result['heal_details'][player][spell_name]['count'] += 1
                        result['heal_details'][player][spell_name]['is_hot'] = is_hot
                    except (ValueError, IndexError):
                        pass

        # Cast tracking
        if 'SPELL_CAST_SUCCESS' in line:
            m = re.search(r'SPELL_CAST_SUCCESS,Player-[^,]*,"([^"]+)"', line)
            if m:
                player = extract_player_name(m.group(1))
                result['casts_by_player'][player] += 1
                result['cast_timeline'][player].append(round(relative_time, 1))
                # Track individual spell casts
                spell_m = re.search(r'SPELL_CAST_SUCCESS,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,(\d+),"([^"]+)"', line)
                if spell_m:
                    spell_name = spell_m.group(2)
                    result['spell_casts'][player][spell_name] += 1

        # Damage done tracking (player dealing damage)
        if 'SPELL_DAMAGE' in line and 'Player-' in line:
            m = re.match(r'.*?(SPELL_DAMAGE|SPELL_PERIODIC_DAMAGE),Player-[^,]*,"([^"]+)",[^,]*,[^,]*,(?:Creature|Player)-[^,]*,"([^"]+)"', line)
            if m:
                player = extract_player_name(m.group(2))
                parts = line.rstrip().split(',')
                # spell name is field 11 (0-indexed 10)
                spell_m2 = re.search(r'(?:SPELL_DAMAGE|SPELL_PERIODIC_DAMAGE),[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,(\d+),"([^"]+)"', line)
                if spell_m2:
                    spell_name = spell_m2.group(2)
                    # damage amount: look for the pattern after coordinates
                    try:
                        # Find damage amount - it's after the coordinate block
                        # Format: ...,mapID,facing,level,amount,rawAmount,...
                        dmg_parts = parts[-8:]  # last 8 fields contain damage info
                        amount = int(dmg_parts[0]) if dmg_parts[0].lstrip('-').isdigit() else 0
                        if amount <= 0:
                            # Try alternate position
                            for p in reversed(parts[-12:]):
                                p = p.strip()
                                if p.lstrip('-').isdigit() and int(p) > 0:
                                    amount = int(p)
                                    break
                        result['damage_done'][player][spell_name] += max(amount, 1)
                    except (ValueError, IndexError):
                        result['damage_done'][player][spell_name] += 1

        # Swing damage from players
        if 'SWING_DAMAGE' in line and line.split(',')[1].startswith('Player-'):
            m = re.search(r'SWING_DAMAGE(?:_LANDED)?,Player-[^,]*,"([^"]+)"', line)
            if m:
                player = extract_player_name(m.group(1))
                result['damage_done'][player]['Melee (Auto Attack)'] += 1

        # Buff/cooldown tracking (key abilities only to keep data small)
        if 'SPELL_AURA_APPLIED' in line and 'Player-' in line and 'BUFF' in line:
            m = re.search(r'SPELL_AURA_APPLIED,Player-[^,]*,"([^"]+)",[^,]*,[^,]*,Player-[^,]*,"([^"]+)",[^,]*,[^,]*,(\d+),"([^"]+)"', line)
            if m:
                source = extract_player_name(m.group(1))
                target = extract_player_name(m.group(2))
                spell_id = m.group(3)
                spell_name = m.group(4)
                # Only track key DPS/tank cooldowns to keep data manageable
                key_buffs = [
                    'Bloodlust', 'Heroism', 'Adrenaline Rush', 'Blade Flurry',
                    'Bestial Wrath', 'Rapid Fire', 'Icy Veins', 'Arcane Power',
                    'Presence of Mind', 'Combustion', 'Shadow Trance',
                    'Shield Wall', 'Last Stand', 'Shield Block', 'Holy Shield',
                    'Barkskin', 'Frenzied Regeneration', 'Survival Instincts',
                    'Recklessness', 'Death Wish', 'Sweeping Strikes',
                    'Tricks of the Trade', 'Misdirection', 'Feign Death',
                    'Innervate', 'Power Infusion', 'Nature\'s Swiftness',
                    'Soulshatter', 'Cloak of Shadows', 'Evasion', 'Vanish',
                    'Ice Block', 'Divine Shield', 'Blessing of Protection',
                    'Lifeblood', 'Drums of Battle', 'Drums of War',
                ]
                if spell_name in key_buffs:
                    result['buff_events'][source if source == target else target].append({
                        'spell': spell_name,
                        'time': round(relative_time, 1),
                        'source': source,
                    })

                # Consumable tracking (flasks, elixirs, food, oils, drums)
                consumable_categories = {
                    # Flasks
                    'Flask of Blinding Light': 'flask', 'Flask of Supreme Power': 'flask',
                    'Flask of Mighty Versatility': 'flask', 'Flask of Relentless Assault': 'flask',
                    'Flask of Fortification': 'flask', 'Flask of Pure Death': 'flask',
                    'Flask of Chromatic Wonder': 'flask', 'Flask of Distilled Wisdom': 'flask',
                    # Battle Elixirs
                    'Elixir of Major Agility': 'battle_elixir', 'Elixir of Major Firepower': 'battle_elixir',
                    'Elixir of Major Shadow Power': 'battle_elixir', 'Elixir of Healing Power': 'battle_elixir',
                    'Elixir of Major Strength': 'battle_elixir', 'Elixir of Mastery': 'battle_elixir',
                    'Adept\'s Elixir': 'battle_elixir', 'Onslaught Elixir': 'battle_elixir',
                    # Guardian Elixirs
                    'Elixir of Major Defense': 'guardian_elixir', 'Elixir of Major Fortitude': 'guardian_elixir',
                    'Elixir of Major Mageblood': 'guardian_elixir', 'Elixir of Draenic Wisdom': 'guardian_elixir',
                    'Elixir of Ironskin': 'guardian_elixir',
                    # Food (Well Fed buffs)
                    'Well Fed': 'food',
                    # Weapon enhancements
                    'Brilliant Wizard Oil': 'weapon_oil', 'Superior Wizard Oil': 'weapon_oil',
                    'Brilliant Mana Oil': 'weapon_oil', 'Superior Mana Oil': 'weapon_oil',
                    'Adamantite Weightstone': 'weapon_oil', 'Adamantite Sharpening Stone': 'weapon_oil',
                    # Drums
                    'Drums of Battle': 'drums', 'Drums of War': 'drums',
                    'Drums of Restoration': 'drums', 'Drums of Speed': 'drums',
                }
                if spell_name in consumable_categories:
                    player_target = target if source == target else target
                    if player_target not in result.get('consumables', {}):
                        result.setdefault('consumables', {})[player_target] = {}
                    cat = consumable_categories[spell_name]
                    result.setdefault('consumables', {}).setdefault(player_target, {})[cat] = spell_name

        # Position tracking (from advanced log damage/heal events with coordinates)
        if 'Player' in line and any(x in line for x in ['SPELL_DAMAGE', 'SPELL_HEAL', 'RANGE_DAMAGE', 'SWING_DAMAGE']):
            # Advanced log format includes x,y coordinates near the end
            # Format: ...,x.xx,y.yy,mapID,...
            coords = re.findall(r'(-?\d+\.\d+),(-?\d+\.\d+),334,', line)
            if coords:
                # Find which player this position belongs to
                players_in_line = re.findall(r'Player-[^,]*,"([^"]+)"', line)
                if players_in_line:
                    player = extract_player_name(players_in_line[0])
                    x, y = float(coords[0][0]), float(coords[0][1])
                    result['player_positions'][player].append({
                        'time': round(relative_time, 1),
                        'x': x,
                        'y': y,
                    })

    # Convert sets/defaultdicts for JSON serialization
    result['players'] = sorted(list(result['players']))
    result['damage_sources'] = {k: dict(v) for k, v in result['damage_sources'].items()}
    result['player_damage_taken'] = {k: dict(v) for k, v in result['player_damage_taken'].items()}
    result['damage_abilities'] = dict(result['damage_abilities'])
    result['heals_by_player'] = dict(result['heals_by_player'])
    result['heal_details'] = {player: {spell: dict(info) for spell, info in spells.items()} for player, spells in result['heal_details'].items()}
    result['casts_by_player'] = dict(result['casts_by_player'])
    result['cast_timeline'] = dict(result['cast_timeline'])
    result['spell_casts'] = {player: dict(spells) for player, spells in result['spell_casts'].items()}
    result['damage_done'] = {player: dict(spells) for player, spells in result['damage_done'].items()}
    result['buff_events'] = dict(result['buff_events'])
    # Merge pre-pull and in-fight consumables
    consumables = dict(pre_pull_consumables)
    for player, cats in result.get('consumables', {}).items():
        consumables.setdefault(player, {}).update(cats)
    result['consumables'] = consumables

    # Reduce position data - keep only samples near key events (deaths, conflags)
    key_times = set()
    for d in result['deaths']:
        key_times.add(round(d['relative_time']))
    for c in result['conflagrations']:
        key_times.add(round(c['relative_time']))

    reduced_positions = {}
    for player, positions in result['player_positions'].items():
        reduced = []
        for pos in positions:
            t = round(pos['time'])
            # Keep positions near key events (within 3 seconds)
            if any(abs(t - kt) <= 3 for kt in key_times):
                reduced.append(pos)
            # Also sample every 10 seconds for timeline
            elif t % 10 == 0:
                reduced.append(pos)
        if reduced:
            reduced_positions[player] = reduced

    result['player_positions'] = reduced_positions

    return result


def identify_roles(lines, encounters):
    """Identify player roles per encounter from cast frequency.
    
    Returns a dict: {encounter_index: {player_name: role}}
    Also returns a 'primary' dict with most-common role across encounters.
    """
    tank_spells = {
        'Shield Slam', 'Sunder Armor', 'Devastate', 'Revenge',
        'Mangle (Bear)', 'Lacerate', 'Maul', 'Swipe',
        'Holy Shield', 'Avenger\'s Shield', 'Righteous Defense',
    }
    heal_spells = {
        'Flash of Light', 'Holy Light', 'Flash Heal', 'Greater Heal',
        'Prayer of Healing', 'Prayer of Mending', 'Circle of Healing',
        'Chain Heal', 'Healing Wave', 'Lesser Healing Wave',
        'Rejuvenation', 'Lifebloom', 'Regrowth', 'Swiftmend',
        'Earth Shield', 'Binding Heal', 'Renew',
    }
    dps_spells = {
        'Fireball', 'Frostbolt', 'Arcane Blast', 'Arcane Missiles',
        'Shadow Bolt', 'Incinerate', 'Seed of Corruption', 'Corruption',
        'Mind Blast', 'Shadow Word: Pain', 'Mind Flay', 'Vampiric Touch',
        'Sinister Strike', 'Backstab', 'Eviscerate', 'Slice and Dice',
        'Steady Shot', 'Arcane Shot', 'Multi-Shot', 'Kill Command',
        'Lightning Bolt', 'Chain Lightning', 'Earth Shock', 'Flame Shock',
        'Stormstrike', 'Lava Burst',
        'Wrath', 'Starfire', 'Moonfire', 'Insect Swarm',
        'Mortal Strike', 'Bloodthirst', 'Whirlwind', 'Slam',
        'Crusader Strike', 'Judgement of Blood', 'Judgement of the Crusader',
        'Judgement of Righteousness', 'Seal of Blood', 'Seal of Command',
        'Heroic Strike', 'Execute',
        'Shred', 'Ferocious Bite', 'Rip', 'Mangle (Cat)',
    }

    per_encounter_roles = {}
    player_role_counts = defaultdict(lambda: defaultdict(int))

    for enc_idx, enc in enumerate(encounters):
        start = enc['start_line']
        end = enc['end_line'] or len(lines) - 1

        player_heal_casts = defaultdict(int)
        player_tank_casts = defaultdict(int)
        player_dps_casts = defaultdict(int)

        for line in lines[start:end + 1]:
            if 'SPELL_CAST_SUCCESS' in line:
                m = re.search(r'SPELL_CAST_SUCCESS,Player-[^,]*,"([^"]+)".*?(\d+),"([^"]+)",0x', line)
                if m:
                    player = extract_player_name(m.group(1))
                    spell = m.group(3)
                    if spell in tank_spells:
                        player_tank_casts[player] += 1
                    elif spell in heal_spells:
                        player_heal_casts[player] += 1
                    elif spell in dps_spells:
                        player_dps_casts[player] += 1

        enc_roles = {}
        all_players = set(player_heal_casts) | set(player_tank_casts) | set(player_dps_casts)
        for player in all_players:
            heals = player_heal_casts[player]
            tanks = player_tank_casts[player]
            dps = player_dps_casts[player]
            total = heals + tanks + dps

            if total == 0:
                role = 'DPS'
            elif tanks > 5 and tanks / total > 0.30:
                role = 'Tank'
            elif heals > dps and heals > 5:
                role = 'Healer'
            else:
                role = 'DPS'

            enc_roles[player] = role
            player_role_counts[player][role] += 1

        per_encounter_roles[enc_idx] = enc_roles

    # Primary role = most frequent role across encounters
    primary_roles = {}
    for player, counts in player_role_counts.items():
        primary_roles[player] = max(counts, key=counts.get)

    return per_encounter_roles, primary_roles


def identify_classes(lines, encounters):
    """Identify player classes from abilities used."""
    classes = {}
    player_abilities = defaultdict(set)

    for enc in encounters:
        start = enc['start_line']
        end = enc['end_line'] or len(lines) - 1
        for line in lines[start:end + 1]:
            if 'SPELL_CAST_SUCCESS' in line:
                m = re.search(r'SPELL_CAST_SUCCESS,Player-[^,]*,"([^"]+)".*?(\d+),"([^"]+)",0x', line)
                if m:
                    player_abilities[extract_player_name(m.group(1))].add(m.group(3))

    class_markers = {
        'Warrior': {'Shield Slam', 'Mortal Strike', 'Bloodthirst', 'Whirlwind', 'Execute', 'Sunder Armor', 'Devastate', 'Revenge', 'Heroic Strike'},
        'Paladin': {'Flash of Light', 'Holy Light', 'Judgement of Wisdom', 'Judgement of Light', 'Seal of Righteousness', 'Holy Shield', 'Avenger\'s Shield', 'Crusader Strike'},
        'Hunter': {'Auto Shot', 'Steady Shot', 'Aimed Shot', 'Multi-Shot', 'Arcane Shot', 'Kill Command', 'Misdirection'},
        'Rogue': {'Sinister Strike', 'Backstab', 'Eviscerate', 'Slice and Dice', 'Mutilate', 'Rupture'},
        'Priest': {'Flash Heal', 'Greater Heal', 'Prayer of Healing', 'Circle of Healing', 'Shadow Word: Pain', 'Mind Blast', 'Vampiric Touch'},
        'Shaman': {'Chain Heal', 'Lightning Bolt', 'Earth Shock', 'Flame Shock', 'Stormstrike', 'Healing Wave'},
        'Mage': {'Fireball', 'Frostbolt', 'Arcane Missiles', 'Arcane Blast', 'Ice Lance', 'Fire Blast'},
        'Warlock': {'Shadow Bolt', 'Corruption', 'Curse of Agony', 'Curse of Elements', 'Seed of Corruption', 'Incinerate'},
        'Druid': {'Rejuvenation', 'Lifebloom', 'Regrowth', 'Mangle (Bear)', 'Mangle (Cat)', 'Moonfire', 'Starfire', 'Wrath'},
    }

    for player, abilities in player_abilities.items():
        best_class = 'Unknown'
        best_score = 0
        for cls, markers in class_markers.items():
            score = len(abilities & markers)
            if score > best_score:
                best_score = score
                best_class = cls
        classes[player] = best_class

    return classes


def parse_talent_specs(lines):
    """Parse COMBATANT_INFO to extract talent specs and determine roles.
    
    Returns: {player_name: {'spec': (t1, t2, t3), 'role': 'Tank'|'Healer'|'DPS'}}
    """
    # First, build player ID -> name mapping from combat events
    id_to_name = {}
    for line in lines:
        matches = re.findall(r'(Player-\d+-[A-F0-9]+),"([^"]+)"', line)
        for pid, name in matches:
            if pid not in id_to_name:
                id_to_name[pid] = extract_player_name(name)
    
    # Parse COMBATANT_INFO for talent specs
    talent_specs = {}
    for line in lines:
        if 'COMBATANT_INFO' not in line:
            continue
        m = re.search(r'COMBATANT_INFO,(Player-\d+-[A-F0-9]+)', line)
        if not m:
            continue
        player_id = m.group(1)
        # Find talent spec: (tree1, tree2, tree3) — sum should be ~61 (TBC max level 70)
        specs = re.findall(r'\((\d+),(\d+),(\d+)\)', line)
        for s in specs:
            total = int(s[0]) + int(s[1]) + int(s[2])
            if 55 <= total <= 65:
                name = id_to_name.get(player_id)
                if name:
                    talent_specs[name] = (int(s[0]), int(s[1]), int(s[2]))
                break
    
    return talent_specs


def parse_talent_specs_per_encounter(lines, encounters):
    """Parse COMBATANT_INFO per encounter to detect spec swaps between pulls.

    Returns: {encounter_index: {player_name: (t1, t2, t3)}}
    """
    # Build player ID -> name mapping
    id_to_name = {}
    for line in lines:
        matches = re.findall(r'(Player-\d+-[A-F0-9]+),"([^"]+)"', line)
        for pid, name in matches:
            if pid not in id_to_name:
                id_to_name[pid] = extract_player_name(name)

    per_encounter_specs = {}
    for enc_idx, enc in enumerate(encounters):
        start = enc['start_line']
        end = enc['end_line'] or len(lines) - 1
        enc_specs = {}
        for line in lines[start:end + 1]:
            if 'COMBATANT_INFO' not in line:
                continue
            m = re.search(r'COMBATANT_INFO,(Player-\d+-[A-F0-9]+)', line)
            if not m:
                continue
            player_id = m.group(1)
            specs = re.findall(r'\((\d+),(\d+),(\d+)\)', line)
            for s in specs:
                total = int(s[0]) + int(s[1]) + int(s[2])
                if 55 <= total <= 65:
                    name = id_to_name.get(player_id)
                    if name:
                        enc_specs[name] = (int(s[0]), int(s[1]), int(s[2]))
                    break
        per_encounter_specs[enc_idx] = enc_specs

    return per_encounter_specs


def role_from_talents(player_class, spec):
    """Determine role from class + talent spec.
    
    TBC talent trees by class:
    Warrior: Arms(1)/Fury(2)/Protection(3)
    Paladin: Holy(1)/Protection(2)/Retribution(3)
    Druid: Balance(1)/Feral(2)/Restoration(3)
    Priest: Discipline(1)/Holy(2)/Shadow(3)
    Shaman: Elemental(1)/Enhancement(2)/Restoration(3)
    Mage: Arcane(1)/Fire(2)/Frost(3) — all DPS
    Warlock: Affliction(1)/Demonology(2)/Destruction(3) — all DPS
    Rogue: Assassination(1)/Combat(2)/Subtlety(3) — all DPS
    Hunter: BM(1)/Marks(2)/Survival(3) — all DPS
    """
    if not spec:
        return None
    
    t1, t2, t3 = spec
    primary_tree = max(range(3), key=lambda i: spec[i])  # 0, 1, or 2
    
    if player_class == 'Warrior':
        if primary_tree == 2:  # Protection
            return 'Tank'
        return 'DPS'
    elif player_class == 'Paladin':
        if primary_tree == 0:  # Holy
            return 'Healer'
        elif primary_tree == 1:  # Protection
            return 'Tank'
        return 'DPS'  # Retribution
    elif player_class == 'Druid':
        if primary_tree == 2:  # Restoration
            return 'Healer'
        elif primary_tree == 1:  # Feral — could be tank or DPS (cat vs bear)
            # Cannot distinguish from talents alone; return None to use cast-based detection
            return None
        return 'DPS'  # Balance
    elif player_class == 'Priest':
        if primary_tree == 2:  # Shadow
            return 'DPS'
        return 'Healer'  # Discipline or Holy
    elif player_class == 'Shaman':
        if primary_tree == 2:  # Restoration
            return 'Healer'
        return 'DPS'  # Elemental or Enhancement
    else:
        # Mage, Warlock, Rogue, Hunter — always DPS
        return 'DPS'


def generate_report(filepath):
    """Generate the full analysis report."""
    print(f"Parsing log file: {filepath}")
    lines, encounters = parse_log_file(filepath)
    print(f"Found {len(encounters)} encounters")

    per_encounter_roles, primary_roles = identify_roles(lines, encounters)
    classes = identify_classes(lines, encounters)
    per_encounter_specs = parse_talent_specs_per_encounter(lines, encounters)

    # Override roles with talent-based detection per encounter
    for enc_idx, specs in per_encounter_specs.items():
        for player, spec in specs.items():
            player_class = classes.get(player, 'Unknown')
            talent_role = role_from_talents(player_class, spec)
            if talent_role:
                if enc_idx in per_encounter_roles and player in per_encounter_roles[enc_idx]:
                    per_encounter_roles[enc_idx][player] = talent_role

    # Recompute primary roles from per-encounter roles
    player_role_counter: dict[str, Counter] = defaultdict(Counter)
    for enc_idx, roles in per_encounter_roles.items():
        for player, role in roles.items():
            player_role_counter[player][role] += 1
    for player, counts in player_role_counter.items():
        primary_roles[player] = counts.most_common(1)[0][0]

    # Group encounters by boss
    boss_groups = defaultdict(list)
    for enc in encounters:
        boss_groups[enc['name']].append(enc)

    report = {
        'log_info': {
            'file': str(filepath),
            'total_lines': len(lines),
            'total_encounters': len(encounters),
        },
        'players': {
            name: {'role': primary_roles.get(name, 'Unknown'), 'class': classes.get(name, 'Unknown')}
            for name in sorted(set(primary_roles.keys()) | set(classes.keys()))
        },
        'bosses': {},
    }

    # Track encounter index globally across all bosses
    enc_idx = 0
    for boss_name, boss_encounters in boss_groups.items():
        print(f"  Analyzing {boss_name} ({len(boss_encounters)} pulls)...")
        pulls = []
        for enc in boss_encounters:
            pull_data = analyze_encounter(lines, enc)
            # Attach per-pull roles
            pull_data['roles'] = per_encounter_roles.get(enc_idx, {})
            pulls.append(pull_data)
            enc_idx += 1

        report['bosses'][boss_name] = {
            'total_pulls': len(pulls),
            'kills': sum(1 for p in pulls if p['kill']),
            'wipes': sum(1 for p in pulls if not p['kill']),
            'pulls': pulls,
        }

    return report


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python parse_log.py <path_to_combat_log> [output_path]")
        sys.exit(1)

    log_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('data/report.json')

    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = generate_report(log_path)

    print(f"Writing report to {output_path}")
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print("Done!")
    print(f"  Bosses: {', '.join(report['bosses'].keys())}")
    print(f"  Players: {len(report['players'])}")
    for boss, data in report['bosses'].items():
        print(f"  {boss}: {data['total_pulls']} pulls ({data['kills']} kills, {data['wipes']} wipes)")
