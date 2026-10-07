"""Regression coverage for bounded selection, integrity and atomic confirmation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from contextcord.config import discover
from contextcord.decision_fabric import DecisionFabric
from contextcord.handoff import assist_handoff
from contextcord.memory import add_note
from contextcord.profiles import write_profile
from contextcord.store import StateStore
from contextcord.workflow import initial_task


class RankProvider:
    def __init__(self, selected=None, fail=False):
        self.selected, self.fail, self.ranked = selected, fail, []

    def decide(self, state, questions, *, stage):
        if self.fail:
            raise TimeoutError("semantic service unavailable")
        return {"status": "JEV_FAKE_PASS", "effective_provider": "jev_api", "answers": {"needs_semantic_rerank": {"value": False}}}

    def rank(self, query, candidates, *, limit):
        self.ranked = candidates
        return {"status": "JEV_FAKE_PASS", "effective_provider": "jev_api", "selected_memory_ids": self.selected or [candidates[-1]["memory_id"]]}


class HandoffSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "AGENTS.md").write_text("# policy\n", encoding="utf-8")
        (self.repo / "source.py").write_text("budget = 3\n", encoding="utf-8")
        write_profile(self.repo, "generic")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=ContextCord Tests", "-c", "user.email=tests@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"], check=True)
        self.cfg = discover(self.repo)
        task = initial_task("task", "code", self.cfg.workflow)
        task["next_action"] = "retry timeout"
        with StateStore(self.repo) as store:
            store.upsert_task(task)

    def tearDown(self):
        self.temp.cleanup()

    def note(self, ident, text, bound=False):
        return add_note(self.cfg, task_id="task", note_id=ident, text=text, depends_on=["source.py"] if bound else [])

    def test_bm25_prefers_rare_query_term_over_repeated_overlap(self):
        self.note("repetition", "retry " * 100)
        self.note("specific", "timeout")
        self.note("background", "retry implementation detail")
        preview = assist_handoff(self.cfg, task_id="task")
        self.assertEqual(preview["continuation"]["selected_memory"][0]["memory_id"], "specific")
        self.assertEqual(preview["decision_receipt"]["selection"]["selector"], "bm25")

    def test_all_stale_pool_stays_empty(self):
        self.note("stale", "retry timeout", bound=True)
        (self.repo / "source.py").write_text("changed\n", encoding="utf-8")
        preview = assist_handoff(self.cfg, task_id="task")
        self.assertEqual(preview["continuation"]["selected_memory"], [])
        self.assertEqual(preview["continuation"]["freshness"]["revalidation_required"], ["stale"])
        self.assertIn("REVALIDATE_STALE", preview["decision_receipt"]["code_actions"])

    def test_semantic_rank_runs_on_bounded_eligible_pool(self):
        for index in range(40):
            self.note(f"note-{index:02}", "retry timeout")
        self.note("stale", "retry timeout", bound=True)
        (self.repo / "source.py").write_text("changed\n", encoding="utf-8")
        provider = RankProvider()
        with patch("contextcord.decision_fabric.make_provider", return_value=provider):
            preview = assist_handoff(self.cfg, task_id="task", provider="jev_api")
        self.assertEqual(len(provider.ranked), 24)
        self.assertNotIn("stale", {row["memory_id"] for row in provider.ranked})
        self.assertEqual([row["memory_id"] for row in preview["continuation"]["selected_memory"]], [provider.ranked[-1]["memory_id"]])

    def test_provider_outage_records_bm25_fallback(self):
        for index in range(5):
            self.note(f"note-{index}", "retry timeout")
        with patch("contextcord.decision_fabric.make_provider", return_value=RankProvider(fail=True)):
            preview = assist_handoff(self.cfg, task_id="task", provider="jev_api")
        self.assertEqual(len(preview["continuation"]["selected_memory"]), 3)
        self.assertEqual(preview["decision_receipt"]["jev"]["status"], "FALLBACK")
        self.assertEqual(preview["decision_receipt"]["selection"]["fallback_selector"], "bm25")

    def test_invalid_ids_are_rejected_before_handoff_fallback(self):
        self.note("a", "retry timeout")
        self.note("b", "retry timeout")
        with patch("contextcord.decision_fabric.make_provider", return_value=RankProvider(selected=["unlisted"])):
            preview = assist_handoff(self.cfg, task_id="task", provider="jev_api")
        self.assertEqual(preview["decision_receipt"]["selection"]["status"], "INVALID_SELECTION")
        self.assertNotIn("unlisted", {row["memory_id"] for row in preview["continuation"]["selected_memory"]})

    def test_event_tampering_blocks_preview_and_confirmation(self):
        self.note("a", "retry timeout")
        with StateStore(self.repo) as store:
            store.conn.execute("UPDATE events SET payload_json='{}'")
        for confirm in (False, True):
            result = assist_handoff(self.cfg, task_id="task", confirm=confirm)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["continuation"]["selected_memory"], [])
        with StateStore(self.repo) as store:
            self.assertEqual(store.open_sessions("task"), [])
            self.assertEqual(store.context_jobs_for_task("task"), [])

    def test_concurrent_confirmations_create_only_one_session(self):
        import contextcord.handoff as module
        self.note("a", "retry timeout")
        barrier = threading.Barrier(2)
        original = module._handoff_decision
        def synchronize(*args, **kwargs):
            result = original(*args, **kwargs)
            barrier.wait(timeout=20)
            return result
        with patch.object(module, "_handoff_decision", side_effect=synchronize), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(assist_handoff, self.cfg, task_id="task", confirm=True) for _ in range(2)]
            results = [future.result(timeout=40) for future in futures]
        self.assertCountEqual([row["status"] for row in results], ["PASS", "OPEN_SESSION_EXISTS"])
        with StateStore(self.repo) as store:
            self.assertEqual(len(store.open_sessions("task")), 1)
            self.assertEqual(len(store.context_jobs_for_task("task")), 1)
            self.assertTrue(store.verify_event_chain()[0])


class SelectionGateTests(unittest.TestCase):
    def state(self):
        return {"candidate_count": 2, "candidate_scores": [0, 0], "candidates": [{"memory_id": "a", "freshness": "FRESH"}, {"memory_id": "stale", "freshness": "STALE"}]}

    def test_hard_gate_prevents_semantic_ranking(self):
        provider = RankProvider()
        result = DecisionFabric(provider=provider, provider_name="jev_api").select_candidates({**self.state(), "permission_allowed": False}, query="retry", limit=1)
        self.assertEqual(result.selected_memory_ids, ())
        self.assertEqual(result.receipt["selection"]["status"], "BLOCKED")
        self.assertEqual(provider.ranked, [])

    def test_provider_cannot_select_stale_or_repeated_ids(self):
        for selected in (["stale"], ["a", "a"]):
            provider = RankProvider(selected=selected)
            result = DecisionFabric(provider=provider, provider_name="jev_api").select_candidates(self.state(), query="retry", limit=2)
            self.assertEqual(result.selected_memory_ids, ())
            self.assertEqual(result.receipt["selection"]["status"], "INVALID_SELECTION")
            self.assertEqual([row["memory_id"] for row in provider.ranked], ["a"])


if __name__ == "__main__":
    unittest.main()
