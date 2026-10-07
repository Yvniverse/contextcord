from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import HarnessConfig
from .policy import Decision, authorize
from .store import StateStore


_PATH_KEYS = (
    "file_path", "filePath", "path", "target", "target_path", "targetPath",
    "destination", "dest", "new_path", "newPath", "old_path", "oldPath",
)


@dataclass(frozen=True)
class HostAction:
    operation: str | None
    target: str | None
    confidence: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "target": self.target,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_path(args: dict[str, Any]) -> str | None:
    for key in _PATH_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _command_action(command: str) -> HostAction:
    text = command.strip()
    low = text.lower()
    if not text:
        return HostAction(None, None, "none", "empty_shell_command")

    # Match force-push before generic push; otherwise the generic rule shadows it.
    if re.search(r"(^|[;&|]\s*)git\s+push\b[^\n]*(--force|-f\b)", low):
        return HostAction("force-push", None, "high", "git_force_push")
    if re.search(r"(^|[;&|]\s*)git\s+push\b", low):
        return HostAction("push", None, "high", "git_push")
    if re.search(r"(^|[;&|]\s*)git\s+tag\b", low):
        return HostAction("release", None, "high", "git_tag")
    deploy_patterns = [
        r"\bkubectl\s+(apply|replace|rollout)\b",
        r"\bhelm\s+(install|upgrade)\b",
        r"\bterraform\s+apply\b",
        r"\bdocker\s+(stack\s+deploy|compose\s+up)\b",
        r"\bvercel\s+(deploy|--prod)\b",
        r"\bnetlify\s+deploy\b",
    ]
    if any(re.search(p, low) for p in deploy_patterns):
        return HostAction("deploy", None, "high", "deployment_command")

    # Conservative file-mutation classification. We only return a target when a
    # simple single-command form can be parsed; ambiguous shell is left to the
    # host sandbox and CI rather than guessed.
    try:
        toks = shlex.split(text, posix=True)
    except ValueError:
        toks = []
    if toks:
        cmd = Path(toks[0]).name.lower()
        if cmd in {"rm", "unlink", "rmdir"}:
            candidates = [x for x in toks[1:] if not x.startswith("-")]
            if len(candidates) == 1:
                return HostAction("delete", candidates[0], "high", f"shell_{cmd}")
        if cmd in {"mv", "move", "ren", "rename"}:
            candidates = [x for x in toks[1:] if not x.startswith("-")]
            if len(candidates) >= 2:
                return HostAction("move", candidates[-1], "high", f"shell_{cmd}")
        if cmd in {"cp", "copy", "install"}:
            candidates = [x for x in toks[1:] if not x.startswith("-")]
            if len(candidates) >= 2:
                return HostAction("write", candidates[-1], "medium", f"shell_{cmd}")
    return HostAction(None, None, "none", "unclassified_tool_call")


def classify_tool_call(tool_name: str, tool_input: Any) -> HostAction:
    name = (tool_name or "").strip().lower()
    args = _mapping(tool_input)
    target = _first_path(args)

    if any(x in name for x in ("write", "edit", "patch", "create_file", "write_file")):
        return HostAction("write", target, "high" if target else "medium", "file_write_tool")
    if any(x in name for x in ("delete", "remove_file", "unlink")):
        return HostAction("delete", target, "high" if target else "medium", "file_delete_tool")
    if any(x in name for x in ("move", "rename")):
        return HostAction("move", target, "high" if target else "medium", "file_move_tool")
    if any(x in name for x in ("read", "cat", "open_file", "read_file")):
        return HostAction("read", target, "high" if target else "medium", "file_read_tool")
    if any(x in name for x in ("bash", "shell", "terminal", "command", "exec")):
        command = args.get("command") or args.get("cmd") or args.get("script")
        if isinstance(command, str):
            return _command_action(command)
    return HostAction(None, target, "none", "unclassified_tool_call")


def _active_task_for_scope(store: StateStore, scope: str | None, task_id: str | None) -> dict[str, Any] | None:
    if task_id:
        return store.get_task(task_id)
    tasks = store.active_tasks()
    if scope:
        scoped = [x for x in tasks if x.get("scope") == scope]
        if len(scoped) == 1:
            return scoped[0]
    if len(tasks) == 1:
        return tasks[0]
    return None


def authorize_host_action(
    cfg: HarnessConfig,
    store: StateStore,
    *,
    action: HostAction,
    scope: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    if action.operation is None:
        return {
            "allowed": True,
            "reason": "unclassified_host_action_deferred_to_host_policy",
            "action": action.as_dict(),
            "enforced": False,
        }
    task = _active_task_for_scope(store, scope, task_id)
    effective_scope = scope or (str(task.get("scope")) if task else None)
    if not effective_scope:
        return {
            "allowed": False,
            "reason": "no_unambiguous_contextcord_scope_for_mutating_action",
            "action": action.as_dict(),
            "enforced": True,
        }
    decision: Decision = authorize(
        cfg.repo, cfg.authority, scope=effective_scope, operation=action.operation, target=action.target
    )
    result = decision.as_dict()
    result.update({"action": action.as_dict(), "enforced": True})
    if result["allowed"] and action.operation in {"write", "delete", "move"} and action.target:
        leases_cfg = cfg.authority.get("leases", {})
        if bool(leases_cfg.get("enforce_conflicts", True)):
            conflict = store.lease_conflict(target=action.target, session_id=session_id)
            if conflict is not None:
                result.update({"allowed": False, "reason": "writer_lease_conflict", "conflicting_lease": conflict})
        if result["allowed"] and bool(leases_cfg.get("require_for_mutation", False)):
            owned = [x for x in store.active_leases() if session_id and x.get("session_id") == session_id]
            from .store import lease_keys_overlap
            if not any(lease_keys_overlap(str(action.target), str(x.get("lease_key"))) for x in owned):
                result.update({"allowed": False, "reason": "writer_lease_required_for_mutation"})
    if result["allowed"] and action.operation in cfg.workflow.get("operation_gates", {}):
        gate = cfg.workflow["operation_gates"][action.operation]
        if task is None:
            result.update({"allowed": False, "reason": "workflow_gate_requires_task"})
        else:
            required = {str(x) for x in gate.get("requires_completed", [])}
            completed = {str(x) for x in task.get("completed", [])}
            allowed_phases = {str(x) for x in gate.get("allowed_current_phases", [])}
            if not required.issubset(completed):
                result.update({
                    "allowed": False,
                    "reason": "workflow_gate_requirements_not_completed",
                    "missing_completed": sorted(required - completed),
                })
            elif allowed_phases and task.get("current_phase") not in allowed_phases:
                result.update({
                    "allowed": False,
                    "reason": "workflow_gate_wrong_current_phase",
                    "current_phase": task.get("current_phase"),
                    "allowed_current_phases": sorted(allowed_phases),
                })
    return result


def event_payload_from_stdin(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def qoder_pretool_result(decision: dict[str, Any]) -> tuple[int, dict[str, Any], str]:
    if decision.get("allowed"):
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }, ""
    reason = str(decision.get("reason", "denied_by_contextcord"))
    return 0, {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"ContextCord: {reason}",
        }
    }, ""


def run_json_command(argv: list[str], *, cwd: Path, stdin_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        input=(json.dumps(stdin_payload) if stdin_payload is not None else None),
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {"stdout": proc.stdout.strip()}
    data["returncode"] = proc.returncode
    if proc.stderr.strip():
        data["stderr"] = proc.stderr.strip()
    return data
