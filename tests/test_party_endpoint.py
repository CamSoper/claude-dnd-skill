"""Tests for the /party roster endpoint in dnd-display-app.

/party feeds the phone first-screen character picker. The display only learns the
full party from a live push_stats /stats POST (which the headless driver runs
during a turn) — but a player can't trigger the first turn until they pick a
character. /party breaks that chicken-and-egg by reading the roster from disk:

  1. live _current_stats players (authoritative once a turn has pushed them),
  2. campaign characters/<Name>.md stems,
  3. the state.md **Party:** line.

These tests pin that resolution order so the picker can't silently regress to
hanging on "Loading party…".
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
DISPLAY = REPO / "skills" / "dnd" / "display"


def _load_app_module():
    """Import dnd-display-app.py under a unique name (same pattern as
    test_phone_presence.py — the filename's hyphen blocks a normal import)."""
    spec = importlib.util.spec_from_file_location(
        "_party_app_under_test", DISPLAY / "dnd-display-app.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_party_app_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class PartyEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _load_app_module()
        cls.client = cls.app.app.test_client()

    def setUp(self) -> None:
        # Each test gets its own temp data root + campaign dir.
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.camp_dir = self.root / "campaigns" / "Embertide"
        self.camp_dir.mkdir(parents=True)

        # Save and redirect the module globals /party reads.
        self._orig_camp_file = self.app.CAMP_FILE
        self._orig_find = self.app._find_campaign
        self._orig_stats = self.app._current_stats

        camp_marker = self.root / ".campaign"
        camp_marker.write_text("Embertide")
        self.app.CAMP_FILE = str(camp_marker)
        self.app._find_campaign = lambda name: self.root / "campaigns" / name
        self.app._current_stats = {}   # force the disk-read path by default

    def tearDown(self) -> None:
        self.app.CAMP_FILE = self._orig_camp_file
        self.app._find_campaign = self._orig_find
        self.app._current_stats = self._orig_stats
        self._tmp.cleanup()

    def _names(self, resp):
        return [p["name"] for p in resp.get_json()["players"]]

    def test_reads_pc_names_from_characters_dir(self) -> None:
        chars = self.camp_dir / "characters"
        chars.mkdir()
        (chars / "Mira.md").write_text("# Mira")
        (chars / "Thorne.md").write_text("# Thorne")
        resp = self.client.get("/party")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._names(resp), ["Mira", "Thorne"])  # sorted

    def test_live_stats_take_precedence_over_disk(self) -> None:
        chars = self.camp_dir / "characters"
        chars.mkdir()
        (chars / "StaleFromDisk.md").write_text("# Stale")
        self.app._current_stats = {"players": [{"name": "Aldric"}, {"name": "Kat"}]}
        resp = self.client.get("/party")
        self.assertEqual(self._names(resp), ["Aldric", "Kat"])

    def test_state_md_party_line_fallback(self) -> None:
        # No characters/ dir → fall back to the state.md **Party:** line. The name
        # is the text before the em dash; a hyphen inside a name is preserved.
        (self.camp_dir / "state.md").write_text(
            "## Current Situation\n"
            "- **Party:** Mira — Tiefling Warlock 3 | HP 21/21 ; "
            "Jean-Luc — Human Fighter 3 | HP 28/28\n"
        )
        resp = self.client.get("/party")
        self.assertEqual(self._names(resp), ["Mira", "Jean-Luc"])

    def test_no_campaign_returns_empty(self) -> None:
        Path(self.app.CAMP_FILE).write_text("")   # no active campaign
        resp = self.client.get("/party")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._names(resp), [])

    def test_empty_roster_returns_empty_list(self) -> None:
        # Campaign set but no characters/ and no state.md → empty, not an error.
        resp = self.client.get("/party")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"players": []})


if __name__ == "__main__":
    unittest.main()
