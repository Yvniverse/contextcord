from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from architecture_sync import ACTIVE_VIEWS, GROUPS, current_architecture_status, scan_source_inventory  # noqa: E402
from contextcord.closeout import _architecture_phase  # noqa: E402


class ArchitectureSyncTests(unittest.TestCase):
    def test_inventory_is_scanned_from_real_source_and_has_all_logical_groups(self) -> None:
        inventory = scan_source_inventory(ROOT)
        self.assertEqual(inventory["module_count"], 52)
        self.assertEqual(len(inventory["modules"]), 52)
        self.assertEqual(tuple(inventory["logical_groups"]), GROUPS)
        self.assertEqual(set(inventory["groups"]), set(GROUPS))
        self.assertEqual(inventory["source_inventory_sha256"], scan_source_inventory(ROOT)["source_inventory_sha256"])
        self.assertTrue(all(row["path"].startswith("src/contextcord/") for row in inventory["modules"]))

    def test_active_atlas_contains_only_six_bilingual_views(self) -> None:
        architecture = ROOT / "docs" / "architecture"
        specs = {path.stem.rsplit(".", 1)[0] for path in (architecture / "specs").glob("*.json")}
        maps = {path.stem.rsplit(".", 1)[0] for path in (architecture / "maps").glob("*.html")}
        self.assertEqual(specs, set(ACTIVE_VIEWS))
        self.assertEqual(maps, set(ACTIVE_VIEWS))
        self.assertEqual(len(list((architecture / "specs").glob("*.json"))), 12)
        self.assertEqual(len(list((architecture / "maps").glob("*.html"))), 12)
        self.assertFalse(any("proposed" in path.name for path in (architecture / "maps").iterdir()))

    def test_release_drift_gate_and_closeout_auto_are_synced(self) -> None:
        status = current_architecture_status(ROOT)
        self.assertEqual(status["status"], "SYNCED", status)
        self.assertEqual(status["active_view_ids"], list(ACTIVE_VIEWS))
        self.assertEqual(_architecture_phase(ROOT, "auto")["status"], "SOURCE_UNCHANGED")



if __name__ == "__main__":
    unittest.main()
