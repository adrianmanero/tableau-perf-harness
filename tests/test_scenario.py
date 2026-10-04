"""Scenario loading, date tokens, and URL normalization."""

from __future__ import annotations

import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tableau_perf.config import load_config, resolve_view_url  # noqa: E402
from tableau_perf.scenario import (  # noqa: E402
    ScenarioError,
    load_scenario,
    normalize_view_url,
    resolve_date_token,
    strip_sensitive_query,
)


class NormalizeTests(unittest.TestCase):
    def test_browser_url_becomes_embed_url(self):
        url = "https://pod.example.com/#/site/demo/views/Book/Sheet?x=1"
        self.assertEqual(normalize_view_url(url), "https://pod.example.com/t/demo/views/Book/Sheet")

    def test_embed_url_keeps_query_and_drops_fragment(self):
        url = "https://pod.example.com/t/demo/views/Book/Sheet?:iid=1#section"
        self.assertEqual(
            normalize_view_url(url),
            "https://pod.example.com/t/demo/views/Book/Sheet?:iid=1",
        )

    def test_sensitive_query_is_removed_and_other_keys_stay(self):
        url = "https://pod.example.com/t/demo/views/Book/Sheet?:iid=1&token=secret-value"
        cleaned = strip_sensitive_query(url)
        self.assertNotIn("secret-value", cleaned)
        self.assertIn(":iid=1", cleaned)

    def test_url_without_sensitive_query_is_unchanged(self):
        url = "https://pod.example.com/t/demo/views/Book/Sheet?:iid=1"
        self.assertEqual(strip_sensitive_query(url), url)


class DateTokenTests(unittest.TestCase):
    def test_offsets(self):
        today = datetime.date(2024, 3, 31)
        self.assertEqual(resolve_date_token("{today}", today), "2024-03-31")
        self.assertEqual(resolve_date_token("{today-7d}", today), "2024-03-24")
        self.assertEqual(resolve_date_token("{today-1m}", today), "2024-02-29")
        self.assertEqual(resolve_date_token("{year-start}", today), "2024-01-01")
        self.assertEqual(resolve_date_token("{year-start-2y+1d}", today), "2022-01-02")

    def test_non_leap_century(self):
        self.assertEqual(resolve_date_token("{today-1m}", datetime.date(1900, 3, 31)), "1900-02-28")

    def test_leap_century(self):
        self.assertEqual(resolve_date_token("{today-1m}", datetime.date(2000, 3, 31)), "2000-02-29")

    def test_plain_values_pass_through(self):
        today = datetime.date(2024, 1, 1)
        self.assertEqual(resolve_date_token("North", today), "North")
        self.assertEqual(resolve_date_token(3, today), 3)

    def test_unknown_token(self):
        with self.assertRaises(ScenarioError):
            resolve_date_token("{today-1w}", datetime.date(2024, 1, 1))


class LoadTests(unittest.TestCase):
    def test_yaml_resolves_dates_and_normalizes_url(self):
        today = datetime.date(2026, 10, 4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "view.yaml"
            path.write_text(
                "\n".join([
                    "view_url: https://pod.example.com/#/site/demo/views/Book/Sheet?token=secret-value",
                    "warmup_passes: 0",
                    "passes: 2",
                    "steps:",
                    "  - action: parameter",
                    "    name: Start Date",
                    "    value: '{today-7d}'",
                    "    label: start",
                ])
            )
            scenario = load_scenario(path, today=today)
        self.assertEqual(scenario["view_url"], "https://pod.example.com/t/demo/views/Book/Sheet")
        self.assertNotIn("secret-value", json.dumps(scenario))
        self.assertEqual(scenario["steps"][0]["value"], "2026-09-27")
        self.assertEqual(scenario["warmup_passes"], 0)
        self.assertEqual(scenario["interactive_timeout_s"], 300)

    def test_missing_filter_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "view.yaml"
            path.write_text(
                "view_url: https://pod.example.com/t/demo/views/Book/Sheet\n"
                "steps:\n"
                "  - {action: filter, field: Category}\n"
            )
            with self.assertRaises(ScenarioError):
                load_scenario(path)

    def test_view_is_joined_to_server_and_site(self):
        config = {"server": "https://pod.example.com", "site": "demo", "passes": 2, "step_gap_ms": 250}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "view.yaml"
            path.write_text("view: Workbook/Overview\nsteps:\n  - {action: load, label: load view}\n")
            scenario = load_scenario(path, config=config)
        self.assertEqual(scenario["view_url"], "https://pod.example.com/t/demo/views/Workbook/Overview")
        self.assertEqual(scenario["passes"], 2)
        self.assertEqual(scenario["step_gap_ms"], 250)
        self.assertEqual(scenario["warmup_passes"], 1)

    def test_scenario_value_wins_over_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "view.yaml"
            path.write_text(
                "view_url: https://pod.example.com/t/demo/views/Book/Sheet\n"
                "passes: 4\n"
                "steps:\n  - {action: load, label: load view}\n"
            )
            scenario = load_scenario(path, config={"passes": 9, "server": "https://other.example.com", "site": "nope"})
        self.assertEqual(scenario["view_url"], "https://pod.example.com/t/demo/views/Book/Sheet")
        self.assertEqual(scenario["passes"], 4)

    def test_view_without_server_fails(self):
        with self.assertRaises(ScenarioError):
            resolve_view_url({"view": "Workbook/Sheet"}, {})

    def test_example_config_loads(self):
        config = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
        self.assertEqual(config["server"], "https://your-pod.online.tableau.com")
        self.assertEqual(config["site"], "your-site")
        self.assertEqual(config["viewport"], {"width": 1920, "height": 1080})

    def test_server_rejects_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("server: https://user:pw@pod.example.com\nsite: demo\n")
            with self.assertRaises(ScenarioError):
                load_config(path)

    def test_example_templates_load(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("baseline.yaml", "candidate.yaml"):
            scenario = load_scenario(root / "examples" / name, today=datetime.date(2026, 10, 4))
            self.assertIn("/views/", scenario["view_url"])
            self.assertTrue(scenario["steps"])


if __name__ == "__main__":
    unittest.main()
