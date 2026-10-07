"""Budgeted Explorer/Implementer/Reviewer calibration over a closed Catalog."""

from __future__ import annotations

import ast
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .contracts import validate
from .router import CalibrationBudget, MAX_CALIBRATION_CALLS, MAX_SOL_MAX_RUNS


MAX_JEV_CALLS = 3
MAX_ESCALATIONS_PER_TASK = 1
MAX_WINNER_REPEATS = 1
TASKS = (
    ("explorer", "read-only source investigation", "EXPLORER_PASS"),
    ("implementer", "disposable synthetic fixture edit", "IMPLEMENTER_PASS"),
    ("reviewer", "independent seeded-defect review without edit", "REVIEWER_PASS"),
)


def _eligible(routes: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row) for row in routes
        if bool(row.get("execution_eligible"))
        and str(row.get("capability_state") or "").upper() in {"CONFIRMED", "CONFIGURED_EXPLICIT"}
        and row.get("fallback_observed") is not True
        and row.get("fallback_used") is not True
    ]


def _synthetic_answer_is_42(path: Path) -> bool:
    """Recognize the disposable fixture's literal answer without executing it."""
    try:
        module = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return False

    def without_docstring(body):
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            return body[1:]
        return body

    body = without_docstring(module.body)
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
        return False
    function = body[0]
    args = function.args
    if (function.name != "answer" or function.decorator_list
            or function.returns is not None or getattr(function, "type_params", ())
            or args.posonlyargs or args.args or args.kwonlyargs
            or args.vararg or args.kwarg or args.defaults or args.kw_defaults):
        return False
    statements = without_docstring(function.body)
    if len(statements) != 1 or not isinstance(statements[0], ast.Return):
        return False
    value = statements[0].value
    return isinstance(value, ast.Constant) and type(value.value) is int and value.value == 42


def _run_codex_task(route: Mapping[str, Any], role: str, *, timeout_seconds: float = 150.0) -> dict[str, Any]:
    """Run one bounded task in a disposable fixture; never run against product source."""

    codex = shutil.which("codex")
    if not codex:
        return {"verifier_pass": False, "status": "UNAVAILABLE", "reason": "codex_cli_missing", "latency_ms": 0.0}
    model = str(route.get("requested_model") or route.get("model_id") or "")
    effort = str(route.get("requested_effort") or route.get("reasoning_effort") or "").casefold()
    marker = next(marker for name, _description, marker in TASKS if name == role)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="contextcord-calibration-") as td:
        root = Path(td)
        (root / "fixture").mkdir()
        (root / "fixture" / "target.txt").write_text("CALIBRATION_TARGET=42\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "app.py").write_text("def answer():\n    return 0\n", encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests" / "test_app.py").write_text("from src.app import answer\n\ndef test_answer():\n    assert answer() == 42\n", encoding="utf-8")
        prompt = {
            "explorer": "Read fixture/target.txt only. Do not edit. Return exactly EXPLORER_PASS:42.",
            "implementer": "Edit only src/app.py so answer() returns 42. Do not edit tests. Return exactly IMPLEMENTER_PASS after the edit.",
            "reviewer": "Inspect src/app.py and tests/test_app.py without editing. Identify the seeded defect and return exactly REVIEWER_PASS:answer returns 0.",
        }[role]
        command = [
            codex, "exec", "--ephemeral", "--json", "--skip-git-repo-check",
            "--sandbox", "workspace-write" if role == "implementer" else "read-only",
            "--ask-for-approval", "never", "-C", str(root), "-m", model,
            "-c", f"model_reasoning_effort={effort}", prompt,
        ]
        try:
            completed = subprocess.run(command, cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=max(1.0, float(timeout_seconds)), check=False)
            output = completed.stdout
            marker_pass = marker in output
            if role == "implementer" and completed.returncode == 0:
                marker_pass = marker_pass and _synthetic_answer_is_42(root / "src" / "app.py")
            return {
                "verifier_pass": bool(completed.returncode == 0 and marker_pass),
                "status": "PASS" if completed.returncode == 0 and marker_pass else "FAIL",
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "fallback_observed": None,
            }
        except subprocess.TimeoutExpired:
            return {"verifier_pass": False, "status": "TIMEOUT", "reason": "calibration_task_timeout", "latency_ms": round((time.monotonic() - started) * 1000, 3)}
        except OSError as exc:
            return {"verifier_pass": False, "status": "UNAVAILABLE", "reason": type(exc).__name__, "latency_ms": round((time.monotonic() - started) * 1000, 3)}


def run_adaptive_calibration(
    routes: list[Mapping[str, Any]],
    *,
    executor: Callable[[Mapping[str, Any], str], Mapping[str, Any]] | None = None,
    record_outcome: Callable[[Mapping[str, Any], str, Mapping[str, Any]], Any] | None = None,
    jev_calls_used: int = 0,
    round_id: str = "0.6.2a1-calibration",
) -> dict[str, Any]:
    """Run the fixed three-role calibration with hard caps and one escalation."""

    eligible = _eligible(routes)
    budget = CalibrationBudget()
    tasks: list[dict[str, Any]] = []
    if not eligible:
        value = {
            "schema": "contextcord-adaptive-router-calibration-v1",
            "round_id": round_id,
            "codex_execution_cap": MAX_CALIBRATION_CALLS,
            "jev_call_cap": MAX_JEV_CALLS,
            "sol_max_cap": MAX_SOL_MAX_RUNS,
            "codex_executions_used": 0,
            "jev_calls_used": min(MAX_JEV_CALLS, max(0, int(jev_calls_used))),
            "sol_max_used": 0,
            "tasks": [{"role": role, "status": "NOT_RUN", "reason": "execution_catalog_empty"} for role, _description, _marker in TASKS],
            "early_stop": True,
            "stop_reason": "execution_catalog_empty_host_capability_blocker",
        }
        validate("adaptive-router-calibration", value)
        return value

    execute = executor or (lambda route, role: _run_codex_task(route, role))
    for role, description, _marker in TASKS:
        if budget.calls_used >= MAX_CALIBRATION_CALLS:
            tasks.append({"role": role, "description": description, "status": "NOT_RUN", "reason": "codex_execution_cap_reached"})
            continue
        task_row: dict[str, Any] = {"role": role, "description": description, "attempts": []}
        for index, route in enumerate(eligible):
            if index > 1:  # one escalation per task; no unbounded route sweep.
                break
            allowed, reason = budget.admit(str(route.get("requested_model") or route.get("model_id")), str(route.get("requested_effort") or route.get("reasoning_effort")))
            if not allowed:
                continue
            result = dict(execute(route, role) or {})
            budget_route = {
                **route,
                "model_id": route.get("model_id") or route.get("requested_model"),
                "reasoning_effort": route.get("reasoning_effort") or route.get("requested_effort"),
            }
            budget.record(budget_route, verifier_pass=bool(result.get("verifier_pass")), latency_seconds=(float(result["latency_ms"]) / 1000.0 if isinstance(result.get("latency_ms"), (int, float)) else None), input_tokens=result.get("input_tokens"), output_tokens=result.get("output_tokens"), api_equivalent_usd=result.get("api_equivalent_usd"), observed_subscription_quota_pct=result.get("observed_subscription_quota_pct"), external_estimated_quota_pct=result.get("external_estimated_quota_pct"))
            attempt = {
                "route_id": route.get("route_id"),
                "model_id": route.get("requested_model") or route.get("model_id"),
                "reasoning_effort": route.get("requested_effort") or route.get("reasoning_effort"),
                "capability_state": route.get("capability_state"),
                "identity_evidence": "resolved_telemetry" if str(route.get("capability_state")) == "CONFIRMED" else "configured_explicit",
                "verifier_pass": bool(result.get("verifier_pass")),
                "status": result.get("status", "PASS" if result.get("verifier_pass") else "FAIL"),
                "latency_ms": result.get("latency_ms"),
            }
            task_row["attempts"].append(attempt)
            if record_outcome is not None:
                record_outcome(route, role, {**result, **attempt})
            if attempt["verifier_pass"]:
                task_row.update({"status": "PASS", "winner": attempt["route_id"]})
                break
            task_row["status"] = "FAIL"
            task_row["escalated"] = index == 0 and len(eligible) > 1
        tasks.append(task_row)
    all_pass = bool(tasks) and all(row.get("status") == "PASS" for row in tasks)
    value = {
        "schema": "contextcord-adaptive-router-calibration-v1",
        "round_id": round_id,
        "codex_execution_cap": MAX_CALIBRATION_CALLS,
        "jev_call_cap": MAX_JEV_CALLS,
        "sol_max_cap": MAX_SOL_MAX_RUNS,
        "codex_executions_used": budget.calls_used,
        "jev_calls_used": min(MAX_JEV_CALLS, max(0, int(jev_calls_used))),
        "sol_max_used": budget.sol_max_runs,
        "tasks": tasks,
        "early_stop": all_pass,
        "stop_reason": "near_best_quality_with_cheaper_success" if all_pass else "calibration_exhausted_or_verifier_failure",
        "budget_receipt": budget.receipt(round_id, early_stop=all_pass, stop_reason="near_best_quality_with_cheaper_success" if all_pass else "calibration_exhausted_or_verifier_failure"),
    }
    validate("adaptive-router-calibration", value)
    return value


__all__ = ["MAX_JEV_CALLS", "MAX_ESCALATIONS_PER_TASK", "MAX_WINNER_REPEATS", "run_adaptive_calibration"]
