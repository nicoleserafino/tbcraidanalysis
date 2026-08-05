# MRT Automarking — source-verified behavior

✅ **Verified against MRT source** (`Marks.lua`, Classic MRT). Supersedes earlier versions of this file.

## How the name-based Marks module really works
The options panel has **8 input rows, each permanently tied to ONE raid icon** (the icon is shown beside each row):

| Row | Icon |
|---|---|
| 1 | ⭐ Star |
| 2 | 🟠 Circle |
| 3 | 🔷 Diamond |
| 4 | 🔺 Triangle |
| 5 | 🌙 Moon |
| 6 | 🟦 Square |
| 7 | ❌ Cross (X) |
| 8 | 💀 Skull |

**Rules (from the code):**
1. **Row = icon, fixed.** To give a mob an icon, type its **exact name** in that icon's row. Rows do **not** shift.
2. **One row marks ONE mob.** If you put several names on a row (comma/space separated), only the **first one present** gets marked — it's a *fallback list* (e.g., alternate spawn names), **not** a way to mark multiple mobs.
3. It re-checks every ~0.5s and applies the icon if the named unit exists and isn't already marked.
4. ⚠️ **Unreliable on trash mobs.** It resolves a *name* to a unit — solid for group/raid **players**, flaky for hostile mobs you aren't targeting/nameplating. The tooltip literally says *"Available only for targets, who are the players of group or raid."*

## Practical use for us
Only trust it for a **few uniquely-named, always-present priority mobs**. Good example:

- **Skull row (8):** `Crimson Hand Inquisitor`  ← healer mob, always die first
- **Cross row (7):** `Nether Scryer`            ← arcane caster, interrupt/kill

Leave the rest to manual marking. **Do NOT rely on it for CC** — Sheep/Banish should be **self-marked by the Mage/Warlock** (also avoids re-breaking CC).

## Bottom line
MRT name-automark ≠ a full trash marker. Use it for 1–2 static kill-priority mobs; **manual + self-marked CC** for everything else. Test it on a throwaway pull before trusting it live.
