from pathlib import Path
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from stage_public_release import stage, content_manifest, checked_path, load_allowlist, is_link
from check_public_release import check, scan_payloads


class PublicReleaseTests(unittest.TestCase):
    def fixture(self, root):
        (root / "support").mkdir()
        (root / "README.md").write_text("# Product\n", encoding="utf-8")
        rules = {"schema": "contextcord-public-allowlist-v1", "files": [{"path": "README.md", "category": "documentation"}, {"path": "support/public_release_allowlist.json", "category": "tooling"}]}
        (root / "support/public_release_allowlist.json").write_text(json.dumps(rules), encoding="utf-8")
        return rules

    def test_unknown_file_under_product_directory_is_not_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "src").mkdir()
            (root / "src/unreviewed.py").write_text("new_source = True\n", encoding="utf-8")
            output = stage(root, root / ".work/candidate")
            self.assertFalse((output / "src").exists())
            self.assertEqual(check(output)["status"], "PASS")

    def test_missing_reviewed_file_fails_before_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "README.md").unlink()
            with self.assertRaisesRegex(ValueError, "missing_inventory_file"):
                stage(root, root / ".work/candidate")
            self.assertFalse((root / ".work/candidate").exists())

    def test_traversal_globs_and_case_collisions_are_rejected(self):
        for bad in ("../outside", "src/*.py", "src/../outside", "README.md/"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rules = self.fixture(root)
                rules["files"].append({"path": bad, "category": "source"})
                (root / "support/public_release_allowlist.json").write_text(json.dumps(rules))
                with self.assertRaises(ValueError):
                    load_allowlist(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rules = self.fixture(root)
            rules["files"].append({"path": "readme.md", "category": "source"})
            (root / "support/public_release_allowlist.json").write_text(json.dumps(rules))
            with self.assertRaises(ValueError):
                load_allowlist(root)

    def test_source_and_destination_link_ancestors_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with patch.object(Path, "is_symlink", lambda path: path.name == "support"):
                with self.assertRaisesRegex(ValueError, "link_forbidden"):
                    checked_path(root, "support/public_release_allowlist.json")
            with patch.object(Path, "is_symlink", lambda path: path.name == ".work"):
                with self.assertRaisesRegex(ValueError, "link_forbidden"):
                    stage(root, root / ".work/candidate")

    def test_existing_destination_and_source_root_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            output = stage(root, root / ".work/candidate")
            before = (output / "README.md").read_bytes()
            for destination in (output, root, root / "src/replacement"):
                with self.assertRaises(ValueError):
                    stage(root, destination)
            self.assertEqual((output / "README.md").read_bytes(), before)

    def test_reparse_attributes_are_rejected_on_older_python(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.txt"
            path.write_text("fixture", encoding="utf-8")
            with patch.object(Path, "lstat", return_value=SimpleNamespace(st_file_attributes=0x400, st_mode=0)):
                self.assertTrue(is_link(path))

    def test_manifest_rejects_changed_and_unexpected_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            output = stage(root, root / ".work/candidate")
            manifest = content_manifest(output)
            self.assertEqual(check(output, manifest=manifest)["status"], "PASS")
            (output / "README.md").write_text("changed\n")
            self.assertIn("content_manifest_mismatch", check(output, manifest=manifest)["errors"])
            (output / "unexpected.py").write_text("added = True\n")
            self.assertIn("unexpected:unexpected.py", check(output)["errors"])

    def test_content_scanner_applies_to_names_and_all_text_files(self):
        self.assertTrue(scan_payloads({".git/config": b"metadata"}))
        self.assertTrue(scan_payloads({"state.sqlite3": b"state"}))
        self.assertTrue(scan_payloads({"web/page.html": b"product"}))
        self.assertTrue(scan_payloads({"LICENSE": ("/mnt/" + "data/private.json").encode()}))
        self.assertTrue(scan_payloads({"fixture.py": ("sk" + "-" + "a" * 16).encode()}))
        self.assertEqual(scan_payloads({"fixture.py": b'token = "test-token-placeholder"\n'}), [])

    def test_review_sidecars_are_rejected_even_if_inventory_includes_them(self):
        for name in ("REVIEW_RELEASE_REPORT.md", "REVIEW_RELEASE_CHECKS.json", "REVIEW_CONTENT_MANIFEST.json", "PRIVATE_CHANGE_SUMMARY.md"):
            with self.subTest(name=name):
                self.assertIn(f"forbidden_payload:docs/{name}", scan_payloads({f"docs/{name}": b"review metadata"}))

    def test_actual_inventory_files_exist(self):
        inventory = load_allowlist(ROOT)
        self.assertTrue({"src/contextcord/handoff.py", "evaluation/continuity/results.json", "evaluation/typed_decisions/gate_cases.json", "scripts/stage_public_release.py"} <= set(inventory))
        for name in inventory:
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
