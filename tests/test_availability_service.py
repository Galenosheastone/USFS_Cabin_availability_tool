"""Regression tests for the dashboard's date matching and API error handling."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from FS_Cabin_App.availability_service import (
    AccessBlocked, AvailabilityError, fetch_month, load_dashboard_snapshot,
    matching_windows, months_between, parse_month, save_dashboard_snapshot,
    scan_availability,
)


class AvailabilityTests(unittest.TestCase):
    def test_month_boundary(self):
        self.assertEqual(
            months_between(date(2026, 12, 30), date(2027, 1, 2)),
            [date(2026, 12, 1), date(2027, 1, 1)],
        )

    def test_two_nights_checkout_exclusive(self):
        dates = ["2026-10-23", "2026-10-24", "2026-10-27"]
        self.assertEqual(
            matching_windows(dates, date(2026, 10, 23), date(2026, 10, 27), 2),
            [(date(2026, 10, 23), date(2026, 10, 25), 2)],
        )

    def test_weekend_filter_and_reactive_minimum(self):
        dates = ["2026-10-26", "2026-10-27", "2026-10-28"]
        self.assertEqual(len(matching_windows(dates, date(2026, 10, 26), date(2026, 10, 28), 2)), 1)
        self.assertEqual(matching_windows(dates, date(2026, 10, 26), date(2026, 10, 28), 4), [])
        self.assertEqual(matching_windows(dates, date(2026, 10, 26), date(2026, 10, 28), 2, True), [])

    def test_parse_actual_available_not_closed(self):
        campsites = {"1234": {"site": "001", "availabilities": {
            "2026-11-01T00:00:00Z": "Available",
            "2026-11-02T00:00:00Z": "Reserved",
        }}}
        self.assertEqual(parse_month(campsites, date(2026, 11, 1), date(2026, 11, 2)),
                         {"001||1234": ["2026-11-01"]})

    def test_malformed_payload_does_not_become_no_availability(self):
        with self.assertRaises(AvailabilityError):
            parse_month({"1234": {"site": "001"}}, date(2026, 11, 1), date(2026, 11, 2))

    def test_failed_month_is_flagged_unknown(self):
        with patch("FS_Cabin_App.availability_service.fetch_month", side_effect=[
            {"1234": {"site": "001", "availabilities": {"2026-11-01T00:00:00Z": "Available"}}},
            AvailabilityError("timeout"),
        ]), patch("FS_Cabin_App.availability_service.time.sleep"):
            result = scan_availability([{"id": "22", "name": "Test Cabin"}],
                                       date(2026, 11, 1), date(2026, 12, 1))
        self.assertEqual(result["months_checked"], 1)
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["availability"]["22"]["001||1234"], ["2026-11-01"])

    def test_dashboard_cache_does_not_touch_email_state(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            email_state = directory / "state.json"
            email_state.write_text('{"availability": {}}')
            cache_file = directory / "dashboard_state.json"
            snapshot = {"availability": {"22": {}}, "requested_ids": ["22"]}
            save_dashboard_snapshot(cache_file, snapshot)
            self.assertEqual(load_dashboard_snapshot(cache_file), snapshot)
            self.assertEqual(email_state.read_text(), '{"availability": {}}')

    def test_access_blocked_stops_scan(self):
        class FakeResponse:
            status_code = 403
        class FakeSession:
            def get(self, *args, **kwargs):
                return FakeResponse()
        with self.assertRaises(AccessBlocked):
            fetch_month(FakeSession(), "22", date(2026, 11, 1))

    def test_catalog_grouping_and_unique_ids(self):
        from pathlib import Path
        import yaml
        catalog = yaml.safe_load((Path(__file__).parents[1] / "FS_Cabin_App" / "config.yaml").read_text())
        cabins = catalog["campgrounds"]
        ids = [str(c["id"]) for c in cabins]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(c.get("forest") and c.get("district") for c in cabins))
        self.assertGreater(len({c["forest"] for c in cabins}), 1)
        self.assertGreater(len({(c["forest"], c["district"]) for c in cabins}), 3)


if __name__ == "__main__":
    unittest.main()
