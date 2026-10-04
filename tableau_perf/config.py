"""Shared Tableau server settings and run defaults."""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import yaml

from tableau_perf.scenario import ScenarioError

REPO_ROOT = Path(__file__).resolve().parents[1]

_INT_KEYS = {
    "warmup_passes": 0,
    "passes": 1,
    "step_gap_ms": 0,
    "interactive_timeout_s": 1,
    "timeout_s": 1,
}


def load_config(path: Path | None = None, cwd: Path | None = None) -> dict:
    """Load config.yaml. An explicit path is required to exist. Otherwise use the first file found."""
    if path is not None:
        if not path.is_file():
            raise ScenarioError(f"config not found: {path}")
        return _read_config(path)
    start = cwd or Path.cwd()
    for candidate in (start / "config.yaml", REPO_ROOT / "config.yaml"):
        if candidate.is_file():
            return _read_config(candidate)
    return {}


def _read_config(path: Path) -> dict:
    raw = yaml.safe_load(path.read_text())
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ScenarioError(f"{path} must be a mapping")
    config = dict(raw)
    if "server" in config and config["server"] is not None:
        config["server"] = _server(str(config["server"]))
    if "site" in config and config["site"] is not None:
        site = str(config["site"]).strip()
        if not site or "/" in site or " " in site:
            raise ScenarioError("site must be the site content URL, without spaces or slashes")
        config["site"] = site
    for key, minimum in _INT_KEYS.items():
        if key not in config or config[key] is None:
            continue
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ScenarioError(f"{key} must be an integer >= {minimum}")
    if "headless" in config and not isinstance(config["headless"], bool):
        raise ScenarioError("headless must be true or false")
    if "viewport" in config and config["viewport"] is not None:
        config["viewport"] = _viewport(config["viewport"])
    if "profile" in config and config["profile"] is not None:
        config["profile"] = str(config["profile"])
    return config


def _server(value: str) -> str:
    parts = urllib.parse.urlsplit(value.strip())
    if parts.scheme != "https" or not parts.netloc or parts.path not in ("", "/"):
        raise ScenarioError("server must be an https origin, such as https://your-pod.online.tableau.com")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ScenarioError("server must be an origin, without credentials or a query string")
    return f"https://{parts.netloc}"


def _viewport(value) -> dict:
    if not isinstance(value, dict):
        raise ScenarioError("viewport must be a mapping with width and height")
    cleaned = {}
    for key in ("width", "height"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ScenarioError(f"viewport.{key} must be a positive integer")
        cleaned[key] = number
    return cleaned


def resolve_view_url(scenario: dict, config: dict) -> str:
    """Full view URL from the scenario, or `view` joined to server and site."""
    if scenario.get("view_url"):
        return str(scenario["view_url"])
    view = scenario.get("view")
    if not view:
        raise ScenarioError("scenario needs 'view_url', or 'view' plus server and site in config.yaml")
    view = str(view).strip()
    if view.startswith("https://"):
        return view
    server = config.get("server")
    site = config.get("site")
    if not server or not site:
        raise ScenarioError("'view' needs server and site in config.yaml")
    view = view.removeprefix("views/").strip("/")
    if not view or ".." in view.split("/"):
        raise ScenarioError("'view' must look like Workbook/Sheet")
    return f"{server}/t/{site}/views/{view}"
