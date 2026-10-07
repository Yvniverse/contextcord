from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contextcord.decision import rank_candidates


class FakeTransport:
    def __init__(self) -> None:
        self.state = None

    def system_one(self, state, questions, *, model):
        self.state = state
        return {
            "model": model,
            "nouls": {
                "candidate_0": {"noul": 0.9},
                "candidate_1": {"noul": 0.2},
            },
            "usage": {"input_tokens": 40, "output_tokens": 8, "total_tokens": 48},
        }


class JevProviderTests(unittest.TestCase):
    def candidates(self):
        return [
            {"memory_id": "m1", "summary": "retry bounded", "next_action": "run tests", "source": "private"},
            {"memory_id": "m2", "summary": "unrelated docs", "next_action": "write README", "source": "private"},
        ]

    def test_fake_jev_ranking_keeps_truth_fields_local(self) -> None:
        from contextcord.jev_provider import JevApiDecisionProvider
        transport = FakeTransport()
        result = JevApiDecisionProvider(transport=transport).rank("retry", self.candidates())
        self.assertEqual(result["status"], "JEV_FAKE_PASS")
        self.assertEqual(result["selected_memory_ids"], ["m1", "m2"])
        self.assertEqual(result["usage"]["total_tokens"], 48)
        self.assertNotIn("source", transport.state["candidates"][0])

    def test_missing_project_key_is_explicit_not_run_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = rank_candidates("retry", self.candidates(), provider="jev_api", project_root=Path(td))
        self.assertEqual(result["status"], "NOT_RUN")
        self.assertEqual(result["effective_provider"], "heuristic")
        self.assertIn("API_KEY_MISSING", result["fallback_reason"])

    def test_heuristic_is_distinguished_from_jev_usage(self) -> None:
        result = rank_candidates("retry", self.candidates(), provider="heuristic")
        self.assertEqual(result["status"], "HEURISTIC_PASS")
        self.assertIsNone(result["usage"])


if __name__ == "__main__":
    unittest.main()
