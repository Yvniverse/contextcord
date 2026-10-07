from __future__ import annotations

from typing import Any

from .evidence import verify_evidence_records
from .config import HarnessConfig
from .fingerprint import policy_fingerprint
from .identity import source_identity
from .runtime import run_probes
from .store import StateStore
from .workflow import phase_ids, required_phases_for_scope


def _latest_evidence_by_name(store: StateStore, task_id: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in store.evidence_for_task(task_id):
        latest[str(row.get("name"))] = row
    return latest


def phase_contract_verdict(cfg: HarnessConfig, store: StateStore, *, task: dict[str, Any], phase: str, session_id: str | None = None) -> dict[str, Any]:
    contract = dict(cfg.workflow.get("phase_contracts", {}).get(phase, {}))
    failures: list[str] = []
    evidence = _latest_evidence_by_name(store, str(task["task_id"]))
    if session_id:
        session = store.session(session_id)
        if not session or session['task_id'] != task['task_id'] or session['status'] != 'OPEN':
            failures.append('phase_requires_open_matching_session')
    if evidence:
        failures.extend(verify_evidence_records(cfg, list(evidence.values())))
    required_evidence = [str(x) for x in contract.get("required_evidence", [])]
    for name in required_evidence:
        row = evidence.get(name)
        if row is None:
            failures.append(f"phase_required_evidence_missing:{phase}:{name}")
        elif row.get("status") != "PASS":
            failures.append(f"phase_required_evidence_not_pass:{phase}:{name}:{row.get('status')}")
    minimum = int(contract.get("minimum_pass_evidence", 0) or 0)
    passed_count = sum(1 for row in evidence.values() if row.get("status") == "PASS")
    if passed_count < minimum:
        failures.append(f"phase_minimum_pass_evidence_not_met:{phase}:{passed_count}<{minimum}")
    runtime_value: dict[str, Any] | None = None
    required_runtime = [str(x) for x in contract.get("required_runtime", [])]
    if required_runtime:
        runtime_value = run_probes(cfg.repo, cfg.runtime)
        by_id = {str(x.get("id")): x for x in runtime_value.get("probes", [])}
        for probe_id in required_runtime:
            row = by_id.get(probe_id)
            if row is None:
                failures.append(f"phase_runtime_probe_missing:{phase}:{probe_id}")
            elif row.get("status") != "PASS":
                failures.append(f"phase_runtime_probe_not_pass:{phase}:{probe_id}:{row.get('status')}")
    if bool(contract.get("require_policy_stable", False)) and not session_id:
        failures.append(f"phase_policy_requires_session:{phase}")
    if bool(contract.get("require_policy_stable", False)) and session_id:
        rec = store.session(session_id)
        current = policy_fingerprint(cfg.repo, cfg.policy_entrypoints)
        if not rec or not rec.get("start_policy_fingerprint") or rec.get("start_policy_fingerprint") != current.get("sha256"):
            failures.append(f"phase_policy_drift:{phase}")
    if bool(contract.get("require_clean_truth", False)):
        ident = source_identity(cfg)
        if ident.get("dirty_truth"):
            failures.append(f"phase_dirty_truth:{phase}")
    profile = contract.get("require_qualification_profile")
    qualification_value = None
    if profile:
        from .qualification import verify
        qualification_value = verify(cfg, commitish="HEAD", profile=str(profile))
        if qualification_value.get("status") != "PASS":
            failures.append(f"phase_qualification_not_pass:{phase}:{profile}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "phase": phase,
        "contract": contract,
        "failures": failures,
        "runtime": runtime_value,
        "qualification": qualification_value,
    }


def workflow_completion_verdict(cfg: HarnessConfig, store: StateStore, *, task_id: str, session_id: str | None = None, recheck_contracts: bool = True) -> dict[str, Any]:
    task = store.get_task(task_id)
    failures: list[str] = []
    phase_results: list[dict[str, Any]] = []
    if task is None:
        return {"status": "FAIL", "task_id": task_id, "failures": ["workflow_task_missing"], "phase_results": []}
    all_phases = phase_ids(cfg.workflow)
    expected = required_phases_for_scope(cfg.workflow, str(task.get("scope") or ""))
    completed = [str(x) for x in task.get("completed", [])]
    missing = [x for x in expected if x not in completed]
    if missing:
        failures.append("workflow_phases_incomplete:" + ",".join(missing))
    full_graph_required = expected == all_phases
    if full_graph_required and task.get("current_phase") is not None:
        failures.append(f"workflow_current_phase_not_none:{task.get('current_phase')}")
    if task.get("blockers"):
        failures.append("workflow_has_blockers")
    if full_graph_required and task.get("status") not in {"READY_TO_FINISH", "COMPLETE"}:
        failures.append(f"workflow_task_not_ready:{task.get('status')}")
    if recheck_contracts:
        for phase in completed:
            if phase in cfg.workflow.get("phase_contracts", {}):
                result = phase_contract_verdict(cfg, store, task=task, phase=phase, session_id=session_id)
                phase_results.append(result)
                failures.extend(result.get("failures", []))
    return {"status": "PASS" if not failures else "FAIL", "task_id": task_id, "task": task, "required_phases": expected, "failures": failures, "phase_results": phase_results}
