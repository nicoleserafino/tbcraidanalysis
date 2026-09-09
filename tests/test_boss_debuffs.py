import unittest

from backend.analysis.boss_debuffs import compute_boss_debuffs


class BossDebuffUptimeTests(unittest.TestCase):
    def test_reports_initial_delay_and_midfight_lapse(self):
        fight = {
            "name": "Test Boss",
            "startTime": 100_000,
            "endTime": 200_000,
        }
        actors = {
            1: {"id": 1, "name": "Tank", "type": "Player"},
            10: {"id": 10, "name": "Test Boss", "type": "NPC"},
        }
        players = {1: actors[1]}
        damage = [
            {"sourceID": 1, "targetID": 10, "timestamp": timestamp}
            for timestamp in range(102_000, 199_000, 8_000)
        ] + [{"sourceID": 1, "targetID": 10, "timestamp": 198_000}]
        debuffs = [
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 105_000, "name": "Sunder Armor"},
            {"type": "removedebuff", "sourceID": 1, "targetID": 10, "timestamp": 150_000, "name": "Sunder Armor"},
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 155_000, "name": "Sunder Armor"},
            {"type": "removedebuff", "sourceID": 1, "targetID": 10, "timestamp": 199_000, "name": "Sunder Armor"},
        ]

        rows, targets = compute_boss_debuffs(
            fight, actors, players, {}, debuffs, damage,
        )

        self.assertEqual(targets, ["Test Boss"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["initial_delay_sec"], 3.0)
        self.assertEqual(rows[0]["lapse_count"], 1)
        self.assertEqual(rows[0]["longest_gap_sec"], 5.0)
        self.assertEqual(rows[0]["drops"], [{"at_sec": 50.0, "duration_sec": 5.0}])
        self.assertEqual(rows[0]["sources"], ["Tank"])

    def test_uses_damageable_phase_as_uptime_window(self):
        fight = {
            "name": "Kael'thas Sunstrider",
            "startTime": 0,
            "endTime": 300_000,
        }
        actors = {
            1: {"id": 1, "name": "Warlock", "type": "Player"},
            10: {"id": 10, "name": "Kael'thas Sunstrider", "type": "NPC"},
        }
        players = {1: actors[1]}
        damage = [
            {"sourceID": 1, "targetID": 10, "timestamp": 200_000},
            {"sourceID": 1, "targetID": 10, "timestamp": 299_000},
        ]
        debuffs = [
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 200_000, "name": "Curse of Elements"},
        ]

        rows, _ = compute_boss_debuffs(
            fight, actors, players, {}, debuffs, damage,
        )

        self.assertEqual(rows[0]["uptime_pct"], 100.0)
        self.assertEqual(rows[0]["initial_delay_sec"], 0.0)

    def test_counts_a_drop_that_is_never_replenished(self):
        fight = {"name": "Test Boss", "startTime": 0, "endTime": 60_000}
        actors = {
            1: {"id": 1, "name": "Tank", "type": "Player"},
            10: {"id": 10, "name": "Test Boss", "type": "NPC"},
        }
        damage = [
            {"sourceID": 1, "targetID": 10, "timestamp": timestamp}
            for timestamp in range(0, 60_000, 10_000)
        ] + [{"sourceID": 1, "targetID": 10, "timestamp": 59_000}]
        debuffs = [
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 0, "name": "Sunder Armor"},
            {"type": "removedebuff", "sourceID": 1, "targetID": 10, "timestamp": 45_000, "name": "Sunder Armor"},
        ]

        rows, _ = compute_boss_debuffs(
            fight, actors, {1: actors[1]}, {}, debuffs, damage,
        )

        self.assertEqual(rows[0]["lapse_count"], 1)
        self.assertEqual(rows[0]["drops"], [{"at_sec": 45.0, "duration_sec": 15.0}])

    def test_excludes_long_untargetable_intermission(self):
        fight = {"name": "Test Boss", "startTime": 0, "endTime": 70_000}
        actors = {
            1: {"id": 1, "name": "Tank", "type": "Player"},
            10: {"id": 10, "name": "Test Boss", "type": "NPC"},
        }
        damage = [
            *[
                {"sourceID": 1, "targetID": 10, "timestamp": timestamp}
                for timestamp in (0, 10_000, 20_000)
            ],
            *[
                {"sourceID": 1, "targetID": 10, "timestamp": timestamp}
                for timestamp in (50_000, 60_000, 69_000)
            ],
        ]
        debuffs = [
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 0, "name": "Misery"},
            {"type": "removedebuff", "sourceID": 1, "targetID": 10, "timestamp": 25_000, "name": "Misery"},
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 50_000, "name": "Misery"},
        ]

        rows, _ = compute_boss_debuffs(
            fight, actors, {1: actors[1]}, {}, debuffs, damage,
        )

        self.assertEqual(rows[0]["uptime_pct"], 100.0)
        self.assertEqual(rows[0]["lapse_count"], 0)

    def test_reports_full_strength_uptime_for_stacked_debuff(self):
        fight = {"name": "Test Boss", "startTime": 0, "endTime": 21_000}
        actors = {
            1: {"id": 1, "name": "Tank", "type": "Player"},
            10: {"id": 10, "name": "Test Boss", "type": "NPC"},
        }
        damage = [
            {"sourceID": 1, "targetID": 10, "timestamp": timestamp}
            for timestamp in (0, 10_000, 20_000)
        ]
        debuffs = [
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 0, "name": "Sunder Armor"},
            *[
                {
                    "type": "applydebuffstack",
                    "sourceID": 1,
                    "targetID": 10,
                    "timestamp": stack * 1_000,
                    "stack": stack + 1,
                    "name": "Sunder Armor",
                }
                for stack in range(1, 5)
            ],
            {"type": "removedebuff", "sourceID": 1, "targetID": 10, "timestamp": 20_000, "name": "Sunder Armor"},
        ]

        rows, _ = compute_boss_debuffs(
            fight, actors, {1: actors[1]}, {}, debuffs, damage,
        )

        self.assertEqual(rows[0]["category"], "Major Armor Reduction")
        self.assertEqual(rows[0]["max_stacks"], 5)
        self.assertEqual(rows[0]["uptime_pct"], 95.2)
        self.assertEqual(rows[0]["full_uptime_pct"], 76.2)
        self.assertEqual(rows[0]["effective_uptime_pct"], 76.2)

    def test_combines_equivalent_armor_debuffs(self):
        fight = {"name": "Test Boss", "startTime": 0, "endTime": 31_000}
        actors = {
            1: {"id": 1, "name": "Tank", "type": "Player"},
            2: {"id": 2, "name": "Rogue", "type": "Player"},
            10: {"id": 10, "name": "Test Boss", "type": "NPC"},
        }
        damage = [
            {"sourceID": 1, "targetID": 10, "timestamp": timestamp}
            for timestamp in (0, 10_000, 20_000, 30_000)
        ]
        debuffs = [
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 0, "name": "Sunder Armor"},
            *[
                {
                    "type": "applydebuffstack",
                    "sourceID": 1,
                    "targetID": 10,
                    "timestamp": stack * 1_000,
                    "stack": stack + 1,
                    "name": "Sunder Armor",
                }
                for stack in range(1, 5)
            ],
            {"type": "removedebuff", "sourceID": 1, "targetID": 10, "timestamp": 15_000, "name": "Sunder Armor"},
            {"type": "applydebuff", "sourceID": 2, "targetID": 10, "timestamp": 15_000, "name": "Expose Armor"},
        ]

        rows, _ = compute_boss_debuffs(
            fight, actors, {1: actors[1], 2: actors[2]}, {}, debuffs, damage,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "Major Armor Reduction")
        self.assertEqual(rows[0]["spells"], ["Expose Armor", "Sunder Armor"])
        self.assertEqual(rows[0]["sources"], ["Rogue", "Tank"])
        self.assertEqual(rows[0]["effective_uptime_pct"], 87.1)
        self.assertEqual(rows[0]["lapse_count"], 0)

    def test_removed_stack_zero_ends_full_strength_coverage(self):
        fight = {"name": "Test Boss", "startTime": 0, "endTime": 21_000}
        actors = {
            1: {"id": 1, "name": "Priest", "type": "Player"},
            10: {"id": 10, "name": "Test Boss", "type": "NPC"},
        }
        damage = [
            {"sourceID": 1, "targetID": 10, "timestamp": timestamp}
            for timestamp in (0, 10_000, 20_000)
        ]
        debuffs = [
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 0, "name": "Shadow Embrace"},
            {"type": "applydebuffstack", "sourceID": 1, "targetID": 10, "timestamp": 0, "stack": 3, "name": "Shadow Embrace"},
            {"type": "removedebuffstack", "sourceID": 1, "targetID": 10, "timestamp": 10_000, "stack": 0, "name": "Shadow Embrace"},
            {"type": "removedebuff", "sourceID": 1, "targetID": 10, "timestamp": 20_000, "name": "Shadow Embrace"},
        ]

        rows, _ = compute_boss_debuffs(
            fight, actors, {1: actors[1]}, {}, debuffs, damage,
        )

        self.assertEqual(rows[0]["full_uptime_pct"], 47.6)

    def test_ignores_subsecond_reapplication_as_a_lapse(self):
        fight = {"name": "Test Boss", "startTime": 0, "endTime": 21_000}
        actors = {
            1: {"id": 1, "name": "Priest", "type": "Player"},
            10: {"id": 10, "name": "Test Boss", "type": "NPC"},
        }
        damage = [
            {"sourceID": 1, "targetID": 10, "timestamp": timestamp}
            for timestamp in (0, 10_000, 20_000)
        ]
        debuffs = [
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 0, "name": "Misery"},
            {"type": "removedebuff", "sourceID": 1, "targetID": 10, "timestamp": 10_000, "name": "Misery"},
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 10_500, "name": "Misery"},
        ]

        rows, _ = compute_boss_debuffs(
            fight, actors, {1: actors[1]}, {}, debuffs, damage,
        )

        self.assertEqual(rows[0]["lapse_count"], 0)
        self.assertEqual(rows[0]["drops"], [])

    def test_tracks_karathress_guardians_as_boss_targets(self):
        fight = {
            "name": "Fathom-Lord Karathress",
            "startTime": 0,
            "endTime": 11_000,
        }
        actors = {
            1: {"id": 1, "name": "Tank", "type": "Player"},
            10: {"id": 10, "name": "Fathom-Guard Sharkkis", "type": "NPC"},
        }
        damage = [
            {"sourceID": 1, "targetID": 10, "timestamp": timestamp}
            for timestamp in (0, 10_000)
        ]
        debuffs = [
            {"type": "applydebuff", "sourceID": 1, "targetID": 10, "timestamp": 0, "name": "Thunder Clap"},
        ]

        rows, targets = compute_boss_debuffs(
            fight, actors, {1: actors[1]}, {}, debuffs, damage,
        )

        self.assertEqual(targets, ["Fathom-Guard Sharkkis"])
        self.assertEqual(rows[0]["target"], "Fathom-Guard Sharkkis")


if __name__ == "__main__":
    unittest.main()
