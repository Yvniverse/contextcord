"""Bounded Codex execution-route capability discovery.

The analysis Catalog is advisory.  This module records only the small set of
explicit probes requested by the calibration contract and never turns a
Radar/official cell into execution authority.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .contracts import validate
from .router import EFFORTS, EXPLICIT_MODELS, build_shortlist, discover_analysis_routes, discover_execution_routes


CAPABILITY_STATES = ("CONFIRMED", "CONFIGURED_EXPLICIT", "UNKNOWN", "UNAVAILABLE")
IDENTITY_EVIDENCE = ("resolved_telemetry", "configured_explicit", "none")
MAX_PROBES = 5


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return value is True or str(value).casefold() in {"1", "true", "yes", "pass", "available", "accepted"}


def _json_events(output: str) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for line in str(output or "").splitlines():
        try:
            value = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, Mapping):
            rows.append(value)
    return rows


def _resolved_identity(result: Mapping[str, Any]) -> tuple[str | None, str | None]:
    model = result.get("resolved_model_id") or result.get("resolved_model") or result.get("effective_model")
    effort = result.get("resolved_reasoning_effort") or result.get("resolved_effort") or result.get("effective_effort")
    for event in _json_events(str(result.get("output") or "")):
        model = model or event.get("resolved_model_id") or event.get("resolved_model") or event.get("effective_model")
        effort = effort or event.get("resolved_reasoning_effort") or event.get("resolved_effort") or event.get("effective_effort")
        nested = event.get("model_identity")
        if isinstance(nested, Mapping):
            model = model or nested.get("model_id")
            effort = effort or nested.get("reasoning_effort")
    return (str(model) if model else None, str(effort).casefold() if effort else None)


def capability_from_probe(
    requested_model: str,
    requested_effort: str,
    result: Mapping[str, Any] | None,
    *,
    host_id: str = "codex",
    probe_task: str = "read-only explicit route capability probe",
) -> dict[str, Any]:
    """Normalize host evidence into the locked four-state capability contract."""

    result = dict(result or {})
    requested_model = str(requested_model).casefold()
    requested_effort = str(requested_effort).casefold()
    returncode = result.get("returncode")
    accepted = result.get("host_acceptance")
    if accepted is None and returncode is not None:
        accepted = int(returncode) == 0
    available = _bool(result.get("available"), default=accepted is not False)
    logged_in = _bool(result.get("logged_in"), default=accepted is not False)
    permissions_ok = _bool(result.get("permissions_ok"), default=accepted is not False)
    fallback = result.get("fallback_observed")
    if fallback is None:
        fallback = True if "fallback" in str(result.get("output") or "").casefold() else False
    resolved_model, resolved_effort = _resolved_identity(result)
    identity_evidence = "none"
    state = "UNKNOWN"
    reason = result.get("reason")
    if accepted is False or not available or not logged_in:
        state = "UNAVAILABLE"
        reason = reason or "host_rejected_or_unavailable"
    elif accepted is True:
        if resolved_model or resolved_effort:
            if resolved_model != requested_model or resolved_effort != requested_effort:
                state = "UNAVAILABLE"
                reason = reason or "resolved_identity_mismatch"
            else:
                state = "CONFIRMED"
                identity_evidence = "resolved_telemetry"
        else:
            state = "CONFIGURED_EXPLICIT"
            identity_evidence = "configured_explicit"
            reason = reason or "explicit_request_accepted_without_resolved_telemetry"
    execution_eligible = bool(
        state in {"CONFIRMED", "CONFIGURED_EXPLICIT"}
        and permissions_ok
        and fallback is not True
        and requested_model in EXPLICIT_MODELS
        and requested_effort in EFFORTS
    )
    value = {
        "schema": "contextcord-execution-route-capability-v1",
        "host_id": str(host_id),
        "requested_model": requested_model,
        "requested_effort": requested_effort,
        "capability_state": state,
        "identity_evidence": identity_evidence,
        "execution_eligible": execution_eligible,
        "fallback_observed": bool(fallback) if fallback is not None else None,
        "probe_verifier_pass": result.get("verifier_pass"),
        "latency_ms": result.get("latency_ms"),
        "usage": result.get("usage") if isinstance(result.get("usage"), Mapping) else None,
        "host_acceptance": accepted,
        "available": available,
        "logged_in": logged_in,
        "permissions_ok": permissions_ok,
        "resolved_model_id": resolved_model,
        "resolved_reasoning_effort": resolved_effort,
        "probe_task": probe_task,
        "reason": reason,
    }
    validate("execution-route-capability", value)
    return value


def run_codex_probe(
    route: Mapping[str, Any],
    *,
    repo: str | Path,
    timeout_seconds: float = 90.0,
    executable: str | None = None,
) -> dict[str, Any]:
    """Run one tiny read-only explicit Codex probe without retaining raw output."""

    model = str(route.get("model_id") or route.get("requested_model") or "")
    effort = str(route.get("reasoning_effort") or route.get("requested_effort") or "").casefold()
    codex = executable or shutil.which("codex")
    if not codex:
        return {"host_acceptance": False, "available": False, "logged_in": False, "reason": "codex_cli_missing"}
    started = time.monotonic()
    command = [
        codex, "exec", "--ephemeral", "--json", "--skip-git-repo-check",
        "--sandbox", "read-only", "--ask-for-approval", "never", "-C", str(Path(repo).resolve()),
        "-m", model, "-c", f"model_reasoning_effort={effort}",
        "Return exactly PROBE_PASS after reading no files and making no edits.",
    ]
    try:
        completed = subprocess.run(
            command, cwd=str(Path(repo).resolve()), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=max(1.0, float(timeout_seconds)), check=False,
        )
        events = _json_events(completed.stdout)
        resolved_model = None
        resolved_effort = None
        usage = None
        for event in events:
            resolved_model = resolved_model or event.get("resolved_model_id") or event.get("resolved_model")
            resolved_effort = resolved_effort or event.get("resolved_reasoning_effort") or event.get("resolved_effort")
            if isinstance(event.get("usage"), Mapping):
                usage = dict(event["usage"])
        return {
            "returncode": completed.returncode,
            "host_acceptance": completed.returncode == 0,
            "available": True,
            "logged_in": completed.returncode == 0 or "auth" not in completed.stderr.casefold(),
            "permissions_ok": completed.returncode == 0,
            "resolved_model_id": resolved_model,
            "resolved_reasoning_effort": resolved_effort,
            "fallback_observed": None,
            "verifier_pass": completed.returncode == 0 and "PROBE_PASS" in completed.stdout,
            "usage": usage,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "reason": None if completed.returncode == 0 else "codex_probe_nonzero_exit",
        }
    except subprocess.TimeoutExpired:
        return {"host_acceptance": False, "available": True, "logged_in": True, "permissions_ok": False, "reason": "codex_probe_timeout", "latency_ms": round((time.monotonic() - started) * 1000, 3)}
    except OSError as exc:
        return {"host_acceptance": False, "available": False, "logged_in": False, "permissions_ok": False, "reason": type(exc).__name__, "latency_ms": round((time.monotonic() - started) * 1000, 3)}


def _probe_candidates(task: Mapping[str, Any], analysis: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    role = str(task.get("role") or task.get("requested_role") or "implementer").casefold()
    risk = max(1, min(5, int(task.get("failure_cost") or task.get("risk") or 3)))
    prior_rows = task.get("codexradar_prior", {})
    external = prior_rows.get("routes", []) if isinstance(prior_rows, Mapping) else []
    external_map = {(str(row.get("model_id")), str(row.get("reasoning_effort"))): row for row in external if isinstance(row, Mapping)}
    local_rows = task.get("local_routes", [])
    local_map = {}
    if isinstance(local_rows, Mapping):
        local_map = local_rows
    elif isinstance(local_rows, list):
        for row in local_rows:
            if isinstance(row, Mapping) and row.get("model_id") and row.get("reasoning_effort") and row.get("role"):
                local_map[(str(row["model_id"]), str(row["reasoning_effort"]), str(row["role"]))] = row
    shortlist = build_shortlist(
        role=role, risk=risk, available_routes=list(analysis), external_routes=external_map,
        local_routes=local_map, allow_sol_max_calibration=bool(task.get("allow_sol_max_calibration")),
    ).get("shortlist", [])
    by_key = {(str(row.get("model_id")), str(row.get("reasoning_effort"))): row for row in analysis}
    preferred = [("gpt-5.6-luna", "medium"), ("gpt-5.6-luna", "max"), ("gpt-5.6-terra", "high"), ("gpt-5.6-sol", "medium"), ("gpt-5.6-sol", "xhigh")]
    if risk >= 4:
        preferred.append(("gpt-5.6-sol", "max"))
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for model, effort in preferred:
        key = (model, effort)
        if key in by_key and key not in seen:
            selected.append(dict(by_key[key])); seen.add(key)
        if len(selected) >= MAX_PROBES:
            break
    for row in shortlist:
        key = (str(row.get("model_id")), str(row.get("reasoning_effort")))
        if key not in seen and key in by_key:
            selected.append(dict(by_key[key])); seen.add(key)
        if len(selected) >= MAX_PROBES:
            break
    return selected[:MAX_PROBES]


def discover_codex_execution_routes(
    task: Mapping[str, Any] | None = None,
    *,
    snapshot: Mapping[str, Any] | None = None,
    probe: bool = False,
    repo: str | Path | None = None,
    runner: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    max_probes: int = MAX_PROBES,
) -> dict[str, Any]:
    """Discover at most five explicit routes and return the execution Catalog."""

    task = dict(task or {})
    analysis = discover_analysis_routes(task, snapshot=snapshot)
    candidates = _probe_candidates(task, analysis)[: max(0, min(int(max_probes), MAX_PROBES))]
    capabilities: list[dict[str, Any]] = []
    for candidate in candidates:
        if probe:
            result = runner(candidate) if runner is not None else run_codex_probe(candidate, repo=repo or Path.cwd())
            capabilities.append(capability_from_probe(candidate["model_id"], candidate["reasoning_effort"], result, probe_task="bounded read-only Codex capability probe"))
        else:
            capabilities.append(capability_from_probe(candidate["model_id"], candidate["reasoning_effort"], None, probe_task="analysis-only; execution not probed"))
    execution_inputs = []
    for row in capabilities:
        execution_inputs.append({
            "host_id": row["host_id"], "model_id": row["requested_model"], "reasoning_effort": row["requested_effort"],
            "real_identity_observed": row["capability_state"] == "CONFIRMED",
            "capability_state": row["capability_state"], "identity_evidence": row["identity_evidence"],
            "available": row.get("available") is True, "logged_in": row.get("logged_in") is True,
            "permissions_ok": row.get("permissions_ok") is True, "host_acceptance": row.get("host_acceptance"),
            "fallback": row.get("fallback_observed") is True, "fallback_used": row.get("fallback_observed") is True,
            "execution_eligible": row["execution_eligible"], "route_id": f"codex:{row['requested_model']}:{row['requested_effort']}:{task.get('role') or 'implementer'}",
        })
    execution = discover_execution_routes(execution_inputs)
    counts = {state: sum(1 for row in capabilities if row["capability_state"] == state) for state in CAPABILITY_STATES}
    value = {
        "schema": "contextcord-execution-route-discovery-v1",
        "probe_requested": bool(probe),
        "probe_cap": MAX_PROBES,
        "probe_count": len(capabilities),
        "analysis_route_count": len(analysis),
        "execution_route_count": len(execution),
        "capability_state_counts": counts,
        "routes": capabilities,
        "execution_routes": execution,
        "truth_boundary": "Only CONFIRMED or CONFIGURED_EXPLICIT routes without fallback enter execution Catalog; UNKNOWN and Radar-only rows never execute.",
    }
    return value


__all__ = [
    "CAPABILITY_STATES", "IDENTITY_EVIDENCE", "MAX_PROBES", "capability_from_probe",
    "discover_codex_execution_routes", "run_codex_probe",
]
