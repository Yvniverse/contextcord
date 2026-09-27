import unittest
from unittest.mock import patch

from scripts import benchmark_v3


class _UnavailableProvider:
    mode = "jev_api"

    def decide(self, state, questions, *, stage):
        return {
            "status": "FALLBACK",
            "effective_provider": "deterministic_fallback",
            "fallback_used": True,
            "fallback_reason": "test_unavailable",
            "answers": {},
        }

    def rank(self, query, candidates, *, limit=None):
        raise AssertionError("unavailable provider must not rank")


class _LiveProvider:
    mode = "jev_api"

    def __init__(self):
        self.rank_called = False

    def decide(self, state, questions, *, stage):
        return {
            "status": "JEV_LIVE_PASS",
            "effective_provider": "jev_api",
            "fallback_used": False,
            "model": "test-jev",
            "usage": {"total_tokens": 3},
            "answers": {},
        }

    def rank(self, query, candidates, *, limit=None):
        self.rank_called = True
        return {
            "status": "JEV_LIVE_PASS",
            "effective_provider": "jev_api",
            "fallback_used": False,
            "selected_memory_ids": [str(candidates[0]["memory_id"])],
            "candidate_pool_sha256": "pool",
            "model": "test-jev",
            "usage": {"total_tokens": 4},
            "duration_ms": 1.0,
        }


class LiveBenchmarkBoundaryTests(unittest.TestCase):
    def test_host_packet_does_not_contain_full_pool_or_archive(self):
        candidates = benchmark_v3._load_candidates()
        packet, metadata = benchmark_v3._select_context("AGENT_NEXUS_BM25", candidates)
        self.assertEqual("bm25_okapi", metadata["selector"])
        self.assertNotIn("mem-ui-note", packet)
        self.assertNotIn("0007", packet)
        self.assertNotIn("raw_archive_relay-trace-017.json", packet)

    def test_jev_unavailable_is_not_relabelled_as_fallback_success(self):
        candidates = benchmark_v3._load_candidates()
        with patch.object(benchmark_v3, "make_provider", return_value=_UnavailableProvider()):
            packet, metadata = benchmark_v3._select_context("AGENT_NEXUS_JEV", candidates)
        self.assertEqual("PROVIDER_UNAVAILABLE", metadata["provider_status"])
        self.assertEqual([], metadata["selected_memory_ids"])
        self.assertIn("PROVIDER_UNAVAILABLE", packet)
        self.assertNotIn("mem-current-contract", packet)

    def test_live_jev_calls_rank_through_decision_fabric(self):
        candidates = benchmark_v3._load_candidates()
        provider = _LiveProvider()
        with patch.object(benchmark_v3, "make_provider", return_value=provider):
            packet, metadata = benchmark_v3._select_context("AGENT_NEXUS_JEV", candidates)
        self.assertTrue(provider.rank_called)
        self.assertEqual("JEV_LIVE_PASS", metadata["provider_status"])
        self.assertEqual(["mem-current-contract"], metadata["selected_memory_ids"])
        self.assertIn("mem-current-contract", packet)


if __name__ == "__main__":
    unittest.main()
