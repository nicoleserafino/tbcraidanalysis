# Raid Awards

The Awards tab displays dashboard-style cards for notable raid moments, aggregated across all bosses and all pulls in the report. Awards are only given when there is a clear winner (no ties).

## How Awards Work

- Data is aggregated across **every pull on every boss** in the report
- Awards are only shown when there is a **clear winner** (if the top two players are tied, the award is skipped)
- Awards are grouped into themed sections
- Cards show the winner, a value/stat, and optional context detail

## Award Categories

### Clutch / Survival

| Award | What it measures | Data source |
|-------|-----------------|-------------|
| Clutch Heal | Lowest HP% target was at when healed | Per-event `hitPoints` from heal events |
| Clutch Self-Save | Lowest HP% self-heal | Same, where healer = target |
| Closest Call | Lowest HP% survival where target didn't die | Clutch heals cross-referenced with death list |
| Guardian Angel | Most clutch saves under 15% HP | Count of low-HP heals per healer |

**Note:** These awards require report data fetched after the clutch heal tracking was added to `fetch_from_api.py`. Older report JSON files won't have the `clutch_heals` field.

### Utility / Support

| Award | What it measures | Data source |
|-------|-----------------|-------------|
| MVP Interrupt | Most successful interrupts | `pull.interrupts` |
| Dispel Hero | Most dispels/cleanses | `pull.dispels` |
| Drumline Captain | Most Drums of Battle/War/etc uses | `spell_casts` + `buff_events` |

### Throughput / Big Numbers

| Award | What it measures | Data source |
|-------|-----------------|-------------|
| Pump Lord | Highest total damage across all pulls | `damage_done` aggregated |
| HPS Monster | Highest total healing across all pulls | `heal_details` aggregated |
| Biggest Crit | Largest single crit (heal or damage) | Per-event `hitType` + `amount` |
| Biggest Heal | Largest single heal event | Per-event heal `amount` |

**Note:** Biggest Crit and Biggest Heal require report data with `biggest_crits` and `biggest_heals` fields.

### Mechanics / Execution

| Award | What it measures | Data source |
|-------|-----------------|-------------|
| Mechanic Gamer | Only player with 0 avoidable damage hits (non-tanks) | `player_damage_taken` vs avoidable regex patterns |
| Standing in It Champion | Most avoidable damage taken | Same source, highest count |
| Floor Inspector | Most total deaths | `pull.deaths` |
| First Blood | Most times dying first on a pull | First entry in `pull.deaths` |
| Last One Standing | Most times being last alive on wipes | Last death or alive on non-kill pulls |

### Preparation / Consumables

| Award | What it measures | Data source |
|-------|-----------------|-------------|
| Potion Goblin | Most combat potion uses | `spell_casts` pattern match |
| Dark Rune Enthusiast | Most Dark/Demonic Rune uses | `spell_casts` pattern match |
| Healthstone Enjoyer | Most Healthstone uses | `spell_casts` pattern match |
| Prepared Gamer | Best flask + food buff consistency | `buff_events` scored per pull |

### Fun / Meme

| Award | What it measures | Data source |
|-------|-----------------|-------------|
| Main Character Syndrome | Most targeted by Capernian conflagrations (Kael only) | `pull.conflagrations` |
| One Trick Pony | Fewest unique spells cast (DPS, 3+ pulls) | `spell_casts` unique count |
| Swiss Army Knife | Most unique spells cast (3+ pulls) | `spell_casts` unique count |
| Overheal Olympics | Highest overheal % (healers) | `heal_details` overheal/total ratio |
| Glass Cannon | Highest damage among players who died | `damage_done` + `deaths` cross-reference |
| Unkillable | Most pulls survived without dying (5+ pulls) | Death list per pull |
| Button Masher | Highest casts per minute | `casts_by_player` / `duration_sec` |
| AFK Champion | Lowest casts per minute (DPS only) | Same, sorted ascending |

## Not Yet Supported

These awards are defined as TODOs in the source but cannot be computed with the current data model. I'll look to add them in the future:

| Award | Reason |
|-------|--------|
| Snap Healer | Needs rolling-window heal timeline analysis |
| Trash Tyrant | Trash encounters not separated in boss-grouped data |
| Threat Enjoyer | Aggro/threat data not exposed by WCL v1 API |
| Interrupt Assassin | Needs enemy cast-start timestamps for reaction time |

## Adding New Awards

Awards are computed in `computeRaidAwards()` in `index.html`. To add a new award:

1. Add any new aggregation trackers in the `allBossPulls.forEach()` loop
2. After the loop, compute the award winner using `topN()` or custom logic
3. Gate the award with `hasClearWinner()` to skip ties
4. Push to the appropriate `awards.<category>` array
5. Each award object has: `title`, `winner`, `value`, and optional `detail`
