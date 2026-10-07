from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contextcord.model_intelligence import (
    aggregate_codexradar,
    fetch_codexradar_table,
    load_codexradar_prior,
)


class _Response:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class ModelIntelligenceTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "benchmark_id": "deep-swe",
            "cells": {
                "t1|gpt-5.6-luna|medium": {"agent": "codex", "rate": 0.8, "cost": 1.2, "min": 4, "est_quota_pct": 1.5, "total_n": 3},
                "t2|gpt-5.6-luna|medium": {"agent": "codex", "p": 90, "cost": 1.0, "min": 3, "est_quota_pct": 1.0, "total_n": 2},
                "t3|gpt-6|max": {"agent": "codex", "rate": 1.0},
                "t4|gpt-5.6-sol|max": {"agent": "other", "rate": 1.0},
            },
        }

    def test_live_fetch_aggregates_only_allowed_codex_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "codexradar.json"
            with patch("contextcord.model_intelligence.urllib.request.urlopen", return_value=_Response(self._payload())):
                result = fetch_codexradar_table(cache_path=cache, now=1000)
            self.assertEqual(result["status"], "LIVE")
            self.assertTrue(cache.is_file())
            derived = aggregate_codexradar(result["payload"])
            self.assertEqual([(row["model_id"], row["reasoning_effort"]) for row in derived["routes"]], [("gpt-5.6-luna", "medium")])
            self.assertEqual(derived["routes"][0]["task_count"], 2)
            self.assertFalse(derived["raw_payload_committed"])

    def test_fresh_cache_is_used_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "codexradar.json"
            cache.write_text(json.dumps({"fetched_at": 1000, "payload": self._payload()}), encoding="utf-8")
            with patch("contextcord.model_intelligence.urllib.request.urlopen", side_effect=AssertionError("network should not be called")):
                result = fetch_codexradar_table(cache_path=cache, now=1100)
            self.assertEqual(result["status"], "FRESH_CACHE")

    def test_stale_cache_is_used_on_provider_failure_within_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "codexradar.json"
            cache.write_text(json.dumps({"fetched_at": 1000, "payload": self._payload()}), encoding="utf-8")
            with patch("contextcord.model_intelligence.urllib.request.urlopen", side_effect=OSError("offline")):
                result = fetch_codexradar_table(cache_path=cache, now=1200, ttl_seconds=10, max_stale_seconds=86400)
            self.assertEqual(result["status"], "STALE_CACHE")

    def test_unavailable_is_nonblocking_and_public_default_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("contextcord.model_intelligence.urllib.request.urlopen", side_effect=OSError("offline")):
                result = fetch_codexradar_table(cache_path=Path(directory) / "missing.json", now=1000)
            self.assertEqual(result["status"], "UNAVAILABLE")
            disabled = load_codexradar_prior(directory)
            self.assertEqual(disabled["status"], "UNAVAILABLE")
            self.assertEqual(disabled["reason"], "disabled_by_default_or_public_release")


if __name__ == "__main__":
    unittest.main()
