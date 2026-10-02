from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
import uuid
from .process import capture
from pathlib import Path
from typing import Any

from .config import HarnessConfig
from .contracts import validate
from .evidence import prepare_records, record_prepared
from .hostbridge import authorize_host_action, classify_tool_call
from .identity import source_identity
from .store import StateStore
from .util import ensure_repo_path, safe_id, utc_now


def _redact_bound(text: str, *, patterns: list[str], max_bytes: int) -> tuple[str, int, bool]:
    count = 0; value = text
    for pattern in patterns:
        value, n = re.subn(pattern, "[REDACTED]", value, flags=re.IGNORECASE)
        count += n
    raw = value.encode("utf-8", "replace")
    truncated = len(raw) > max_bytes
    if truncated:
        marker = b"\n[CONTEXTCORD OUTPUT TRUNCATED]\n"
        raw = raw[:max(0, max_bytes - len(marker))] + marker
        value = raw.decode("utf-8", "replace")
    return value, count, truncated


def _cwd(cfg: HarnessConfig, raw: str | None) -> Path:
    candidate = (cfg.repo / raw) if raw and not Path(raw).is_absolute() else (Path(raw) if raw else cfg.repo)
    resolved = candidate.resolve(strict=False)
    allow_external = bool(cfg.evidence.get("rules", {}).get("runner_allow_external_cwd", False))
    if not allow_external:
        try:
            resolved.relative_to(cfg.repo)
        except ValueError as exc:
            raise ValueError(f"runner_cwd_outside_repository:{raw}") from exc
    if not resolved.is_dir():
        raise ValueError(f"runner_cwd_missing:{resolved}")
    return resolved


def _write_log(path: Path, stdout: str, stderr: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "[stdout]\n" + stdout
    if stdout and not stdout.endswith("\n"):
        text += "\n"
    text += "\n[stderr]\n" + stderr
    if stderr and not stderr.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8", errors="replace")


def run_check(
    cfg: HarnessConfig,
    store: StateStore,
    *,
    session_id: str,
    task_id: str,
    name: str,
    command: list[str],
    timeout: float | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    if not command:
        raise ValueError("runner_requires_command")
    rec = store.session(session_id)
    if not rec or rec.get("status") != "OPEN" or rec.get("task_id") != task_id:
        raise ValueError("runner_requires_open_matching_session")
    action = classify_tool_call("Bash", {"command": shlex.join(command)})
    decision = authorize_host_action(cfg, store, action=action, scope=str(rec["scope"]), task_id=task_id, session_id=session_id)
    if decision.get("enforced") and not decision.get("allowed"):
        raise ValueError(f"runner_command_denied:{decision.get('reason')}")
    working = _cwd(cfg, cwd)
    identity_before = source_identity(cfg)
    rules = cfg.evidence.get("rules", {})
    runner_dir = str(rules.get("runner_dir") or f"{cfg.root.name}/generated/evidence")
    runner_root, _ = ensure_repo_path(cfg.repo, Path(runner_dir), label="runner_dir", allow_external=False)
    directory = runner_root / safe_id(session_id)
    safe_name = safe_id(name) + "-" + uuid.uuid4().hex[:12]
    log_path = directory / f"{safe_name}.log"
    meta_path = directory / f"{safe_name}.json"
    started = utc_now(); t0 = time.monotonic(); status = "BLOCKED"; reason = ""; code: int | None = None; out = ""; err = ""
    max_bytes = int(rules.get("runner_max_output_bytes") or 1_048_576)
    overflow = [False, False]
    try:
        code, out, err, timed_out, overflow, incomplete = capture(
            command, cwd=working, timeout=timeout if timeout is not None else 300, max_bytes=max_bytes)
        status = "PASS" if code == 0 else "FAIL"
        if code != 0:
            reason = f"command exited with status {code}"
        if timed_out or incomplete:
            status = "BLOCKED"
            reason = "command_timed_out" if timed_out else "command_output_pipe_not_closed"
    except FileNotFoundError as exc:
        reason = f"command unavailable: {exc}"
    max_bytes = int(rules.get("runner_max_output_bytes") or 1_048_576)
    patterns = [str(x) for x in rules.get("runner_redact_patterns", [])]
    out, orc, otrunc = _redact_bound(out, patterns=patterns, max_bytes=max_bytes)
    err, erc, etrunc = _redact_bound(err, patterns=patterns, max_bytes=max_bytes)
    _write_log(log_path, out, err)
    duration = round(time.monotonic() - t0, 6); finished = utc_now(); identity_after = source_identity(cfg)
    identity_changed = any([
        identity_before.get("truth_fingerprint", {}).get("sha256") != identity_after.get("truth_fingerprint", {}).get("sha256"),
        identity_before.get("policy_fingerprint", {}).get("sha256") != identity_after.get("policy_fingerprint", {}).get("sha256"),
        identity_before.get("memory_fingerprint", {}).get("sha256") != identity_after.get("memory_fingerprint", {}).get("sha256"),
    ])
    if bool(rules.get("runner_require_identity_stable", True)) and identity_changed:
        status = "BLOCKED"
        reason = "runner_changed_trusted_identity"
    try:
        cwd_value = working.relative_to(cfg.repo).as_posix()
    except ValueError:
        cwd_value = str(working)
    receipt = {
        "schema": "contextcord-runner-receipt-v1",
        "name": name,
        "session_id": session_id,
        "task_id": task_id,
        "command": command,
        "command_display": shlex.join(command),
        "cwd": cwd_value,
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": duration,
        "exit_code": code,
        "status": status,
        "reason": reason or None,
        "source_identity_sha256": identity_before["identity_sha256"],
        "source_identity_after_sha256": identity_after["identity_sha256"],
        "truth_changed_during_command": identity_before["truth_fingerprint"]["sha256"] != identity_after["truth_fingerprint"]["sha256"],
        "trusted_identity_changed_during_command": identity_changed,
        "log_path": log_path.relative_to(cfg.repo).as_posix(),
        "output_control": {"max_bytes_per_stream": max_bytes, "redaction_count": orc + erc, "stdout_truncated": otrunc or overflow[0], "stderr_truncated": etrunc or overflow[1]},
    }
    validate("runner-receipt", receipt)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Evidence is bound to the identity *after* the validation command. Tests may
    # legitimately generate source truth; callers can see truth_changed_during_command.
    test = {"name": name, "status": status, "evidence": log_path.relative_to(cfg.repo).as_posix(), "revision": identity_after["git_commit"], "reason": reason or None, "metadata": {"runner_receipt": meta_path.relative_to(cfg.repo).as_posix(), "truth_changed_during_command": receipt["truth_changed_during_command"]}}
    records, _ = prepare_records(cfg, tests=[test], evidence_paths=[test["evidence"]], identity=identity_after)
    record_prepared(store, session_id=session_id, task_id=task_id, records=records)
    return {"status": status, "runner": receipt, "evidence_record": records[0]}
