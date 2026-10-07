"""Exercise the installed CLI and MCP stdio surface in a disposable Git project."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from contextcord.profiles import write_profile
from contextcord.service import TOOLS, MUTATIONS


def smoke() -> dict:
    with tempfile.TemporaryDirectory(prefix="contextcord-smoke-") as directory:
        root = Path(directory)
        repo = root / "project"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "AGENTS.md").write_text("# Project policy\n", encoding="utf-8")
        (repo / "src").mkdir()
        (repo / "src/client.py").write_text("budget = 3\n", encoding="utf-8")
        write_profile(repo, "generic")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=ContextCord Tests", "-c", "user.email=tests@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"], check=True)
        def cli(*args):
            run = subprocess.run([sys.executable, "-m", "contextcord", "--repo", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=True)
            return json.loads(run.stdout)
        assert cli("doctor")["status"] == "PASS"
        start = cli("start", "--task-id", "continuity", "--scope", "code", "--json")
        cli("memory", "note", "add", "--task-id", "continuity", "--text", "Check bounded retry budget", "--depends-on", "src/client.py")
        cli("finish", "--session-id", start["session_id"], "--mode", "handoff", "--summary-text", "Continue retry checks")
        preview = cli("handoff", "--assist", "--task-id", "continuity")
        assert preview["continuation"]["selected_memory"] and preview["decision_receipt"]["candidate_reduction"]["selector"] == "bm25"
        for allow_mutations in (False, True):
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "contextcord_memory", "arguments": {"task_id": "continuity"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "contextcord_handoff", "arguments": {"task_id": "continuity"}}},
            ]
            command = [sys.executable, "-m", "contextcord", "--repo", str(repo), "mcp"]
            if allow_mutations:
                command.append("--allow-mutations")
            run = subprocess.run(command, input="".join(json.dumps(row) + "\n" for row in messages), capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
            responses = {row["id"]: row for row in map(json.loads, run.stdout.splitlines())}
            actual = {row["name"] for row in responses[2]["result"]["tools"]}
            assert actual == (set(TOOLS) if allow_mutations else set(TOOLS) - MUTATIONS)
            assert responses[3]["result"]["structuredContent"]["task"]["task_id"] == "continuity"
            assert responses[4]["result"]["structuredContent"]["status"] == "AWAITING_CONFIRMATION"
        empty = root / "empty"
        empty.mkdir()
        error = subprocess.run([sys.executable, "-m", "contextcord", "--repo", str(empty), "doctor"], capture_output=True, text=True, encoding="utf-8")
        assert error.returncode == 2 and json.loads(error.stdout)["status"] == "ERROR" and "Traceback" not in error.stderr
    return {"status": "PASS", "declared_tools": len(TOOLS), "readonly_tools": len(TOOLS) - len(MUTATIONS), "cli_handoff": "PASS", "non_git_failure": "PASS"}


if __name__ == "__main__":
    print(json.dumps(smoke(), indent=2))
