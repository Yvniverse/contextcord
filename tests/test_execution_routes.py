from __future__ import annotations

import json
import unittest
from pathlib import Path

from contextcord.contracts import validation_errors
from contextcord.execution_routes import capability_from_probe, discover_codex_execution_routes


FIXTURE = Path(__file__).parent / "fixtures" / "route_observations.json"


class ExecutionRouteTests(unittest.TestCase):
    def test_four_capability_states_are_distinct(self) -> None:
        confirmed = capability_from_probe("gpt-5.6-luna", "medium", {"host_acceptance": True, "resolved_model_id": "gpt-5.6-luna", "resolved_reasoning_effort": "medium"})
        configured = capability_from_probe("gpt-5.6-luna", "medium", {"host_acceptance": True})
        unknown = capability_from_probe("gpt-5.6-luna", "medium", None)
        unavailable = capability_from_probe("gpt-5.6-luna", "medium", {"returncode": 1, "host_acceptance": False})
        self.assertEqual(confirmed["capability_state"], "CONFIRMED")
        self.assertTrue(confirmed["execution_eligible"])
        self.assertEqual(configured["capability_state"], "CONFIGURED_EXPLICIT")
        self.assertTrue(configured["execution_eligible"])
        self.assertEqual(unknown["capability_state"], "UNKNOWN")
        self.assertFalse(unknown["execution_eligible"])
        self.assertEqual(unavailable["capability_state"], "UNAVAILABLE")
        self.assertFalse(unavailable["execution_eligible"])
        self.assertEqual(validation_errors("execution-route-capability", confirmed), [])

    def test_discovery_probes_at_most_five_and_unknown_never_executes(self) -> None:
        snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        seen = []

        def runner(route):
            seen.append(route["model_id"] + ":" + route["reasoning_effort"])
            return {"host_acceptance": True}

        value = discover_codex_execution_routes(
            {"role": "implementer", "failure_cost": 3, "codexradar_prior": snapshot},
            probe=True, runner=runner, max_probes=5,
        )
        self.assertLessEqual(len(seen), 5)
        self.assertEqual(value["probe_count"], len(seen))
        self.assertEqual(value["capability_state_counts"]["CONFIGURED_EXPLICIT"], len(seen))
        self.assertEqual(value["execution_route_count"], len(seen))

        unknown = discover_codex_execution_routes(
            {"role": "implementer", "failure_cost": 3, "codexradar_prior": snapshot},
            probe=False, max_probes=5,
        )
        self.assertEqual(unknown["execution_route_count"], 0)
        self.assertGreater(unknown["capability_state_counts"]["UNKNOWN"], 0)

    def test_fallback_and_host_only_identity_do_not_enter_execution_catalog(self) -> None:
        snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        value = discover_codex_execution_routes(
            {"role": "implementer", "failure_cost": 3, "codexradar_prior": snapshot},
            probe=True,
            runner=lambda _route: {"host_acceptance": True, "fallback_observed": True},
        )
        self.assertEqual(value["execution_route_count"], 0)


if __name__ == "__main__":
    unittest.main()
