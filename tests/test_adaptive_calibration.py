from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from contextcord.calibration import run_adaptive_calibration
from contextcord.profiles import write_profile
from contextcord.store import StateStore


class AdaptiveCalibrationTests(unittest.TestCase):
    def routes(self):
        return [
            {
                "route_id": "codex:gpt-5.6-luna:medium:implementer",
                "requested_model": "gpt-5.6-luna",
                "requested_effort": "medium",
                "capability_state": "CONFIGURED_EXPLICIT",
                "execution_eligible": True,
                "fallback_observed": False,
            },
            {
                "route_id": "codex:gpt-5.6-terra:high:implementer",
                "requested_model": "gpt-5.6-terra",
                "requested_effort": "high",
                "capability_state": "CONFIRMED",
                "execution_eligible": True,
                "fallback_observed": False,
            },
        ]

    def test_three_roles_and_caps_are_recorded(self) -> None:
        calls = []
        outcomes = []

        def executor(route, role):
            calls.append((route["route_id"], role))
            return {"verifier_pass": not (role == "implementer" and route["requested_model"] == "gpt-5.6-luna"), "latency_ms": 12.0}

        value = run_adaptive_calibration(self.routes(), executor=executor, record_outcome=lambda route, role, result: outcomes.append((route, role, result)))
        self.assertEqual(value["schema"], "contextcord-adaptive-router-calibration-v1")
        self.assertEqual(len(value["tasks"]), 3)
        self.assertTrue(all(row["status"] == "PASS" for row in value["tasks"]))
        self.assertEqual(value["codex_executions_used"], 4)
        self.assertLessEqual(value["codex_executions_used"], 6)
        self.assertEqual(len(outcomes), 4)
        self.assertEqual({row[2]["identity_evidence"] for row in outcomes}, {"configured_explicit", "resolved_telemetry"})

    def test_empty_execution_catalog_is_a_truthful_host_blocker(self) -> None:
        value = run_adaptive_calibration([])
        self.assertEqual(value["codex_executions_used"], 0)
        self.assertEqual(value["stop_reason"], "execution_catalog_empty_host_capability_blocker")
        self.assertTrue(all(row["status"] == "NOT_RUN" for row in value["tasks"]))

    def test_host_only_outcome_is_retained_but_excluded_from_learning_summary(self) -> None:
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name)
        try:
            subprocess.check_call(["git", "init", "-q", str(repo)])
            (repo / "AGENTS.md").write_text("policy\n", encoding="utf-8")
            write_profile(repo, "generic", state_dir=".contextcord")
            subprocess.check_call(["git", "-C", str(repo), "add", "."])
            subprocess.check_call(["git", "-C", str(repo), "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-qm", "initial"])
            with StateStore(repo) as store:
                store.record_model_outcome(task_class="reviewer", role="reviewer", model_id="gpt-5.6-luna", reasoning_effort="medium", verifier_pass=True, identity_evidence="host_only")
                store.record_model_outcome(task_class="reviewer", role="reviewer", model_id="gpt-5.6-luna", reasoning_effort="medium", verifier_pass=True, identity_evidence="configured_explicit")
                self.assertEqual(len(store.model_outcomes()), 2)
                summary = store.model_outcome_summary()
            self.assertEqual(summary[0]["observations"], 1)
            self.assertEqual(summary[0]["configured_explicit_observations"], 1)
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
