from __future__ import annotations

import json
import os
import io
import contextlib
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from contextcord.cli import main
from contextcord.config import discover
from contextcord.hostbridge import authorize_host_action, classify_tool_call
from contextcord.policy import authorize
from contextcord.profiles import write_profile
from contextcord.store import StateStore


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def make_repo(profile: str, env: dict[str, str] | None = None) -> tuple[tempfile.TemporaryDirectory, Path]:
    td = tempfile.TemporaryDirectory()
    repo = Path(td.name)
    subprocess.check_call(["git", "init", "-q", str(repo)])
    git(repo, "config", "user.email", "bench@example.com")
    git(repo, "config", "user.name", "ContextCord Benchmark")
    required = {
        "generic": ["AGENTS.md"],
        "carbon-bot": ["AGENTS.md", "PROJECT_RULES.md", "docs/agent/PROJECT_MEMORY.md", "docs/agent/ENVIRONMENT_AUTHORITY.md", "docs/agent/KNOWN_ISSUES.md"],
        "materialbrain": ["AGENTS.md", "backend/AGENTS.md", "frontend/AGENTS.md", "docs/PROJECT_MEMORY.md", "docs/DOCUMENTATION_MAP.md"],
    }[profile]
    for rel in required:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("benchmark\n", encoding="utf-8")
    with patch.dict(os.environ, env or {}, clear=False):
        write_profile(repo, profile)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "init")
    return td, repo


def record(results, name, expected, observed, detail=""):
    results.append({"scenario": name, "expected": expected, "observed": observed, "pass": expected == observed, "detail": detail})


def run() -> dict:
    results = []

    td, repo = make_repo("generic")
    try:
        cfg = discover(repo)
        record(results, "generic_external_write", "DENY", "ALLOW" if authorize(repo, cfg.authority, scope="code", operation="write", target="/tmp/out").allowed else "DENY")
        with contextlib.redirect_stdout(io.StringIO()):
            main(["--repo", str(repo), "start", "--task-id", "rel", "--scope", "release", "--json"])
        with StateStore(repo) as store:
            action = classify_tool_call("bash", {"command": "git push origin HEAD"})
            d = authorize_host_action(cfg, store, action=action, scope="release", task_id="rel")
            record(results, "early_push_gate", "DENY", "ALLOW" if d["allowed"] else "DENY", d["reason"])
            sid = store.open_sessions("rel")[0]["session_id"]
            first = store.acquire_lease(lease_key="src/**", session_id=sid, task_id="rel", ttl_seconds=60)
            # second synthetic session on same task
            second_sid = store.create_session(task_id="rel", scope="release", head=git(repo, "rev-parse", "HEAD"), fingerprint="x", policy_fingerprint="p")
            second = store.acquire_lease(lease_key="src/**", session_id=second_sid, task_id="rel", ttl_seconds=60)
            record(results, "same_scope_concurrent_writer", "DENY", "ALLOW" if second["acquired"] else "DENY")
    finally:
        td.cleanup()

    td, repo = make_repo("materialbrain", {"MATERIALBRAIN_BASE_URL": "http://127.0.0.1:9"})
    try:
        cfg = discover(repo)
        record(results, "materialbrain_env_write", "DENY", "ALLOW" if authorize(repo, cfg.authority, scope="code", operation="write", target=".env").allowed else "DENY")
        record(results, "materialbrain_backup_delete", "DENY", "ALLOW" if authorize(repo, cfg.authority, scope="release", operation="delete", target="storage/backups/x.zip").allowed else "DENY")
    finally:
        td.cleanup()

    env = {"CARBON_DATA_ROOT": "D:/carbon-transformer-data", "CARBON_STAGING_ROOT": "D:/carbon-transformer-data/session-x"}
    td, repo = make_repo("carbon-bot", env)
    try:
        with patch.dict(os.environ, env, clear=False):
            cfg = discover(repo)
            d1 = authorize(repo, cfg.authority, scope="data-readonly", operation="write", target="/mnt/d/carbon-transformer-data/serving/x")
            record(results, "carbon_wsl_alias_protected_write", "DENY", "ALLOW" if d1.allowed else "DENY")
            d2 = authorize(repo, cfg.authority, scope="staging", operation="write", target="/run/desktop/mnt/host/d/carbon-transformer-data/session-x/out.txt")
            record(results, "carbon_docker_alias_staging_write", "ALLOW", "ALLOW" if d2.allowed else "DENY")
    finally:
        td.cleanup()

    passed = sum(1 for r in results if r["pass"])
    return {"schema": "contextcord-contract-benchmark-v1", "passed": passed, "total": len(results), "pass_rate": passed / len(results), "results": results}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
