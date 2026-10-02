from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from contextcord.cli import main
from contextcord.config import discover
from contextcord.profiles import write_profile
from contextcord.qualification import record as qualification_record, deploy as qualification_deploy
from contextcord.store import StateStore

ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class DeliverySurfaceTests(unittest.TestCase):
    def test_github_workflows_are_yaml_and_portable_bundle_aware(self):
        required = ROOT / "integrations/github/contextcord-enforce-vendored.yml"
        shadow = ROOT / "integrations/github/contextcord-shadow.yml"
        for path in (required, shadow):
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertIsInstance(value, dict)
            self.assertIn("jobs", value)
        req = required.read_text(encoding="utf-8")
        self.assertIn("bundle verify", req)
        self.assertIn("bundle import", req)
        self.assertIn("verify --ci", req)
        self.assertLess(req.index("bundle verify"), req.index("bundle import"))
        self.assertIn("original live store", req)
        self.assertIn("Required Portable Evidence Bundle missing", req)
        sh = shadow.read_text(encoding="utf-8")
        self.assertIn("does NOT certify closeout evidence", sh)

    def test_deployment_phase_requires_evidence_bearing_production_qualification(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.check_call(["git", "init", "-q", str(repo)])
            git(repo, "config", "user.email", "delivery@example.com")
            git(repo, "config", "user.name", "Delivery Test")
            for rel in ["AGENTS.md", "PROJECT_RULES.md", "docs/agent/PROJECT_MEMORY.md", "docs/agent/ENVIRONMENT_AUTHORITY.md", "docs/agent/KNOWN_ISSUES.md"]:
                p = repo / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("v1\n", encoding="utf-8")
            write_profile(repo, "carbon-bot")
            git(repo, "add", "."); git(repo, "commit", "-qm", "initial")
            cfg = discover(repo)
            ci = repo / ".contextcord/generated/ci.txt"; ci.parent.mkdir(parents=True, exist_ok=True); ci.write_text("PASS\n", encoding="utf-8")
            qualification_record(cfg, commitish="HEAD", status="PASS", evidence=ci, summary="ci", kind="ci")
            deploy_ev = repo / ".contextcord/generated/deploy.txt"; deploy_ev.write_text("deployed\n", encoding="utf-8")
            qualification_deploy(cfg, commitish="HEAD", status="PASS", environment="production", runtime_revisions=["HEAD"], summary="deployed", evidence_paths=[deploy_ev])
            value = __import__("contextcord.qualification", fromlist=["verify"]).verify(cfg, commitish="HEAD", profile="production")
            self.assertEqual(value["status"], "PASS")
            deploy_ev.write_text("tampered\n", encoding="utf-8")
            value = __import__("contextcord.qualification", fromlist=["verify"]).verify(cfg, commitish="HEAD", profile="production")
            self.assertEqual(value["integrity_status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
