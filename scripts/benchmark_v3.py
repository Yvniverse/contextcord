"""Bounded context-selection fixture using the canonical ContextCord implementation."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
_ROOT = Path(__file__).resolve().parents[1]
# Keep only the bounded selection contract needed by public regression tests.
from contextcord.bm25 import BM25Selector, candidate_pool_sha256
from contextcord.decision_fabric import DecisionFabric, make_provider

_FIXTURE = _ROOT / "support" / "benchmark_v3"
_QUERY = "continue relay retry resume implementation against current contract"

def _load_candidates() -> list[dict[str, Any]]:
    value = json.loads((_FIXTURE / "memory_candidates.json").read_text(encoding="utf-8"))
    rows = value.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise ValueError("benchmark_candidate_pool_invalid")
    result = []
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("id"):
            raise ValueError("benchmark_candidate_invalid")
        result.append({**dict(row), "memory_id": str(row["id"])})
    return result

def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", " ").strip()[:limit]

def _select_context(arm: str, candidates: Sequence[Mapping[str, Any]]) -> tuple[str, dict[str, Any]]:
    metadata: dict[str, Any] = {
        "candidate_pool_sha256": None,
        "selected_memory_ids": [],
        "restored_archive_ids": [],
        "selector": "none",
        "provider_status": None,
        "provider_model": None,
        "jev_usage": None,
        "decision_receipt": None,
    }
    packet = f"# Bounded continuation context\n\nArm: {arm}\n"
    if arm == "CONTEXTCORD_BM25":
        selection = BM25Selector().select(_QUERY, candidates, limit=4)
        metadata.update({
            "candidate_pool_sha256": selection.candidate_pool_sha256,
            "selected_memory_ids": list(selection.selected_memory_ids),
            "selector": "bm25_okapi",
        })
        blocks = ["Selector: real Okapi BM25."]
        for row in selection.selected:
            blocks.append(
                "\n".join([
                    f"## Memory {row['memory_id']} ({row.get('freshness', 'UNKNOWN')})",
                    f"Source: {_bounded_text(row.get('source'), 160)}",
                    f"Text: {_bounded_text(row.get('text'), 1200)}",
                ])
            )
        return packet + "\n".join(blocks) + "\n", metadata
    if arm != "CONTEXTCORD_JEV":
        raise ValueError(f"unknown_benchmark_arm:{arm}")
    state = {
        "task_id": "relay-trace-017",
        "task_prompt": _QUERY,
        "next_action": "Implement and verify relay retry/resume continuation.",
        "host": "public-benchmark-boundary",
        "candidates": list(candidates),
        "candidate_count": len(candidates),
        "stale_count": sum(str(row.get("freshness", "")).upper() == "STALE_REVALIDATE" for row in candidates),
        "relevance_margin": 0.0,
        "budget_tokens": 6000,
        "hard_relevant_estimated_tokens": 1200,
        "semantic_conflict_markers": ["stale_candidate", "archive_edge_cases"],
        "restore_uncertainty": True,
        "archive_restore_candidates": ["relay-trace-017"],
        "retrieval_incomplete": True,
        "permission_allowed": True,
        "integrity_status": "PASS",
        "qualification_pass": True,
        "frozen_tests_pass": True,
        "release_gate_pass": True,
        "destructive_side_effects_approved": False,
        "deterministic_limit": 4,
    }
    fabric = DecisionFabric(provider=make_provider("jev_api", project_root=str(_ROOT)), provider_name="jev_api")
    receipt = fabric.select_candidates(state, query=_QUERY, limit=4, force=True).receipt
    selection = receipt.get("selection") if isinstance(receipt.get("selection"), Mapping) else {}
    metadata.update({
        "selector": "production_decision_fabric_jev",
        "provider_status": selection.get("status") or receipt.get("jev", {}).get("status"),
        "provider_model": selection.get("model") or receipt.get("jev", {}).get("model"),
        "jev_usage": selection.get("usage") or receipt.get("jev", {}).get("usage"),
        "selected_memory_ids": [str(item) for item in (selection.get("selected_memory_ids") or [])],
        "candidate_pool_sha256": selection.get("candidate_pool_sha256"),
        "decision_receipt": receipt,
    })
    live = metadata["provider_status"] in {"JEV_LIVE_PASS", "JEV_FAKE_PASS"} and selection.get("provider") == "jev_api"
    if not live:
        return packet + "Jev Decision Fabric status: PROVIDER_UNAVAILABLE.\n", metadata
    by_id = {str(row["memory_id"]): row for row in candidates}
    blocks = ["Selector: production Decision Fabric with Jev provider-backed ranking."]
    for memory_id in metadata["selected_memory_ids"]:
        row = by_id.get(memory_id)
        if row:
            blocks.append(
                "\n".join([
                    f"## Memory {memory_id} ({row.get('freshness', 'UNKNOWN')})",
                    f"Source: {_bounded_text(row.get('source'), 160)}",
                    f"Text: {_bounded_text(row.get('text'), 1200)}",
                ])
            )
    return packet + "\n".join(blocks) + "\n", metadata
