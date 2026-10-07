from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contextcord.calibration import _run_codex_task, _synthetic_answer_is_42, run_adaptive_calibration
from contextcord.profiles import write_profile
from contextcord.store import StateStore


class AdaptiveCalibrationTests(unittest.TestCase):
    def test_static_fixture_verifier_accepts_only_literal_integer_answer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.py"
            for body in ('def answer():\n    return 42\n', '"""Fixture."""\ndef answer():\n    """Answer."""\n    return 42\n'):
                with self.subTest(body=body):
                    source.write_text(body, encoding="utf-8")
                    self.assertTrue(_synthetic_answer_is_42(source))
            for body in (
                'def answer():\n    return 0\n',
                'def answer():\n    return 42.0\n',
                'def answer():\n    return 21 + 21\n',
                'def answer(value=42):\n    return 42\n',
                'def answer(*args):\n    return 42\n',
                '@decorate\ndef answer():\n    return 42\n',
                'def answer() -> annotate():\n    return 42\n',
                'def answer():\n    side_effect()\n    return 42\n',
                'import os\ndef answer():\n    return 42\n',
                'async def answer():\n    return 42\n',
                'def answer(:\n',
            ):
                with self.subTest(body=body):
                    source.write_text(body, encoding="utf-8")
                    self.assertFalse(_synthetic_answer_is_42(source))
            source.unlink()
            self.assertFalse(_synthetic_answer_is_42(source))

    def test_implementer_verifier_never_executes_generated_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "side-effect.txt"

            def edited_fixture(command, **kwargs):
                source = Path(kwargs["cwd"]) / "src/app.py"
                source.write_text(
                    "from pathlib import Path\n"
                    f"Path({str(marker)!r}).write_text('executed')\n"
                    "def answer():\n    return 42\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="IMPLEMENTER_PASS", stderr="")

            with patch("contextcord.calibration.shutil.which", return_value="codex"), patch("contextcord.calibration.subprocess.run", side_effect=edited_fixture):
                result = _run_codex_task(self.routes()[0], "implementer")
            self.assertFalse(result["verifier_pass"])
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(marker.exists())

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
