"""Print a single-run summary or an A/B comparison of two result files."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

from tableau_perf.stats import budget_ms, comparison_rows, load, step_records, summarize


def _fmt(ms) -> str:
    return f"{ms / 1000:8.2f}s" if ms is not None else "        —"


def _run_payload(run: dict) -> dict:
    return {
        "name": run["name"],
        "view_url": run["meta"].get("view_url"),
        "recorded_at": run["meta"].get("recorded_at"),
        "budget_ms": budget_ms(run),
        "steps": step_records(run),
        "failed": run["failed"],
    }


def _text_single(run: dict) -> str:
    lines = [f"\n=== {run['name']} ==="]
    meta = run["meta"]
    if meta:
        lines.append(f"view: {meta.get('view_url', '?')}   recorded: {meta.get('recorded_at', '?')}")
    lines.append(f"\n{'step':<52} {'n':>3} {'cold p1':>9} {'median':>9} {'mean':>9} {'p95':>9} {'warmup':>9}")
    lines.append("-" * 106)
    for record in step_records(run):
        measured = record["measured"]
        warmup = record["warmup"]
        cold = record["cold"]
        label = record["label"][:52]
        if measured:
            lines.append(
                f"{label:<52} {measured['n']:>3} {_fmt(cold['median']) if cold else '        —'} "
                f"{_fmt(measured['median'])} {_fmt(measured['mean'])} {_fmt(measured['p95'])} "
                f"{_fmt(warmup['median']) if warmup else '        —'}"
            )
        elif warmup:
            lines.append(
                f"{label:<52} {'0':>3} {'        —'} {'        —'} {'        —'} "
                f"{'        —'} {_fmt(warmup['median'])}"
            )
    budget = budget_ms(run)
    if budget is not None:
        lines.append(f"\ninteraction budget (sum of medians, failed steps omitted): {budget / 1000:.2f}s")
    if run["failed"]:
        lines.append(f"\nfailed steps ({len(run['failed'])}):")
        for row in run["failed"]:
            lines.append(f"  [pass {row['pass'] + 1}] {row['label']}: {row['error']}")
    return "\n".join(lines)


def _text_compare(left: dict, right: dict) -> str:
    rows, warnings = comparison_rows(left, right)
    lines = [f"\n=== A/B: A = {left['name']}   B = {right['name']} ==="]
    for warning in warnings:
        lines.append(f"warning: {warning} (comparison uses the last step with that label)")
    lines.append(f"A view: {left['meta'].get('view_url', '?')}")
    lines.append(f"B view: {right['meta'].get('view_url', '?')}")
    lines.append(f"\n{'step':<46} {'A median':>10} {'B median':>10} {'delta':>9} {'B vs A':>8}")
    lines.append("-" * 88)
    for row in rows:
        left_summary = row["a"]
        right_summary = row["b"]
        label = row["label"][:46]
        if left_summary and right_summary:
            lines.append(
                f"{label:<46} {_fmt(left_summary['median'])} {_fmt(right_summary['median'])} "
                f"{row['delta_ms'] / 1000:+8.2f}s {abs(row['delta_pct']):6.1f}% {row['direction']}"
            )
        else:
            only = "A" if left_summary else "B"
            lines.append(
                f"{label:<46} {_fmt(left_summary['median']) if left_summary else '         —'} "
                f"{_fmt(right_summary['median']) if right_summary else '         —'}   (only in {only})"
            )
    left_budget = budget_ms(left)
    right_budget = budget_ms(right)
    if left_budget is not None and right_budget is not None:
        delta = right_budget - left_budget
        lines.append(
            f"\ninteraction budget: A {left_budget / 1000:.2f}s   B {right_budget / 1000:.2f}s   "
            f"delta {delta / 1000:+.2f}s"
        )
    return "\n".join(lines)


def _csv_single(run: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["step", "n", "cold_p1_ms", "median_ms", "mean_ms", "p95_ms", "warmup_median_ms"])
    for record in step_records(run):
        measured = record["measured"] or {}
        warmup = record["warmup"] or {}
        cold = record["cold"] or {}
        writer.writerow([
            record["label"],
            measured.get("n", 0),
            cold.get("median", ""),
            measured.get("median", ""),
            measured.get("mean", ""),
            measured.get("p95", ""),
            warmup.get("median", ""),
        ])
    return buffer.getvalue().rstrip("\n")


def _csv_compare(left: dict, right: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["step", "a_median_ms", "b_median_ms", "delta_ms", "delta_pct", "direction"])
    for row in comparison_rows(left, right)[0]:
        writer.writerow([
            row["label"],
            row["a"]["median"] if row["a"] else "",
            row["b"]["median"] if row["b"] else "",
            row.get("delta_ms", ""),
            row.get("delta_pct", ""),
            row.get("direction", ""),
        ])
    return buffer.getvalue().rstrip("\n")


def render(runs: list[dict], output_format: str) -> str:
    if output_format == "json":
        payload: dict = {"runs": [_run_payload(run) for run in runs]}
        if len(runs) == 2:
            rows, warnings = comparison_rows(runs[0], runs[1])
            payload["comparison"] = rows
            payload["warnings"] = warnings
        return json.dumps(payload, indent=2)
    if output_format == "csv":
        if len(runs) == 1:
            return _csv_single(runs[0])
        return _csv_compare(runs[0], runs[1])
    chunks = [_text_single(run) for run in runs]
    if len(runs) == 2:
        chunks.append(_text_compare(runs[0], runs[1]))
    return "\n".join(chunks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize harness results, or compare two runs (A then B). "
        "Measured passes only; warmup is shown and excluded from medians.",
    )
    parser.add_argument("results", nargs="+", type=Path, help="one result JSON, or two for an A/B comparison")
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text")
    args = parser.parse_args(argv)
    if len(args.results) > 2:
        parser.error("pass one result file, or exactly two to compare")
    for path in args.results:
        if not path.is_file():
            print(f"result file not found: {path}", file=sys.stderr)
            return 1
    runs = [load(path) for path in args.results]
    print(render(runs, args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
