from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_harness.config import discover
from project_harness.policy import authorize
from project_harness.profiles import PROFILES, write_profile
from project_harness.workflow import phase_ids, validate_workflow


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class ProfileTest(unittest.TestCase):
    def test_carbon_profile_extracts_a_to_j_and_protects_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"CARBON_DATA_ROOT": "D:/carbon-transformer-data", "CARBON_STAGING_ROOT": "D:/carbon-transformer-data/session-x"}):
            repo = Path(td)
            subprocess.check_call(["git", "init", "-q", str(repo)])
            (repo / "AGENTS.md").write_text("x")
            (repo / "PROJECT_RULES.md").write_text("x")
            (repo / "docs" / "agent").mkdir(parents=True)
            for name in ["PROJECT_MEMORY.md", "ENVIRONMENT_AUTHORITY.md", "KNOWN_ISSUES.md"]:
                (repo / "docs" / "agent" / name).write_text("x")
            write_profile(repo, "carbon-bot")
            cfg = discover(repo)
            self.assertFalse(validate_workflow(cfg.workflow))
            self.assertEqual(len(phase_ids(cfg.workflow)), 10)
            d1 = authorize(repo, cfg.authority, scope="data-readonly", operation="write", target="/mnt/d/carbon-transformer-data/serving/x")
            self.assertFalse(d1.allowed)
            d2 = authorize(repo, cfg.authority, scope="data-readonly", operation="read", target="/run/desktop/mnt/host/d/carbon-transformer-data/serving/x")
            self.assertTrue(d2.allowed)
            d3 = authorize(repo, cfg.authority, scope="staging", operation="write", target="D:/carbon-transformer-data/session-x/out.txt")
            self.assertTrue(d3.allowed)

    def test_materialbrain_profile_has_exact_sha_probes(self) -> None:
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"MATERIALBRAIN_BASE_URL": "http://127.0.0.1:9999"}):
            repo = Path(td)
            subprocess.check_call(["git", "init", "-q", str(repo)])
            for rel in ["AGENTS.md", "backend/AGENTS.md", "frontend/AGENTS.md", "docs/PROJECT_MEMORY.md", "docs/DOCUMENTATION_MAP.md"]:
                p = repo / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("x")
            write_profile(repo, "materialbrain")
            cfg = discover(repo)
            self.assertEqual([p["id"] for p in cfg.runtime["probes"]], ["backend", "frontend"])
            self.assertTrue(all(p["expected"] == "HEAD" for p in cfg.runtime["probes"]))

    def test_policy_pack_files_match_builtin_profiles(self) -> None:
        root = Path(__file__).resolve().parents[1]
        names = ["project.toml", "truth.toml", "workflow.toml", "authority.toml", "runtime.toml", "evidence.toml", "qualification.toml"]
        for profile, payloads in PROFILES.items():
            pack = root / "policy-packs" / profile / ".harness"
            for name, expected in zip(names, payloads):
                self.assertEqual((pack / name).read_text(encoding="utf-8"), expected, f"policy pack drift: {profile}/{name}")
            self.assertEqual((pack / ".gitignore").read_text(encoding="utf-8"), "generated/\nreceipts/\ndual-run/\n")


if __name__ == "__main__":
    unittest.main()
