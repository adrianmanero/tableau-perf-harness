"""Runner helpers that do not open a browser."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tableau_perf.run import ensure_profile_safe, main, start_server  # noqa: E402
from tableau_perf.scenario import ScenarioError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    def test_profile_inside_the_repo_is_refused(self):
        with self.assertRaises(ScenarioError):
            ensure_profile_safe(ROOT / "profile")

    def test_clear_session_uses_the_override_and_not_the_home_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "session"
            profile.mkdir()
            (profile / "cookie").write_text("nope")
            previous = os.environ.get("TABLEAU_PERF_PROFILE")
            os.environ["TABLEAU_PERF_PROFILE"] = str(profile)
            try:
                code = main(["--clear-session"])
            finally:
                if previous is None:
                    os.environ.pop("TABLEAU_PERF_PROFILE", None)
                else:
                    os.environ["TABLEAU_PERF_PROFILE"] = previous
            self.assertEqual(code, 0)
            self.assertFalse(profile.exists())


class DryRunTests(unittest.TestCase):
    def test_dry_run_prints_resolved_scenario_without_a_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "view.yaml"
            path.write_text(
                "view_url: https://pod.example.com/#/site/demo/views/Book/Sheet?access_token=secret-value\n"
                "steps:\n"
                "  - {action: load, label: load view}\n"
            )
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main([str(path), "--dry-run"])
        self.assertEqual(code, 0)
        text = buffer.getvalue()
        self.assertNotIn("secret-value", text)
        payload = json.loads(text)
        self.assertEqual(payload["view_url"], "https://pod.example.com/t/demo/views/Book/Sheet")
        self.assertEqual(payload["steps"][0]["action"], "load")


class ServerTests(unittest.TestCase):
    def test_only_the_runner_and_scenario_are_served(self):
        server = start_server(b"<html>ok</html>", b'{"steps":[]}')
        port = server.server_address[1]
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/runner.html") as response:
                self.assertEqual(response.read(), b"<html>ok</html>")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/scenario.json") as response:
                self.assertEqual(response.read(), b'{"steps":[]}')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/results/secret.json")
            self.assertEqual(caught.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
