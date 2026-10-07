from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from contextcord.cli import main
from contextcord.profiles import write_profile
from contextcord.store import StateStore


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def invoke(repo: Path, *args: str) -> tuple[int, dict]:
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        rc = main(["--repo", str(repo), *args])
    return rc, json.loads(out.getvalue())


class HandoffVerifyProfileTests(unittest.TestCase):
    def make_repo(self):
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name)
        subprocess.check_call(["git", "init", "-q", str(repo)])
        git(repo, "config", "user.email", "handoff@example.com")
        git(repo, "config", "user.name", "Handoff Test")
        (repo / "AGENTS.md").write_text("# policy\n", encoding="utf-8")
        write_profile(repo, "generic", state_dir=".contextcord")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "initial")
        return td, repo

    def test_handoff_profile_passes_without_complete_receipt(self) -> None:
        td, repo = self.make_repo()
        try:
            rc, started = invoke(repo, "start", "--task-id", "handoff-task", "--scope", "code", "--json")
            self.assertEqual(rc, 0, started)
            with StateStore(repo) as store:
                sid = store.open_sessions("handoff-task")[0]["session_id"]
            rc, receipt = invoke(
                repo, "finish", "--session-id", sid, "--mode", "handoff",
                "--summary-text", "bounded handoff",
            )
            self.assertEqual(rc, 0, receipt)
            self.assertEqual(receipt["integrity_status"], "PASS")

            rc, value = invoke(repo, "verify", "--profile", "handoff")
            self.assertEqual(rc, 0, value)
            self.assertEqual(value["status"], "PASS")
            self.assertEqual(value["profile"], "handoff")
            self.assertEqual(value["observed_terminal_state"], "HANDOFF")

            rc, value = invoke(repo, "verify", "--profile", "complete")
            self.assertEqual(rc, 2, value)
            self.assertIn("no_complete_closeout_receipt_matches_current_source_identity", value["failures"])
            rc, value = invoke(repo, "verify", "--ci")
            self.assertEqual(rc, 2, value)
            self.assertIn("no_complete_closeout_receipt_matches_current_source_identity", value["failures"])
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
