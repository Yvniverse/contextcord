from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contextcord.cli import main
from contextcord.profiles import write_profile


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class HookTest(unittest.TestCase):
    def test_stop_blocks_changed_unclosed_session_then_handoff_closes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); subprocess.check_call(["git", "init", "-q", str(repo)])
            git(repo, "config", "user.email", "test@example.com"); git(repo, "config", "user.name", "Harness Test")
            (repo / "AGENTS.md").write_text("rules\n"); (repo / "a.txt").write_text("a\n"); write_profile(repo, "generic"); git(repo, "add", "."); git(repo, "commit", "-qm", "init")
            payload = json.dumps({"session_id": "abc"})
            with patch("sys.stdin.read", return_value=payload): self.assertEqual(main(["--repo", str(repo), "hook-start", "--host", "codex"]), 0)
            (repo / "a.txt").write_text("changed\n")
            with patch("sys.stdin.read", return_value=payload): self.assertEqual(main(["--repo", str(repo), "hook-stop", "--host", "codex"]), 0)
            sid = "host-codex-abc"
            self.assertEqual(main(["--repo", str(repo), "finish", "--mode", "handoff", "--session-id", sid, "--summary-text", "close"]), 0)
            with patch("sys.stdin.read", return_value=payload): self.assertEqual(main(["--repo", str(repo), "hook-stop", "--host", "codex"]), 0)

    def test_stop_hook_active_does_not_reblock_forever(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); subprocess.check_call(["git","init","-q",str(repo)]); git(repo,"config","user.email","x@y"); git(repo,"config","user.name","x")
            (repo/"AGENTS.md").write_text("rules\n"); (repo/"a.txt").write_text("a\n"); write_profile(repo,"generic"); git(repo,"add","."); git(repo,"commit","-qm","init")
            start=json.dumps({"session_id":"abc"})
            with patch("sys.stdin.read",return_value=start): self.assertEqual(main(["--repo",str(repo),"hook-start","--host","qoder"]),0)
            (repo/"a.txt").write_text("b\n")
            active=json.dumps({"session_id":"abc","stop_hook_active":True})
            with patch("sys.stdin.read",return_value=active): self.assertEqual(main(["--repo",str(repo),"hook-stop","--host","qoder"]),0)

if __name__ == "__main__": unittest.main()
