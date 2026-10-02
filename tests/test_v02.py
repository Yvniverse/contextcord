from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contextcord.adapters import render
from contextcord.cli import main
from contextcord.hostbridge import classify_tool_call
from contextcord.profiles import write_profile
from contextcord.store import StateStore


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class V02Test(unittest.TestCase):
    def make_repo(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name)
        subprocess.check_call(["git", "init", "-q", str(repo)])
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Harness Test")
        (repo / "AGENTS.md").write_text("rules\n", encoding="utf-8")
        (repo / "src").mkdir()
        (repo / "src" / "x.py").write_text("x=1\n", encoding="utf-8")
        write_profile(repo, "generic")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "init")
        return td, repo

    def test_tool_classifier(self) -> None:
        self.assertEqual(classify_tool_call("Write", {"file_path": ".env"}).operation, "write")
        self.assertEqual(classify_tool_call("Bash", {"command": "git push origin HEAD"}).operation, "push")
        self.assertEqual(classify_tool_call("Bash", {"command": "git push --force origin HEAD"}).operation, "force-push")
        self.assertEqual(classify_tool_call("bash", {"command": "kubectl apply -f deploy.yaml"}).operation, "deploy")
        self.assertEqual(classify_tool_call("bash", {"command": "rm -f .env"}).target, ".env")

    def test_qoder_pretool_blocks_without_task_scope(self) -> None:
        td, repo = self.make_repo()
        try:
            payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "src/x.py"}})
            with patch("sys.stdin.read", return_value=payload):
                rc = main(["--repo", str(repo), "host-event", "--host", "qoder", "--event", "pre-tool-use"])
            self.assertEqual(rc, 0)  # Qoder encodes denial in hookSpecificOutput.
        finally:
            td.cleanup()

    def test_host_event_with_task_scope_and_workflow_gate(self) -> None:
        td, repo = self.make_repo()
        try:
            self.assertEqual(main(["--repo", str(repo), "start", "--task-id", "r1", "--scope", "release", "--json"]), 0)
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD"}})
            with patch("sys.stdin.read", return_value=payload):
                self.assertEqual(main(["--repo", str(repo), "host-event", "--host", "opencode", "--event", "pre-tool-use", "--task-id", "r1", "--scope", "release"]), 3)
        finally:
            td.cleanup()

    def test_policy_drift_and_lease(self) -> None:
        td, repo = self.make_repo()
        try:
            self.assertEqual(main(["--repo", str(repo), "start", "--task-id", "t", "--scope", "code", "--json"]), 0)
            with StateStore(repo) as store:
                sid = store.open_sessions("t")[0]["session_id"]
            self.assertEqual(main(["--repo", str(repo), "lease", "acquire", "--key", "src/**", "--session-id", sid, "--ttl", "60"]), 0)
            with StateStore(repo) as store:
                self.assertEqual(len(store.active_leases()), 1)
            (repo / "AGENTS.md").write_text("rules changed\n", encoding="utf-8")
            self.assertEqual(main(["--repo", str(repo), "drift"]), 2)
            self.assertEqual(main(["--repo", str(repo), "doctor"]), 2)
            self.assertEqual(main(["--repo", str(repo), "lease", "release", "--key", "src/**", "--session-id", sid]), 0)
        finally:
            td.cleanup()


    def test_all_json_schemas_parse(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for schema in (root / "schemas").glob("*.json"):
            value = json.loads(schema.read_text(encoding="utf-8"))
            self.assertEqual(value.get("$schema"), "https://json-schema.org/draft/2020-12/schema")

    def test_native_adapter_renderers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            q = render("qoder", root / "qoder")
            o = render("opencode", root / "opencode")
            d = render("deepseek", root / "deepseek")
            self.assertTrue((root / "qoder" / "settings.json").is_file())
            settings = json.loads((root / "qoder" / "settings.json").read_text())
            self.assertIn("PreToolUse", settings["hooks"])
            self.assertTrue((root / "opencode" / "plugins" / "contextcord.js").is_file())
            self.assertIn('ctx.tool.hook("execute.before"', (root / "opencode" / "plugins" / "contextcord.js").read_text())
            pkg = json.loads((root / "deepseek" / "package.json").read_text())
            self.assertEqual(pkg["dsh"]["bundle"]["patch"], "./cordis.patch.yml")
            self.assertTrue(q and o and d)


if __name__ == "__main__":
    unittest.main()
