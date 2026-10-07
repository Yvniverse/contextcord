from __future__ import annotations

import tempfile
import unittest
import subprocess
from pathlib import Path

from contextcord.decision_fabric import DecisionFabric, gate0, state_sha256
from contextcord.handoff import assist_handoff
from contextcord.config import discover
from contextcord.profiles import write_profile
from contextcord.store import StateStore
from contextcord.workflow import initial_task


class BundleProvider:
    mode = "fake_bundle"

    def __init__(self) -> None:
        self.stages: list[str] = []

    def decide(self, state, questions, *, stage):
        self.stages.append(stage)
        answers = {}
        for question in questions:
            ident = question["id"]
            value = True if ident == "needs_semantic_rerank" else "CONTINUITY_ONLY" if ident == "tool_profile" else "STANDARD" if ident == "handoff_mode" else False
            answers[ident] = {"type": question.get("type", "noul"), "value": value, "confidence": 0.95}
        return {"status": "FAKE_PASS", "model": "fake", "answers": answers, "usage": {"total_tokens": 7}, "latency_ms": 1.2}


class FailingProvider:
    mode = "failing"

    def decide(self, state, questions, *, stage):
        raise TimeoutError("temporary semantic outage")


class DecisionFabricTests(unittest.TestCase):
    def test_gate_zero_bypasses_clear_single_candidate(self) -> None:
        result = gate0({"candidates": [{"memory_id": "m1"}], "stale_count": 0})
        self.assertEqual(result["outcome"], "BYPASS_JEV_SIMPLE_CASE")

    def test_gate_zero_requests_semantics_for_stale_ambiguous_pool(self) -> None:
        result = gate0({"candidate_count": 3, "candidate_scores": [1, 1, 0.9], "stale_count": 1})
        self.assertEqual(result["outcome"], "REQUEST_JEV_SEMANTIC_JUDGMENT")
        self.assertIn("STALE_PRESENT", result["reason_codes"])

    def test_bundle_receipt_escalates_and_hard_gate_wins(self) -> None:
        provider = BundleProvider()
        state = {
            "candidate_count": 2, "candidate_scores": [1, 1], "stale_count": 1,
            "candidates": [{"memory_id": "m1", "freshness": "FRESH"}],
            "secret_blocker": True, "integrity_status": "PASS",
        }
        result = DecisionFabric(provider=provider, provider_name="fake_bundle").evaluate(state)
        self.assertEqual(provider.stages, ["gate", "deep"])
        self.assertEqual(result.receipt["state_sha256"], state_sha256(state))
        self.assertIn("BLOCK_SECRET", result.receipt["hard_gate_overrides"])
        self.assertIn("NO_SEMANTIC_OVERRIDE", result.receipt["code_actions"])
        self.assertEqual(result.receipt["escalated_second_stage"], True)

    def test_provider_failure_is_a_recorded_nonblocking_fallback(self) -> None:
        result = DecisionFabric(provider=FailingProvider(), provider_name="jev_api").evaluate({"candidate_count": 2, "candidate_scores": [0, 0]})
        self.assertEqual(result.receipt["jev"]["status"], "FALLBACK")
        self.assertTrue(result.receipt["jev"]["fallback_used"])
        self.assertEqual(result.receipt["jev"]["effective_provider"], "deterministic_fallback")


class AssistedHandoffTests(unittest.TestCase):
    def test_preview_then_confirmation_creates_one_local_session_and_job(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.check_call(["git", "init", "-q", str(repo)])
            subprocess.check_call(["git", "-C", str(repo), "config", "user.email", "test@example.com"])
            subprocess.check_call(["git", "-C", str(repo), "config", "user.name", "Harness Test"])
            (repo / "AGENTS.md").write_text("# test\n", encoding="utf-8")
            (repo / "src").mkdir(); (repo / "src" / "app.py").write_text("ok\n", encoding="utf-8")
            write_profile(repo, "generic")
            subprocess.check_call(["git", "-C", str(repo), "add", "."])
            subprocess.check_call(["git", "-C", str(repo), "commit", "-qm", "initial"])
            cfg = discover(repo)
            task = initial_task("handoff-task", "code", cfg.workflow)
            task["next_action"] = "continue retry implementation and run tests"
            with StateStore(repo) as store, store.transaction():
                store.upsert_task(task)
                store.create_note(task_id="handoff-task", text="Retry budget policy is implemented; continue tests.")
            preview = assist_handoff(cfg, task_id="handoff-task", host="qoder")
            self.assertEqual(preview["status"], "AWAITING_CONFIRMATION")
            self.assertTrue(preview["requires_confirmation"])
            with StateStore(repo) as store:
                self.assertEqual(store.open_sessions("handoff-task"), [])
            confirmed = assist_handoff(cfg, task_id="handoff-task", host="qoder", confirm=True)
            self.assertEqual(confirmed["status"], "PASS")
            self.assertTrue(confirmed["session_id"])
            with StateStore(repo) as store:
                self.assertEqual(len(store.open_sessions("handoff-task")), 1)
                self.assertEqual(len(store.context_jobs_for_task("handoff-task")), 1)


if __name__ == "__main__":
    unittest.main()
