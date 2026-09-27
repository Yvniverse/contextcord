from __future__ import annotations

import json
import unittest
from pathlib import Path

from contextcord.contracts import validation_errors
from contextcord.jev_provider import JevApiDecisionProvider
from contextcord.router import (
    discover_analysis_routes,
    discover_execution_routes,
    model_route_decision_v3,
)


FIXTURE = Path(__file__).parent / "fixtures" / "codexradar-derived-snapshot-20260926.json"


class _RouteChoiceTransport:
    def __init__(self, choice: str | None = None) -> None:
        self.choice = choice
        self.calls = 0

    def system_one(self, state, questions, *, model):
        self.calls += 1
        choice = self.choice
        if choice is None:
            choice = questions["route_choice"]["options"][-1]
        return {
            "model": model,
            "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
            "answers": {"route_choice": {"value": choice, "confidence": 0.91}},
        }


class RouterV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def _task(self, **overrides):
        task = {
            "router_version": "v3",
            "role": "implementer",
            "complexity": 4,
            "failure_cost": 3,
            "context_pressure": 4,
            "context_profile": "bounded",
            "codexradar_prior": self.snapshot,
            "external_prior_status": "LIVE",
        }
        task.update(overrides)
        return task

    def test_analysis_catalog_preserves_full_fifteen_route_fixture(self) -> None:
        routes = discover_analysis_routes(self._task())
        self.assertEqual(len(routes), 15)
        self.assertEqual({row["execution_eligible"] for row in routes}, {"unknown"})
        self.assertEqual({row["availability_source"] for row in routes}, {"external_analysis_catalog"})
        self.assertNotIn("gpt-5.6", {row["model_id"] for row in routes})

    def test_off_gate_keeps_planner_effective_and_records_quota_boundary(self) -> None:
        decision = model_route_decision_v3(self._task(jev_mode="off"))
        self.assertEqual(decision["schema"], "contextcord-model-route-decision-v3")
        self.assertEqual(decision["decision_source"], "jev_bypassed")
        self.assertIsNone(decision["semantic_decision"])
        self.assertEqual(decision["effective_route"]["route_id"], decision["planner_recommendation"]["route_id"])
        self.assertEqual(decision["catalog"]["analysis_route_count"], 15)
        self.assertEqual(decision["quality_cost_basis"], "subscription_quota_optimization_not_yet_observed")
        self.assertEqual(validation_errors("model-route-decision-v3", decision), [])

    def test_radar_off_and_fixture_on_use_the_same_full_analysis_catalog(self) -> None:
        fixed_catalog = discover_analysis_routes(self._task())
        base = {
            "router_version": "v3",
            "role": "implementer",
            "failure_cost": 3,
            "context_pressure": 3,
            "analysis_routes": fixed_catalog,
            "jev_mode": "off",
        }
        off = model_route_decision_v3(base)
        on = model_route_decision_v3({**base, "codexradar_prior": self.snapshot, "external_prior_status": "LIVE"})
        self.assertEqual(off["catalog"]["analysis_route_count"], 15)
        self.assertEqual(on["catalog"]["analysis_route_count"], 15)
        self.assertEqual(off["shortlist"]["shortlist"][0]["external_task_count"], 0)
        self.assertGreater(on["shortlist"]["shortlist"][0]["external_task_count"], 0)
        self.assertEqual(on["quality_cost_basis"], "subscription_quota_optimization_not_yet_observed")

    def test_jev_valid_choice_is_the_only_semantic_override(self) -> None:
        transport = _RouteChoiceTransport()
        provider = JevApiDecisionProvider(transport=transport)
        decision = model_route_decision_v3(self._task(), jev_provider=provider)
        self.assertEqual(transport.calls, 1)
        self.assertEqual(decision["decision_source"], "jev_api")
        self.assertEqual(decision["provider_calls"], 1)
        self.assertEqual(decision["semantic_decision"]["provider"], "jev_api")
        self.assertIn(decision["effective_route"]["route_id"], decision["shortlist"]["eligible_route_ids"])
        self.assertEqual(decision["provider_usage"]["key_source"], "fake_transport")

    def test_jev_out_of_shortlist_choice_falls_back_to_planner(self) -> None:
        transport = _RouteChoiceTransport(choice="codex:gpt-5.6:not-a-real-route:implementer")
        decision = model_route_decision_v3(self._task(), jev_provider=JevApiDecisionProvider(transport=transport))
        self.assertEqual(decision["decision_source"], "jev_invalid_choice")
        self.assertIsNone(decision["semantic_decision"])
        self.assertEqual(decision["effective_route"]["route_id"], decision["planner_recommendation"]["route_id"])

    def test_missing_jev_provider_is_unavailable_not_a_fake_semantic_pass(self) -> None:
        decision = model_route_decision_v3(self._task())
        self.assertEqual(decision["decision_source"], "jev_unavailable")
        self.assertIsNone(decision["semantic_decision"])
        self.assertEqual(decision["provider_calls"], 0)

    def test_execution_catalog_requires_observed_identity_and_rejects_alias(self) -> None:
        observed = [
            {
                "host_id": "codex",
                "model_id": "gpt-5.6-luna",
                "reasoning_effort": "medium",
                "real_identity_observed": True,
                "available": True,
                "logged_in": True,
            },
            {
                "host_id": "codex",
                "model_id": "gpt-5.6",
                "reasoning_effort": "medium",
                "real_identity_observed": True,
                "available": True,
                "logged_in": True,
            },
        ]
        execution = discover_execution_routes(observed)
        self.assertEqual(len(execution), 1)
        self.assertTrue(execution[0]["execution_eligible"])
        task = self._task(
            mode="EXECUTE",
            execution_routes=observed,
            observed={
                "model_id": "gpt-5.6-luna",
                "reasoning_effort": "medium",
                "real_identity_observed": True,
            },
            jev_mode="off",
        )
        decision = model_route_decision_v3(task, mode="EXECUTE")
        self.assertEqual(decision["catalog"]["execution_route_count"], 1)
        self.assertEqual(len(decision["eligible_routes"]), 1)
        self.assertTrue(decision["execution"]["executed"])


if __name__ == "__main__":
    unittest.main()
