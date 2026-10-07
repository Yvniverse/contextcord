from __future__ import annotations

from typing import Any


def phase_rows(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    rows = workflow.get("phases", [])
    if not isinstance(rows, list):
        raise ValueError("workflow.phases must be an array of tables")
    return [dict(x) for x in rows]


def phase_ids(workflow: dict[str, Any]) -> list[str]:
    return [str(x["id"]) for x in phase_rows(workflow)]


def required_phases_for_scope(workflow: dict[str, Any], scope: str | None) -> list[str]:
    profiles = workflow.get("scope_profiles", {})
    if scope and isinstance(profiles, dict) and isinstance(profiles.get(scope), dict):
        return [str(x) for x in profiles[scope].get("required_phases", [])]
    return phase_ids(workflow)


def validate_workflow(workflow: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = phase_rows(workflow)
    ids = [str(x.get("id", "")) for x in rows]
    if not ids:
        errors.append("workflow_has_no_phases")
        return errors
    if any(not x for x in ids):
        errors.append("workflow_phase_missing_id")
    if len(set(ids)) != len(ids):
        errors.append("workflow_duplicate_phase_id")
    known = set(ids)
    for row in rows:
        for dep in row.get("requires", []):
            if str(dep) not in known:
                errors.append(f"unknown_phase_dependency:{row.get('id')}:{dep}")
    for operation, gate in workflow.get("operation_gates", {}).items():
        for phase in gate.get("allowed_current_phases", []):
            if str(phase) not in known:
                errors.append(f"unknown_gate_phase:{operation}:{phase}")
        for phase in gate.get("requires_completed", []):
            if str(phase) not in known:
                errors.append(f"unknown_gate_requirement:{operation}:{phase}")
    for phase in workflow.get("phase_contracts", {}):
        if str(phase) not in known:
            errors.append(f"unknown_phase_contract:{phase}")
    by_id = {str(row.get("id")): row for row in rows}
    for scope, profile in workflow.get("scope_profiles", {}).items():
        required = [str(x) for x in profile.get("required_phases", [])] if isinstance(profile, dict) else []
        if not required:
            errors.append(f"scope_profile_has_no_required_phases:{scope}")
            continue
        unknown = [x for x in required if x not in known]
        for phase in unknown:
            errors.append(f"unknown_scope_profile_phase:{scope}:{phase}")
        required_set = set(required)
        for phase in required:
            row = by_id.get(phase)
            if not row:
                continue
            missing_deps = [str(dep) for dep in row.get("requires", []) if str(dep) not in required_set]
            for dep in missing_deps:
                errors.append(f"scope_profile_missing_dependency:{scope}:{phase}:{dep}")
    return errors


def ready_phases(workflow: dict[str, Any], completed: list[str]) -> list[str]:
    done = set(completed)
    ready = []
    for row in phase_rows(workflow):
        pid = str(row["id"])
        if pid in done:
            continue
        deps = {str(x) for x in row.get("requires", [])}
        if deps.issubset(done):
            ready.append(pid)
    return ready


def initial_task(task_id: str, scope: str, workflow: dict[str, Any]) -> dict[str, Any]:
    ready = ready_phases(workflow, [])
    return {
        "task_id": task_id,
        "scope": scope,
        "status": "ACTIVE",
        "current_phase": ready[0] if ready else None,
        "completed": [],
        "blockers": [],
        "next_action": "complete ContextCord preflight",
    }


def advance(task: dict[str, Any], workflow: dict[str, Any], phase: str, next_action: str) -> dict[str, Any]:
    ready = ready_phases(workflow, task.get("completed", []))
    if phase != task.get("current_phase"):
        raise ValueError(f"phase_order_violation expected={task.get('current_phase')} got={phase}")
    if phase not in ready:
        raise ValueError(f"phase_not_ready:{phase}")
    completed = list(task.get("completed", []))
    completed.append(phase)
    task = dict(task)
    task["completed"] = completed
    task["blockers"] = []
    next_ready = ready_phases(workflow, completed)
    task["current_phase"] = next_ready[0] if next_ready else None
    task["next_action"] = next_action
    if task["current_phase"] is None:
        task["status"] = "READY_TO_FINISH"
    return task
