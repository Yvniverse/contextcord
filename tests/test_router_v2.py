from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from contextcord.cli import cmd_router
from contextcord.router import (
    CalibrationBudget,
    build_eligible_set,
    model_route_decision,
    next_escalation_route,
    route_id,
    shadow_route,
)


class RouterV2Tests(unittest.TestCase):
    def test_route_identity_includes_model_effort_and_role(self) -> None:
        self.assertEqual(
            route_id("codex", "gpt-5.6-luna", "medium", "explorer"),
            "codex:gpt-5.6-luna:medium:explorer",
        )

    def test_codex_closed_set_rejects_aliases_fallbacks_and_non_gpt56(self) -> None:
        task = {
            "codex_only": True,
            "data_boundary": "local",
            "hosts": [{
                "id": "codex",
                "available": True,
                "logged_in": True,
                "models": [
                    {"id": "gpt-5.6", "tier": "reasoning"},
                    {"id": "gpt-6", "tier": "reasoning"},
                    {"id": "gpt-5.6-luna", "fallback": True},
                    {"id": "gpt-5.6-luna"},
                ],
            }],
        }
        eligible = build_eligible_set(task)
        self.assertEqual(
            eligible["eligible_ids"],
            [f"codex:gpt-5.6-luna:{role}" for role in ("explorer", "implementer", "reviewer")],
        )
        receipt = shadow_route(task)
        self.assertFalse(receipt["executed"])
        self.assertEqual(receipt["decision"]["kind"], "Choice")

    def test_model_effort_decision_is_typed_and_closed(self) -> None:
        decision = model_route_decision({
            "role": "explorer",
            "complexity": 2,
            "failure_cost": 2,
            "context_pressure": 3,
            "context_profile": "bounded",
            "available_routes": [
                {"host_id": "codex", "model_id": "gpt-5.6-luna", "reasoning_effort": "medium", "available": True},
                {"host_id": "codex", "model_id": "gpt-5.6-terra", "reasoning_effort": "high", "available": True},
                {"host_id": "codex", "model_id": "gpt-5.6-sol", "reasoning_effort": "max", "available": True},
                {"host_id": "codex", "model_id": "gpt-5.5", "reasoning_effort": "max", "available": True},
            ],
            "external_routes": [
                {"model_id": "gpt-5.6-luna", "reasoning_effort": "medium", "task_equal_pass_rate": 0.82, "task_count": 20, "median_estimated_quota_pct": 1.0},
                {"model_id": "gpt-5.6-terra", "reasoning_effort": "high", "task_equal_pass_rate": 0.90, "task_count": 20, "median_estimated_quota_pct": 3.0},
            ],
        })
        self.assertEqual(decision["schema"], "contextcord-model-route-decision-v2")
        self.assertEqual(decision["jev_decision"]["kind"], "Choice")
        route = decision["jev_decision"]["route_id"]
        self.assertIn(route, {row["route_id"] for row in decision["eligible_routes"]})
        self.assertEqual(route.count(":"), 3)
        self.assertEqual({row["name"] for row in decision["typed_fields"]}, {
            "task_complexity", "failure_cost", "context_pressure",
            "should_parallelize", "needs_independent_review", "context_profile",
        })
        self.assertFalse(decision["execution"]["executed"])

    def test_execution_allows_only_one_escalation(self) -> None:
        decision = model_route_decision({
            "role": "implementer",
            "available_routes": [
                {"host_id": "codex", "model_id": "gpt-5.6-luna", "reasoning_effort": "medium"},
                {"host_id": "codex", "model_id": "gpt-5.6-terra", "reasoning_effort": "high"},
            ],
        })
        self.assertIsNotNone(next_escalation_route(decision, verifier_pass=False, attempts_used=1))
        self.assertIsNone(next_escalation_route(decision, verifier_pass=False, attempts_used=2))
        self.assertIsNone(next_escalation_route(decision, verifier_pass=True, attempts_used=1))

    def test_existing_cli_shadow_entrypoint_dispatches_model_effort_routes(self) -> None:
        state = {
            "router_version": "v2",
            "role": "explorer",
            "available_routes": [{
                "host_id": "codex",
                "model_id": "gpt-5.6-luna",
                "reasoning_effort": "medium",
                "available": True,
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "router-input.json"
            input_path.write_text(json.dumps(state), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = cmd_router(argparse.Namespace(
                    router_command="shadow",
                    input=str(input_path),
                    out=None,
                    repo=None,
                ))
        self.assertEqual(rc, 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value["schema"], "contextcord-model-route-decision-v2")
        self.assertEqual(value["jev_decision"]["reasoning_effort"], "medium")

    def test_calibration_budget_caps_calls_and_sol_max(self) -> None:
        budget = CalibrationBudget()
        for index in range(5):
            budget.record({"model_id": "gpt-5.6-luna", "reasoning_effort": "medium", "role": "explorer"}, verifier_pass=True)
        budget.record({"model_id": "gpt-5.6-sol", "reasoning_effort": "max", "role": "reviewer"}, verifier_pass=False)
        allowed, reason = budget.admit("gpt-5.6-sol", "max")
        self.assertFalse(allowed)
        self.assertEqual(reason, "live_call_cap_reached")
        receipt = budget.receipt("round-1", early_stop=True, stop_reason="near_best_cheaper_route")
        self.assertEqual(receipt["calls_used"], 6)
        self.assertEqual(receipt["sol_max_runs"], 1)
        self.assertEqual(receipt["live_call_cap"], 6)

        sol_budget = CalibrationBudget()
        sol_budget.record({"model_id": "gpt-5.6-sol", "reasoning_effort": "max", "role": "reviewer"})
        allowed, reason = sol_budget.admit("gpt-5.6-sol", "max")
        self.assertFalse(allowed)
        self.assertEqual(reason, "sol_max_cap_reached")


if __name__ == "__main__":
    unittest.main()
