from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from contextcord.util import _link_or_reparse_point, _repository_alias_candidate, ensure_repo_path


class RepositoryPathAliasTests(unittest.TestCase):
    def test_existing_ancestor_identity_accepts_only_same_repository(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            candidate = repo / "future" / "evidence.json"
            self.assertEqual(_repository_alias_candidate(repo, candidate, label="evidence"), candidate)
            resolved, rel = ensure_repo_path(repo, candidate, label="evidence")
            self.assertEqual(resolved, candidate)
            self.assertEqual(rel, "future/evidence.json")

    def test_real_windows_short_name_uses_same_directory_without_extra_permissions(self):
        with tempfile.TemporaryDirectory(prefix="ContextCord-path-alias-") as td:
            repo = Path(td).resolve()
            alias = Path(td)
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                function = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
                function.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
                function.restype = wintypes.DWORD
                buffer = ctypes.create_unicode_buffer(32768)
                self.assertGreater(function(str(repo), buffer, len(buffer)), 0)
                alias = Path(buffer.value)
            resolved, rel = ensure_repo_path(repo, alias / "qualification.txt", label="evidence")
            self.assertEqual(resolved, repo / "qualification.txt")
            self.assertEqual(rel, "qualification.txt")

    def test_outside_absolute_file_and_parent_traversal_still_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td).resolve()
            repo = base / "repo"
            repo.mkdir()
            outside = base / "outside.txt"
            outside.write_text("fixture", encoding="utf-8")
            for candidate in (outside, Path("../outside.txt")):
                with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, "outside_repository"):
                    ensure_repo_path(repo, candidate, label="evidence")

    def test_samefile_evidence_is_required_not_just_resolve(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            with patch.object(Path, "samefile", return_value=False), self.assertRaisesRegex(ValueError, "outside_repository"):
                _repository_alias_candidate(repo, repo / "future.txt", label="evidence")

    def test_parent_link_above_alias_root_cannot_bypass_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            with patch("contextcord.util._link_or_reparse_point", side_effect=lambda p: p == repo.parent), self.assertRaisesRegex(ValueError, "traverses_symlink"):
                _repository_alias_candidate(repo, repo / "future.txt", label="evidence")

    def test_python311_reparse_attribute_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fixture.txt"
            path.write_text("fixture", encoding="utf-8")
            with patch.object(Path, "lstat", return_value=SimpleNamespace(st_file_attributes=0x400, st_mode=0)):
                self.assertTrue(_link_or_reparse_point(path))

    def test_final_resolution_is_rechecked_against_escape(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td).resolve()
            repo = base / "repo"
            repo.mkdir()
            candidate = repo / "evidence.txt"
            original = Path.resolve
            def redirect(path, *args, **kwargs):
                return base / "escaped.txt" if path == candidate else original(path, *args, **kwargs)
            with patch.object(Path, "resolve", redirect), self.assertRaisesRegex(ValueError, "resolves_outside_repository"):
                ensure_repo_path(repo, candidate, label="evidence")

    def test_external_permission_remains_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td).resolve()
            repo = base / "repo"
            repo.mkdir()
            external = base / "external.txt"
            with self.assertRaises(ValueError):
                ensure_repo_path(repo, external, label="evidence")
            resolved, rel = ensure_repo_path(repo, external, label="evidence", allow_external=True)
            self.assertEqual(resolved, external)
            self.assertEqual(rel, str(external))


if __name__ == "__main__":
    unittest.main()
