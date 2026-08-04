# Serpentshrine Cavern (SSC) — Trash Marking & Boss Guide
_Reconstructed from last Tuesday's clear (report `YXzKVkwL3h94ya1R`). Marks, tanks & CC are what your raid **actually** did._

## Mark Legend (same as TK)
| Mark | Meaning | Who |
|------|---------|-----|
| 💀 **Skull** | Kill FIRST | MT holds, everyone burns |
| ❌ **X** | Kill SECOND | OT holds |
| 🌙 **Moon** | **Polymorph** (Sheep) | Mages (Dirtymagik / Harahot / Cakespanks) |
| 🔷 **Diamond** | **Banish** | Warlock (Kamiguruu) |
| 🟦 **Square** | Off-tank elite | OT |
| 🔺 **Triangle** | Off-tank 2nd elite | OT |

## Tank Roster (Tuesday, SSC)
- **Furboll** — Druid Bear, **primary SSC tank** (tanks most bosses + big elementals)
- **Mightystorm** — Warrior, **MT** on elite packs & shares Hydross / tanks Leotheras
- **Mothan** — Prot Paladin, **OT** (casters, kill targets, add piles)
- **Kamiguruu** — Warlock, **Banish** duty (+ Leotheras demon)
- **Varúk / Warriorlouco** — Warrior spare OTs

## MRT Automark — safe presets (one-mob-one-mark)
```
Greyheart Nether-Mage    -> Moon      (sheep)
Serpentshrine Lurker     -> Diamond   (banish)
Vashj'ir Honor Guard     -> Triangle  (off-tank)
Coilfang Shatterer       -> Skull     (kill/interrupt on Honor Guard packs)
Greyheart Tidecaller     -> Skull     (kill — caster)
Tidewalker Shaman        -> Skull     (kill/interrupt — caster)
Tidewalker Hydromancer   -> Square    (off-tank)
```
⚠️ **Hand-mark live:** Coilfang Priestess (Moon/Square varies), Greyheart Skulker/Shield-Bearer, Underbog Colossus Ragers, and any kill-order Skull/X on mixed packs.

---

# ═══════  TRASH BY PACK TYPE  ═══════
_SSC repeats the same ~5 pack types on the way to each boss._

## Pack A — Honor Guard packs (bridges toward Hydross / Lurker)
| Mob | Mark | Tank | Do |
|-----|------|------|----|
| Vashj'ir Honor Guard | 🔺 Triangle | **Mightystorm** | Off-tank the big elite |
| Coilfang Shatterer | 💀 Skull / ❌ X | **Mothan** | **Kill first** (hits hard, Arcane Explosion) |
| Coilfang Priestess | 🌙 Moon (or 🟦 Square) | Mage sheep / OT | **Polymorph** — she **heals & Mind Controls**. Sheep or kill fast |
| Greyheart Technician | — | OT (AoE) | Add — Frost Nova + AoE down |

**Plan:** Sheep the Priestess (Moon — she heals/MCs). MT (Mightystorm) grabs Honor Guard (Triangle), kill Shatterer (Skull) first, then release/kill Priestess. Interrupt Priestess heals if not sheeped.

## Pack B — Underbog Colossus / Water Elementals
| Mob | Mark | Tank | Do |
|-----|------|------|----|
| Underbog Colossus | 💀 Skull | **Furboll** / Mightystorm | Big elemental — single-tank & burn |
| Colossus Rager | — | AoE | Splits off — **Frost Nova** + AoE down |
| Coilfang Beast-Tamer | 🟦 Square | Mightystorm | Off-tank (has pets) |

**Plan:** One tank grabs the Colossus (Skull), Frost Nova the Ragers when it splits, cleave everything. Watch for **Coilfang Frenzy** adds.

## Pack C — Greyheart caster packs (toward Leotheras / Karathress)
| Mob | Mark | Tank | Do |
|-----|------|------|----|
| Greyheart Nether-Mage | 🌙 Moon | Mage sheep | **Polymorph** (caster — Blast Wave/Frostbolt) |
| Greyheart Tidecaller | 💀 Skull / ❌ X | **Mothan** / Furboll | **Kill/interrupt** — heals & chain lightning |
| Coilfang Serpentguard | ❌ X / 🟦 Square | Mightystorm / Mothan | Off-tank / kill 2nd |
| Coilfang Fathom-Witch | 💀 Skull / ❌ X | Furboll / Mothan | Caster — **interrupt**, kill |
| Greyheart Skulker | 🔺 Triangle / 🟦 Square | Furboll / Mightystorm | Stealther — off-tank |
| Greyheart Shield-Bearer | 🟦 Square / ❌ X | Furboll / Mightystorm | Off-tank (shields) |
| **Serpentshrine Lurker** | 🔷 **Diamond** | **Kamiguruu Banish** | **BANISH** (it's an elemental add) |

**Plan:** Sheep a Nether-Mage (Moon), **Banish the Serpentshrine Lurker (Diamond)**, MT off-tanks the melee (Skulker/Shield-Bearer/Serpentguard on Square/Triangle), kill casters first (Tidecaller/Fathom-Witch = Skull, **interrupt their heals & chain lightning**).

## Pack D — Tidewalker packs (toward Morogrim)
| Mob | Mark | Tank | Do |
|-----|------|------|----|
| Tidewalker Shaman | 💀 Skull / ❌ X | **Mothan** | **Kill/interrupt** — casts heals & totems |
| Tidewalker Hydromancer | 🟦 Square | **Mightystorm** | Off-tank (caster) |
| Tidewalker Warrior | — | Varúk / Mothan | Melee — tank & cleave |
| Tidewalker Depth-Seer / Harpooner | — | Mothan (AoE) | Adds — kill |

**Plan:** Casters are the danger — kill/interrupt Shamans (Skull) & Hydromancers first, off-tank Warriors, cleave the rest. Kill totems.

---

# ═══════════════  BOSS GUIDE  ═══════════════
_Lust timings are what you actually did Tuesday._

## 💧 Hydross the Unstable  (Lust: ~13s / on pull)  — Tanks: **Mightystorm + Furboll**
The frost↔nature transition fight (see also your Hydross survivability notes).
- **Two tanks, two roles:** one holds **Frost side** (needs nature resist), one holds **Nature side** (needs frost resist). Swap boss across the line at each transition.
- **Marks of Hydross/Corruption** stack every ~14.5s; each stack = **+15% boss damage & attack speed** (up to +60% at 4 stacks). **Transition BEFORE 4 stacks** (aim for 3) — that's where tanks die.
- On transition he **spawns adds** (4 Pure/Tainted Spawn) — off-tank/AoE them down fast.
- **Tank cooldowns at the stack peak** (Shield Wall / Barkskin) — this was your Sunday death cause.
- **Callouts:** "Transition NOW — 3 stacks!" • "Tanks swap sides." • "Adds on transition — AoE." • "Tank CD on the flip."

## 🌊 The Lurker Below  (Lust: ~15s / on pull)  — Tank: **Furboll**
- **Spout:** Lurker rotates and blasts a line — **everyone watches the turn direction and dodges** (or LoS behind a platform). Knocks you into the water = adds.
- **Geyser:** random water spouts under players — move out.
- **Submerge phase:** Lurker dives, **3 adds spawn** (Coilfang Guardians/Ambushers) — tanks pick up, kill before he resurfaces.
- **Callouts:** "SPOUT — get behind LoS / dodge!" • "Geyser, move." • "Submerge — grab adds." • Ranged on platforms.

## 👹 Leotheras the Blind  (Lust: ~1:40 / after split)  — Tanks: **Mightystorm (main) + Furboll**, Kami assists
- **Start: kill the 3 Greyheart Spellbinder adds first** (they channel a whirlwind on players — dead by ~12s Tuesday) before engaging Leotheras.
- **Whirlwind:** every ~60s he spins doing huge melee AoE (219 hits Tue). **We do NOT back melee out** — **melee EAT the whirlwind and stay on him.** Instead, **RANGED jump/relocate away** so the whirlwinding Leotheras doesn't wander into the ranged parties. Healers keep melee topped through it.
- **Split (~15%):** he splits into **Human form** (casts, tanked by Mightystorm) + **Demon form** (melees + **Chaos Blast** random nuke — needs a shadow-resist/warlock-ish body; Mightystorm held it Tue). Kill the Human, tank the Demon.
- **Inner Demon (Insidious Whisper):** marks ~5 players — each marked player must **kill their OWN Inner Demon within 30s or they get Mind-Controlled.** Do NOT help kill someone else's.
- **Lust after the split (~1:40).**
- **Callouts:** "Spellbinders first!" • "Whirlwind — MELEE STAY/eat it, RANGED move away!" • "Inner Demon on <name> — kill YOUR add!" • "Split — burn human, tank demon." • "Lust — burn him down."

## 🔱 Fathom-Lord Karathress  (Lust: ~60s / after adds)  — Tank: **Furboll** (+ Mothan on adds)
**Our strat: off-tank Karathress herself FAR AWAY and ignore her — kill the 3 guards first, then reset her threat and burn.**
- A tank drags **Karathress out of the way** and just holds her at range (she takes only chip damage — Tuesday she took ~30k/15s while we cleared adds). **Don't commit DPS to her yet.**
- **Kill the 2 killable guards** (each grants Karathress its ability on death, so handle them cleanly):
  - **Fathom-Guard Tidalvess** — drops totems (**kill the totems**), Spitfire. _(died ~40s Tue)_
  - **Fathom-Guard Sharkkis** — Enrage + pet; kite/kill. _(died ~66s Tue)_
- **Fathom-Guard Caribdis (the healer) — we do NOT kill her.** A tank **runs her out of the hallway and kites her until she resets/leashes** (so she's out of the fight and can't heal the pack). She was never killed Tuesday. Watch her Water Bolt / Tidal Surge geyser while kiting.
- **Once Tidalvess & Sharkkis are down and Caribdis is reset out → turn onto Karathress, LUST (~60s), and burn her** (Tuesday: damage jumped from ~30k to 440k/15s right here).
- **Callouts:** "Tank Karathress AWAY — ignore her!" • "Kill Tidalvess (totems) + Sharkkis." • "Run Caribdis out — DON'T kill her, reset her!" • "Guards handled — turn on the boss, LUST!"

## 🐟 Morogrim Tidewalker  (Lust: ~3:20 / execute)  — Tank: **Furboll**
- **Watery Grave:** marks 4 players, teleports them + spawns water globules — quick move.
- **Murloc waves (Tidewalker Lurkers):** at ~50% he summons a big **murloc add wave** — **AoE them down FAST** (they overwhelm healers). This is the wipe point.
- **Tidal Wave:** frontal knockback — don't stack in front.
- **Lust late (~3:20) for the execute** once murlocs are handled.
- **Callouts:** "Murlocs SPAWNING — AoE them!" • "Watery Grave — move." • "Don't stand in front (Tidal Wave)." • "Lust for execute."

## 🐍 Lady Vashj  (Lust: ~6:15 / Phase 3)  — Tank: **Furboll**
The big one — 3 phases, **DO NOT lust early.**
- **Phase 1:** tank & spank + poison. Get her to 70%.
- **Phase 2 (the hard one):** Vashj is **invulnerable.** Handle:
  - **Tainted Cores:** **Tainted Elementals** drop cores — **pass them by hand** to the shield generators to drop them. **Coordinate the core relay.**
  - **Enchanted Elementals:** the small adds that stream in (120 killed Tue) — kill them; they drop **Tainted Core** / give the striders.
  - **Coilfang Striders + Coilfang Elites:** kill/kite the ranged adds.
  - **Static Charge:** a chained lightning debuff on players — **move AWAY from others** so it doesn't spread.
  - **Entangle:** Vashj roots the raid periodically — keep moving/decurse.
  - Once all shield generators down → Phase 3.
- **Phase 3:** Vashj attackable again + spawns **flying adds (Toxic Sporebats)**. **LUST here (~6:15)** and burn her while ranged handle sporebats.
- **Callouts:** "P2 — CORES to the generators, relay!" • "Kill the striders/elementals." • "Static Charge on <name> — SPREAD out!" • "Generators down → P3." • "P3 — LUST, ranged on sporebats, BURN Vashj."

---
### SSC Lust cheat-sheet
| Boss | Lust when |
|------|-----------|
| Hydross | On pull (~13s) |
| The Lurker Below | On pull (~15s) |
| Leotheras | Demon/final phase (~1:40) |
| Fathom-Lord Karathress | Boss solo after guards (~60s) |
| Morogrim | Execute after murlocs (~3:20) |
| Lady Vashj | **Phase 3 (~6:15)** |
