from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contextcord import __version__
from support.check_public_surface_brand import audit


class PublicSurfaceBrandGateTests(unittest.TestCase):
    def test_unlabeled_legacy_usage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Use project-harness init.\n", encoding="utf-8")
            result = audit(root)
            self.assertEqual("FAIL", result["status"])
            self.assertEqual(1, result["unallowlisted_lines"])

    def test_compatibility_label_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Legacy project-harness compatibility is preserved.\n", encoding="utf-8")
            result = audit(root)
            self.assertEqual("PASS", result["status"])

    def test_current_version_is_contextcord_release(self) -> None:
        self.assertEqual("0.6.2a1", __version__)


if __name__ == "__main__":
    unittest.main()
