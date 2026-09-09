import unittest
from unittest.mock import AsyncMock, patch

from backend.analysis.guild import compute_attendance


class GuildAttendanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_attendance_uses_detected_instances_across_phases(self):
        reports = [
            {
                "code": "old-ssc",
                "date": 1_788_900_000_000,
                "players": [
                    {"name": "Alice", "class": "Priest", "present": True},
                ],
            },
            {
                "code": "old-tk",
                "date": 1_788_900_100_000,
                "players": [
                    {"name": "Alice", "class": "Priest", "present": True},
                ],
            },
            {
                "code": "new-mh",
                "date": 1_789_600_000_000,
                "players": [
                    {"name": "Alice", "class": "Priest", "present": True},
                    {"name": "Bob", "class": "Warrior", "present": True},
                ],
            },
            {
                "code": "new-bt",
                "date": 1_789_600_100_000,
                "players": [
                    {"name": "Alice", "class": "Priest", "present": True},
                    {"name": "Bob", "class": "Warrior", "present": False},
                ],
            },
        ]
        report_page = {
            "reports": reports,
            "has_more": False,
        }

        with (
            patch(
                "backend.analysis.guild.fetch_guild_reports",
                new=AsyncMock(return_value=report_page),
            ),
            patch(
                "backend.analysis.guild._fetch_report_instances",
                new=AsyncMock(side_effect=[{"SSC"}, {"TK"}, {"MH"}, {"BT"}]),
            ),
        ):
            result = await compute_attendance(123)

        self.assertEqual(
            [instance["code"] for instance in result["instances"]],
            ["MH", "BT", "SSC", "TK"],
        )
        self.assertEqual(set(result["week_instances"][result["weeks"][0]]), {"MH", "BT"})
        players = {player["name"]: player for player in result["players"]}
        self.assertEqual(players["Alice"]["attendance_pct"], 100.0)
        self.assertEqual(players["Alice"]["instance_weeks"], {
            "SSC": 1, "TK": 1, "MH": 1, "BT": 1,
        })
        self.assertEqual(players["Bob"]["attendance_pct"], 50.0)
        self.assertEqual(players["Bob"]["eligible_lockouts"], 2)
        self.assertEqual(players["Bob"]["first_seen_week"], result["weeks"][0])
        self.assertEqual(players["Bob"]["instance_weeks"]["MH"], 1)


if __name__ == "__main__":
    unittest.main()
