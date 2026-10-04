"""Tracked files must stay free of company names and local result data."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "__pycache__", ".venv", "venv", ".pytest_cache", "results"}
# Built without writing the banned words as a contiguous literal.
_COMPANY = "sup" + "er"
_BRAND = _COMPANY + "bet"
BANNED = re.compile(rf"{_BRAND}|\b{_COMPANY}\b", re.IGNORECASE)


class HygieneTests(unittest.TestCase):
    def test_no_company_names(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP for part in path.parts):
                continue
            if "local" in path.parts and "scenarios" in path.parts:
                continue
            if path.suffix.lower() in {".png", ".pyc"}:
                continue
            text = path.read_text(errors="ignore")
            if BANNED.search(text):
                hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [])

    def test_no_home_directory_paths(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or any(part in SKIP for part in path.parts):
                continue
            if "local" in path.parts and "scenarios" in path.parts:
                continue
            if path.suffix.lower() in {".png", ".pyc"}:
                continue
            text = path.read_text(errors="ignore")
            home_markers = ("/" + "Users" + "/", "/" + "home" + "/")
            if any(marker in text for marker in home_markers):
                hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
