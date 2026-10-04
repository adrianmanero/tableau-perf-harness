"""Drive a scenario in Chromium and write step timings."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tableau_perf import __version__
from tableau_perf.scenario import ScenarioError, load_scenario, view_slug

RUNNER_HTML = Path(__file__).resolve().parent / "runner.html"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = Path.home() / ".cache" / "tableau-perf-profile"


def profile_dir() -> Path:
    override = os.environ.get("TABLEAU_PERF_PROFILE")
    if override:
        return Path(override).expanduser()
    return DEFAULT_PROFILE


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def ensure_profile_safe(profile: Path) -> None:
    """The profile stores sign-in cookies. Refuse to keep it inside the repo tree."""
    if _is_inside(profile, REPO_ROOT):
        raise ScenarioError(
            f"browser profile {profile} is inside the repo; "
            "pick a path outside it (it holds sign-in cookies)"
        )


def make_handler(runner_html: bytes, scenario: bytes):
    routes = {
        "/": ("text/html; charset=utf-8", runner_html),
        "/runner.html": ("text/html; charset=utf-8", runner_html),
        "/scenario.json": ("application/json; charset=utf-8", scenario),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — stdlib handler name
            item = routes.get(urllib.parse.urlparse(self.path).path)
            if item is None:
                self.send_error(404)
                return
            content_type, body = item
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002 — stdlib signature
            return

    return Handler


def start_server(runner_html: bytes, scenario: bytes) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runner_html, scenario))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _default_output(scenario_path: Path, scenario: dict) -> Path:
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    name = f"{scenario_path.stem}_{view_slug(scenario['view_url'])}_{stamp}.json"
    return Path.cwd() / "results" / name


def _warn_if_tracked_output(path: Path) -> None:
    if _is_inside(path, REPO_ROOT) and not _is_inside(path, REPO_ROOT / "results"):
        print(
            "warning  : output is inside the repo and outside results/ — do not commit it",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drive a Tableau view in Chromium and save per-step timings.\n\n"
        "The first run opens a window so you can sign in. The session is stored in\n"
        f"{DEFAULT_PROFILE} (override with TABLEAU_PERF_PROFILE) and reused later,\n"
        "including with --headless.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("scenario", type=Path, nargs="?", help="scenario YAML or JSON; not required with --clear-session")
    parser.add_argument("-o", "--out", type=Path, default=None, help="output JSON (default: results/<scenario>_<view>_<time>.json)")
    parser.add_argument("--headless", action="store_true", help="no visible window; needs a profile that is already signed in")
    parser.add_argument("--timeout", type=int, default=3600, help="overall timeout in seconds (default 3600)")
    parser.add_argument("--width", type=int, default=1920, help="viewport width (default 1920)")
    parser.add_argument("--height", type=int, default=1080, help="viewport height (default 1080)")
    parser.add_argument("--dry-run", action="store_true", help="resolve the scenario, print it, and exit")
    parser.add_argument("--fail-on-step-error", action="store_true", help="exit 1 when any measured step fails")
    parser.add_argument(
        "--clear-session",
        action="store_true",
        help=f"delete the browser profile ({DEFAULT_PROFILE}, or TABLEAU_PERF_PROFILE) and exit",
    )
    args = parser.parse_args(argv)

    try:
        profile = profile_dir()
        ensure_profile_safe(profile)
    except ScenarioError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.clear_session:
        if profile.exists():
            shutil.rmtree(profile)
            print(f"cleared  : {profile}")
        else:
            print(f"nothing to clear : {profile} does not exist")
        return 0

    if args.scenario is None:
        parser.error("scenario is required unless --clear-session is given")
    if not args.scenario.is_file():
        print(f"scenario not found: {args.scenario}", file=sys.stderr)
        return 1

    try:
        scenario = load_scenario(args.scenario)
    except ScenarioError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps(scenario, indent=2))
        return 0

    if not RUNNER_HTML.is_file():
        print(f"runner page is missing: {RUNNER_HTML}", file=sys.stderr)
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright is not installed. Run:\n"
            "  python3 -m pip install -r requirements.txt && python3 -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    out = args.out or _default_output(args.scenario, scenario)
    out.parent.mkdir(parents=True, exist_ok=True)
    _warn_if_tracked_output(out)

    server = start_server(RUNNER_HTML.read_bytes(), json.dumps(scenario).encode())
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/runner.html?scenario=scenario.json"
    profile.mkdir(parents=True, exist_ok=True)

    print(f"scenario : {args.scenario.name}")
    print(f"view     : {scenario['view_url']}")
    print(f"passes   : {scenario['warmup_passes']} warmup + {scenario['passes']} measured")
    print(f"runner   : {url}")
    if not args.headless:
        print("NOTE: if the view asks you to sign in, do it once — the session is kept.")

    playwright = None
    ctx = None
    try:
        playwright = sync_playwright().start()
        ctx = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=args.headless,
            viewport={"width": args.width, "height": args.height},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on(
            "console",
            lambda message: print(f"console  : [{message.type}] {message.text}")
            if message.type in ("error", "warning")
            else None,
        )
        page.goto(url)
        try:
            page.wait_for_function("window.__HARNESS_DONE === true", timeout=args.timeout * 1000)
        except Exception:
            shot = out.with_suffix(".stuck.png")
            try:
                page.screenshot(path=str(shot), full_page=True)
                shot_note = str(shot)
            except Exception as shot_error:
                shot_note = f"(screenshot failed: {shot_error})"
            status = page.evaluate(
                "document.getElementById('status') && document.getElementById('status').textContent"
            )
            print(
                f"harness did not finish within {args.timeout}s\n"
                f"  last status : {status}\n"
                f"  screenshot  : {shot_note}\n"
                f"  hint: if the screenshot shows a sign-in page, rerun without --headless and sign in once.",
                file=sys.stderr,
            )
            return 1
        payload = page.evaluate("window.__HARNESS_RESULTS") or {"results": []}
        fatal = page.evaluate("window.__HARNESS_ERROR")
    finally:
        if ctx is not None:
            ctx.close()
        if playwright is not None:
            playwright.stop()
        server.shutdown()
        server.server_close()

    payload["meta"] = {
        "scenario_file": args.scenario.name,
        "view_url": scenario["view_url"],
        "recorded_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "fatal_error": fatal,
        "harness_version": __version__,
        "headless": args.headless,
        "viewport": {"width": args.width, "height": args.height},
    }
    out.write_text(json.dumps(payload, indent=2))
    print(f"\nresults  : {out}")

    steps = payload.get("results", [])
    failed = [row for row in steps if not row.get("ok")]
    print(f"steps    : {len(steps)} recorded, {len(failed)} failed")
    if fatal:
        print(f"FATAL    : {fatal}", file=sys.stderr)
        return 1
    if failed:
        for row in failed:
            print(f"  FAILED [pass {row['pass'] + 1}] {row['label']}: {row['error']}")
        if args.fail_on_step_error:
            return 1
    print(f"\nnext     : python3 report.py {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
