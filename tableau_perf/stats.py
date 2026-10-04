"""Aggregate harness result files. Warmup passes are excluded from the measured stats."""

from __future__ import annotations

import json
import statistics
from pathlib import Path


def p95(values: list[float]) -> float:
    """Nearest-rank p95 used by this harness, including on very small samples.

    Kept stable so results from earlier versions stay comparable:
    ``sorted(values)[min(n - 1, round(0.95 * n) - 1)]``.
    """
    if len(values) < 2:
        return values[0]
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(0.95 * len(ordered)) - 1)
    return ordered[index]


def summarize(values: list[float]) -> dict | None:
    if not values:
        return None
    summary = {
        "n": len(values),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "p95": p95(values),
        "min": min(values),
        "max": max(values),
    }
    if len(values) >= 2:
        summary["stdev"] = statistics.stdev(values)
    return summary


def load(path: Path | str) -> dict:
    data = json.loads(Path(path).read_text())
    groups: dict[tuple, dict] = {}
    for row in data.get("results", []):
        if not row.get("ok"):
            continue
        key = (row["idx"], row["label"])
        bucket = groups.setdefault(key, {"warm": [], "warmup": [], "cold": []})
        bucket["warmup" if row.get("warmup") else "warm"].append(row["ms"])
        if not row.get("warmup") and row.get("pass") == 0:
            bucket["cold"].append(row["ms"])
    return {
        "meta": data.get("meta", {}),
        "groups": groups,
        "failed": [row for row in data.get("results", []) if not row.get("ok")],
        "name": Path(path).stem,
    }


def budget_ms(run: dict) -> float | None:
    """Sum of per-step medians. Pauses are not recorded; failed steps are omitted."""
    total = 0.0
    counted = 0
    for bucket in run["groups"].values():
        summary = summarize(bucket["warm"])
        if summary:
            total += summary["median"]
            counted += 1
    return total if counted else None


def _label_keys(groups: dict) -> tuple[dict[str, tuple], list[str]]:
    found: dict[str, tuple] = {}
    duplicates: list[str] = []
    for key in groups:
        label = key[1]
        if label in found:
            duplicates.append(label)
        found[label] = key
    return found, duplicates


def comparison_rows(left: dict, right: dict) -> tuple[list[dict], list[str]]:
    """Pair steps by label. The first run's label order comes first, then labels only on the right."""
    left_keys, left_dupes = _label_keys(left["groups"])
    right_keys, right_dupes = _label_keys(right["groups"])
    labels = list(dict.fromkeys(list(left_keys) + list(right_keys)))
    rows = []
    for label in labels:
        left_summary = summarize(left["groups"][left_keys[label]]["warm"]) if label in left_keys else None
        right_summary = summarize(right["groups"][right_keys[label]]["warm"]) if label in right_keys else None
        row = {"label": label, "a": left_summary, "b": right_summary}
        if left_summary and right_summary:
            delta = right_summary["median"] - left_summary["median"]
            row["delta_ms"] = delta
            row["delta_pct"] = (delta / left_summary["median"] * 100) if left_summary["median"] else 0.0
            if delta < 0:
                row["direction"] = "faster"
            elif delta > 0:
                row["direction"] = "slower"
            else:
                row["direction"] = "same"
        rows.append(row)
    warnings = [f"duplicate step label in A: {label}" for label in left_dupes]
    warnings += [f"duplicate step label in B: {label}" for label in right_dupes]
    return rows, warnings


def step_records(run: dict) -> list[dict]:
    records = []
    for (index, label), bucket in sorted(run["groups"].items()):
        records.append({
            "idx": index,
            "label": label,
            "measured": summarize(bucket["warm"]),
            "warmup": summarize(bucket["warmup"]),
            "cold": summarize(bucket["cold"]),
        })
    return records
