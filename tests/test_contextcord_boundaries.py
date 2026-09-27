from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from contextcord.config import ConfigError, discover
from contextcord.profiles import write_profile
from contextcord.util import ensure_repo_path


@unittest.skipUnless(os.name != "nt", "Linux symlink boundary regression runs in Linux CI")
class ContextCordLinuxBoundaryTests(unittest.TestCase):
    def _repo(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name)
        (repo / "AGENTS.md").write_text("trusted rules\n", encoding="utf-8")
        write_profile(repo, "generic", state_dir=".contextcord")
        return td, repo

    def test_generic_path_helper_keeps_value_error_contract(self) -> None:
        td, repo = self._repo()
        try:
            with self.assertRaises(ValueError):
                ensure_repo_path(repo, Path("..") / "outside", label="generic")
        finally:
            td.cleanup()

    def test_symlinked_project_config_becomes_config_error(self) -> None:
        td, repo = self._repo()
        try:
            project = repo / ".contextcord" / "project.toml"
            target = repo / "project-target.toml"
            target.write_text(project.read_text(encoding="utf-8"), encoding="utf-8")
            project.unlink()
            project.symlink_to(target)
            with self.assertRaises(ConfigError):
                discover(repo)
        finally:
            td.cleanup()

    def test_symlinked_trusted_entrypoint_becomes_config_error(self) -> None:
        td, repo = self._repo()
        try:
            agents = repo / "AGENTS.md"
            target = repo / "trusted-target.md"
            target.write_text(agents.read_text(encoding="utf-8"), encoding="utf-8")
            agents.unlink()
            agents.symlink_to(target)
            with self.assertRaises(ConfigError):
                discover(repo)
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
