"""Load, validate, and resolve a scenario file."""

from __future__ import annotations

import datetime
import json
import re
import sys
import urllib.parse
from pathlib import Path

import yaml

_SENSITIVE_QUERY = re.compile(r"(token|ticket|secret|password)", re.IGNORECASE)

_ACTIONS = {
    "load": set(),
    "tab": {"name"},
    "parameter": {"name", "value"},
    "filter": {"field"},
    "clear_filter": {"field"},
    "select_marks": {"sheet", "field"},
    "clear_selection": {"sheet"},
    "refresh": set(),
    "pause": set(),
}


class ScenarioError(ValueError):
    """A scenario file is missing data or uses an unsupported value."""


def normalize_view_url(url: str) -> str:
    """Accept a browser URL (`…/#/site/<site>/views/…`) or an embed URL.

    The Embedding API needs the embed form (`…/t/<site>/views/…`).
    Query strings on a browser URL are dropped. An embed URL keeps its
    query string and loses any fragment.
    """
    match = re.match(r"(https://[^/]+)/#/site/([^/]+)/views/(.+)", url)
    if match:
        host, site, rest = match.groups()
        rest = rest.split("?")[0]
        return f"{host}/t/{site}/views/{rest}"
    if "/views/" in url:
        return url.split("#")[0]
    return url


def sensitive_query_names(url: str) -> list[str]:
    """Names of credential-like query parameters, including ones sitting after a hash."""
    names = []
    for match in re.finditer(r"[?&]([^=&#]+)=", url):
        key = urllib.parse.unquote_plus(match.group(1))
        if _SENSITIVE_QUERY.search(key):
            names.append(key)
    return names


def strip_sensitive_query(url: str) -> str:
    """Drop credential-like query parameters from an already-normalized URL.

    URLs with no such parameters are returned unchanged, so Tableau's `:`
    query keys are not re-encoded.
    """
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if not any(_SENSITIVE_QUERY.search(key) for key, _ in pairs):
        return url
    kept = [(key, value) for key, value in pairs if not _SENSITIVE_QUERY.search(key)]
    query = urllib.parse.urlencode(kept, safe=":")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def resolve_date_token(value, today: datetime.date):
    """Resolve `{today}`, `{today-Nd}`, `{today-Nm}`, `{year-start}`, `{year-start-Ny+Nd}`.

    Any other value is returned unchanged.
    """
    if not (isinstance(value, str) and value.startswith("{") and value.endswith("}")):
        return value
    token = value[1:-1]
    if token == "today":
        resolved = today
    elif re.fullmatch(r"today-\d+d", token):
        resolved = today - datetime.timedelta(days=int(token[6:-1]))
    elif re.fullmatch(r"today-\d+m", token):
        months = int(token[6:-1])
        month = today.month - months
        year = today.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        last_day = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
        resolved = datetime.date(year, month, min(today.day, last_day))
    elif re.fullmatch(r"year-start(?:-\d+y)?(?:\+\d+d)?", token):
        match = re.fullmatch(r"year-start(?:-(\d+)y)?(?:\+(\d+)d)?", token)
        years_back = int(match.group(1) or 0)
        days_forward = int(match.group(2) or 0)
        resolved = datetime.date(today.year - years_back, 1, 1) + datetime.timedelta(days=days_forward)
    else:
        raise ScenarioError(
            f"unknown date token '{value}' (supported: {{today}}, {{today-Nd}}, "
            f"{{today-Nm}}, {{year-start}}, {{year-start-Ny}}, {{year-start-Ny+Nd}})"
        )
    return resolved.isoformat()


def view_slug(url: str) -> str:
    """Filesystem-safe last segment of a view URL, used in result filenames."""
    tail = url.rstrip("/").split("/")[-1]
    tail = tail.split("?")[0].split("#")[0]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", tail).strip("._")
    return safe or "view"


def _require_mapping(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ScenarioError(f"{label} must be a mapping")
    return value


def _validate_steps(steps) -> None:
    if not isinstance(steps, list) or not steps:
        raise ScenarioError("steps must be a non-empty list")
    for index, step in enumerate(steps, start=1):
        step = _require_mapping(step, f"steps[{index}]")
        action = step.get("action")
        if action not in _ACTIONS:
            known = ", ".join(sorted(_ACTIONS))
            raise ScenarioError(f"steps[{index}] has unknown action '{action}' (known: {known})")
        missing = [key for key in sorted(_ACTIONS[action]) if key not in step]
        if missing:
            raise ScenarioError(f"steps[{index}] action '{action}' is missing {', '.join(missing)}")
        if action in ("filter", "select_marks") and "values" not in step and "value" not in step:
            raise ScenarioError(f"steps[{index}] action '{action}' needs 'values' or 'value'")


def _positive_int(scenario: dict, key: str, default: int, minimum: int) -> int:
    raw = scenario.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum:
        raise ScenarioError(f"{key} must be an integer >= {minimum}")
    return raw


def load_scenario(path: Path, today: datetime.date | None = None) -> dict:
    """Read YAML or JSON, normalize the view URL, and resolve date tokens in place."""
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    scenario = _require_mapping(raw, "scenario")
    if "view_url" not in scenario or "steps" not in scenario:
        missing = "view_url" if "view_url" not in scenario else "steps"
        raise ScenarioError(f"scenario is missing required key '{missing}'")

    raw_url = str(scenario["view_url"])
    removed = sensitive_query_names(raw_url)
    view_url = strip_sensitive_query(normalize_view_url(raw_url))
    parsed = urllib.parse.urlsplit(view_url)
    if parsed.scheme != "https" or not parsed.netloc or "/views/" not in parsed.path:
        raise ScenarioError("view_url must be an https Tableau view URL containing /views/")
    if parsed.username or parsed.password:
        raise ScenarioError("view_url must not include credentials")
    if removed:
        print(
            f"warning  : removed sensitive query parameter(s) from view URL: {', '.join(removed)}",
            file=sys.stderr,
        )
    scenario["view_url"] = view_url

    scenario["warmup_passes"] = _positive_int(scenario, "warmup_passes", 1, 0)
    scenario["passes"] = _positive_int(scenario, "passes", 3, 1)
    scenario["step_gap_ms"] = _positive_int(scenario, "step_gap_ms", 0, 0)
    scenario["interactive_timeout_s"] = _positive_int(scenario, "interactive_timeout_s", 300, 1)
    _validate_steps(scenario["steps"])

    today = today or datetime.date.today()
    for step in scenario["steps"]:
        if "value" in step:
            resolved = resolve_date_token(step["value"], today)
            if resolved != step["value"]:
                print(f"resolved : {step.get('label', step['value'])} -> {resolved}", file=sys.stderr)
            step["value"] = resolved
        if "values" in step:
            step["values"] = [resolve_date_token(item, today) for item in step["values"]]
    return scenario
