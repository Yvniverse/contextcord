from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from contextcord.cli import main
from contextcord.config import discover
from contextcord.identity import source_identity
from contextcord.policy import authorize, canonical_host_path
from contextcord.profiles import write_profile
from contextcord.qualification import deploy, record, verify
from contextcord.store import StateStore


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class HarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.repo = Path(self.tmp.name)
        subprocess.check_call(["git", "init", "-q", str(self.repo)])
        git(self.repo, "config", "user.email", "test@example.com"); git(self.repo, "config", "user.name", "Harness Test")
        (self.repo / "AGENTS.md").write_text("# Agent instructions\n", encoding="utf-8")
        (self.repo / "src").mkdir(); (self.repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
        write_profile(self.repo, "generic"); git(self.repo, "add", "."); git(self.repo, "commit", "-qm", "initial")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def start(self, task: str = "t1", scope: str = "code") -> str:
        self.assertEqual(main(["--repo", str(self.repo), "start", "--task-id", task, "--scope", scope, "--json"]), 0)
        with StateStore(self.repo) as store:
            return store.open_sessions(task)[0]["session_id"]

    def add_pass_evidence(self, sid: str, name: str = "unit") -> Path:
        path = self.repo / f"{name}.txt"; path.write_text("PASS\n", encoding="utf-8")
        self.assertEqual(main(["--repo", str(self.repo), "evidence", "add", "--session-id", sid, "--name", name, "--status", "PASS", "--path", path.name]), 0)
        return path

    def complete_generic_workflow(self, task: str, sid: str) -> None:
        self.assertEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", task, "--phase", "authority", "--next-action", "implement", "--session-id", sid]), 0)
        self.assertEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", task, "--phase", "implementation", "--next-action", "test", "--session-id", sid]), 0)
        if not self.repo.joinpath("unit.txt").exists(): self.add_pass_evidence(sid)
        self.assertEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", task, "--phase", "tests", "--next-action", "finish", "--session-id", sid]), 0)

    def test_policy_and_path_canonicalization(self) -> None:
        cfg = discover(self.repo)
        self.assertEqual(canonical_host_path("/" + "mnt/d/data/x"), chr(100) + ":/data/x")
        self.assertTrue(authorize(self.repo, cfg.authority, scope="code", operation="write", target="src/app.py").allowed)
        self.assertFalse(authorize(self.repo, cfg.authority, scope="code", operation="write", target="/" + "tmp/out.txt").allowed)
        self.assertEqual(__import__("contextcord.policy", fromlist=["normalize_target"]).normalize_target(self.repo, ".env")[0], ".env")

    def test_complete_closeout_requires_workflow_and_evidence_then_ci_rehashes(self) -> None:
        sid = self.start(); evidence = self.add_pass_evidence(sid); self.complete_generic_workflow("t1", sid)
        self.assertEqual(main(["--repo", str(self.repo), "finish", "--session-id", sid, "--summary-text", "tested"]), 0)
        receipts = list((self.repo / ".contextcord" / "receipts").glob("*.json")); self.assertEqual(len(receipts), 1)
        self.assertEqual(main(["--repo", str(self.repo), "verify", "--ci"]), 0)
        evidence.write_text("TAMPERED\n", encoding="utf-8")
        self.assertEqual(main(["--repo", str(self.repo), "verify", "--ci"]), 2)
        with StateStore(self.repo) as store:
            ok, bad = store.verify_event_chain(); self.assertTrue(ok, bad)

    def test_workflow_enforces_order_and_phase_contract(self) -> None:
        sid = self.start("t2")
        self.assertNotEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", "t2", "--phase", "tests", "--next-action", "x", "--session-id", sid]), 0)
        self.assertEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", "t2", "--phase", "authority", "--next-action", "implement", "--session-id", sid]), 0)
        self.assertEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", "t2", "--phase", "implementation", "--next-action", "tests", "--session-id", sid]), 0)
        self.assertNotEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", "t2", "--phase", "tests", "--next-action", "x", "--session-id", sid]), 0)
        self.add_pass_evidence(sid)
        self.assertEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", "t2", "--phase", "tests", "--next-action", "x", "--session-id", sid]), 0)

    def test_gated_deploy_requires_workflow_phase_and_task(self) -> None:
        sid = self.start("rel", "release")
        self.assertEqual(main(["--repo", str(self.repo), "authorize", "--scope", "release", "--operation", "deploy", "--target", "staging"]), 3)
        self.assertEqual(main(["--repo", str(self.repo), "authorize", "--task-id", "rel", "--scope", "release", "--operation", "deploy", "--target", "staging", "--session-id", sid]), 3)
        for phase in ["authority", "implementation"]:
            self.assertEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", "rel", "--phase", phase, "--next-action", "next", "--session-id", sid]), 0)
        self.add_pass_evidence(sid)
        self.assertEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", "rel", "--phase", "tests", "--next-action", "qualify", "--session-id", sid]), 0)
        qev = self.repo / ".contextcord/generated/qualification-release.txt"; qev.parent.mkdir(parents=True, exist_ok=True); qev.write_text("ci pass\n", encoding="utf-8")
        record(discover(self.repo), commitish="HEAD", status="PASS", evidence=qev, summary="ci", kind="ci")
        self.assertEqual(main(["--repo", str(self.repo), "state", "advance", "--task-id", "rel", "--phase", "qualification", "--next-action", "deliver", "--session-id", sid]), 0)
        self.assertEqual(main(["--repo", str(self.repo), "authorize", "--task-id", "rel", "--scope", "release", "--operation", "deploy", "--target", "staging", "--session-id", sid]), 0)

    def test_qualification_append_only_and_exact_deploy(self) -> None:
        cfg = discover(self.repo); ev = self.repo / "qualification.txt"; ev.write_text("qualified\n", encoding="utf-8")
        note = record(cfg, commitish="HEAD", status="PASS", evidence=ev, summary="ok", kind="ci")
        self.assertEqual(note["records"][-1]["status"], "PASS")
        value = verify(cfg, commitish="HEAD", profile="candidate"); self.assertEqual(value["status"], "PASS")
        dev = self.repo / "deployment.txt"; dev.write_text("deployed\n", encoding="utf-8")
        deploy(cfg, commitish="HEAD", status="PASS", environment="staging", runtime_revisions=["HEAD"], summary="ok", evidence_paths=[dev])
        value = verify(cfg, commitish="HEAD", require_deployed=True, environment="staging"); self.assertEqual(value["status"], "PASS")
        dev.write_text("tampered\n", encoding="utf-8")
        value = verify(cfg, commitish="HEAD", require_deployed=True, environment="staging"); self.assertEqual(value["integrity_status"], "FAIL")

    def test_pass_deployment_requires_evidence(self) -> None:
        cfg = discover(self.repo)
        with self.assertRaises(ValueError):
            deploy(cfg, commitish="HEAD", status="PASS", environment="staging", runtime_revisions=["HEAD"], summary="missing evidence")

    def test_source_identity_has_distinct_policy_and_truth(self) -> None:
        cfg = discover(self.repo); value = source_identity(cfg)
        self.assertEqual(value["schema"], "contextcord-source-identity-v1")
        self.assertNotEqual(value["truth_fingerprint"]["sha256"], value["policy_fingerprint"]["sha256"])


if __name__ == "__main__": unittest.main()
