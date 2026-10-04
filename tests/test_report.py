"""Report aggregation and A/B deltas."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tableau_perf.report_cmd import main, render  # noqa: E402
from tableau_perf.stats import budget_ms, comparison_rows, load, p95, summarize  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class PercentileTests(unittest.TestCase):
    def test_single_value(self):
        self.assertEqual(p95([12.0]), 12.0)

    def test_matches_historical_index(self):
        values = [float(n) for n in range(1, 11)]
        index = min(len(values) - 1, round(0.95 * len(values)) - 1)
        self.assertEqual(p95(values), values[index])

    def test_summary_includes_stdev_only_when_possible(self):
        self.assertNotIn("stdev", summarize([5.0]))
        self.assertIn("stdev", summarize([5.0, 7.0]))


class CompareTests(unittest.TestCase):
    def test_sample_files_show_candidate_faster(self):
        baseline = load(ROOT / "examples" / "sample_baseline.json")
        candidate = load(ROOT / "examples" / "sample_candidate.json")
        self.assertEqual(summarize(baseline["groups"][(0, "load: overview")]["warm"])["median"], 4000)
        self.assertEqual(budget_ms(baseline), 5500)
        rows, warnings = comparison_rows(baseline, candidate)
        self.assertEqual(warnings, [])
        by_label = {row["label"]: row for row in rows}
        self.assertEqual(by_label["load: overview"]["direction"], "faster")
        self.assertEqual(by_label["load: overview"]["delta_ms"], -1500)
        text = render([baseline, candidate], "text")
        self.assertIn("faster", text)
        self.assertIn("interaction budget", text)
        self.assertNotIn("9000", text.split("load: overview")[1].split("\n", 1)[0])

    def test_warmup_is_excluded_and_cold_pass_is_kept(self):
        payload_path = ROOT / "examples" / "sample_baseline.json"
        run = load(payload_path)
        warm = run["groups"][(0, "load: overview")]["warm"]
        warmup = run["groups"][(0, "load: overview")]["warmup"]
        self.assertEqual(warmup, [9000])
        self.assertNotIn(9000, warm)
        self.assertEqual(run["groups"][(0, "load: overview")]["cold"], [])

    def test_cli_on_samples(self):
        code = main([
            str(ROOT / "examples" / "sample_baseline.json"),
            str(ROOT / "examples" / "sample_candidate.json"),
            "--format",
            "json",
        ])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
