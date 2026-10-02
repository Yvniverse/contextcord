"""Optional, vendor-neutral ranking for already retrieved memory candidates."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
ALLOWED_MODES = ("disabled", "heuristic", "jev_api")


def _tokens(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, Mapping):
        return set().union(*(_tokens(k) | _tokens(v) for k, v in value.items())) if value else set()
    if isinstance(value, (list, tuple, set)):
        return set().union(*(_tokens(item) for item in value)) if value else set()
    return set(TOKEN_RE.findall(str(value).casefold()))


def _candidate_text(candidate: Mapping[str, Any]) -> str:
    return " ".join(str(candidate.get(key, "")) for key in ("summary", "next_action", "text", "content", "description"))


def _validate(query: str, candidates: Sequence[Mapping[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if not isinstance(query, str) or not query.strip() or len(query) > 4096:
        raise ValueError("query_must_be_nonempty_max_4096")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)) or not 1 <= len(candidates) <= 200:
        raise ValueError("candidates_must_be_1_to_200")
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 200):
        raise ValueError("limit_must_be_1_to_200")
    result = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("candidate_must_be_object")
        memory_id = candidate.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id.strip() or memory_id in seen:
            raise ValueError("candidate_memory_id_must_be_unique_nonempty")
        seen.add(memory_id)
        result.append(dict(candidate))
    return result


def _pool_hash(candidates: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(list(candidates), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


def _response(*, requested_provider: str, effective_provider: str, status: str, query: str,
              candidates: Sequence[Mapping[str, Any]], ranked: Sequence[tuple[Mapping[str, Any], float | None, int]],
              limit: int | None, started: float, fallback_used: bool = False,
              fallback_reason: str | None = None, usage: Mapping[str, Any] | None = None,
              model: str | None = None, key_source: str | None = None,
              question_schema: str | None = None) -> dict[str, Any]:
    rows = []
    for rank, (candidate, score, original_index) in enumerate(list(ranked)[: limit or len(ranked)], 1):
        row = dict(candidate)
        row.update(rank=rank, decision_score=score, original_index=original_index)
        rows.append(row)
    return {
        "schema": "contextcord-memory-ranking-v1",
        "requested_provider": requested_provider,
        "effective_provider": effective_provider,
        "status": status,
        "query": query,
        "candidate_count": len(candidates),
        "selected_count": len(rows),
        "selected_memory_ids": [row["memory_id"] for row in rows],
        "candidates": rows,
        "candidate_pool_sha256": _pool_hash(candidates),
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "usage": dict(usage) if usage is not None else None,
        "model": model,
        "key_source": key_source,
        "question_schema": question_schema,
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "confidence_boundary": "Ordinal relevance only; no confidence calibration or authorization.",
        "truth_boundary": "Source, evidence and freshness are forwarded unchanged; ranking cannot upgrade stale memory.",
    }


class DisabledDecisionProvider:
    mode = "disabled"

    def rank(self, query, candidates, *, limit=None):
        started = time.monotonic()
        return _response(requested_provider=self.mode, effective_provider=self.mode, status="DISABLED", query=query,
                         candidates=candidates, ranked=[(row, None, i) for i, row in enumerate(candidates)],
                         limit=limit, started=started)


class HeuristicDecisionProvider:
    mode = "heuristic"

    def rank(self, query, candidates, *, limit=None):
        started = time.monotonic()
        query_tokens = _tokens(query)
        scored = []
        for index, candidate in enumerate(candidates):
            text = _candidate_text(candidate)
            overlap = len(query_tokens & _tokens(text))
            phrase = 1 if query.casefold().strip() in text.casefold() else 0
            scored.append((candidate, float(overlap * 2 + phrase), index))
        scored.sort(key=lambda row: (-float(row[1] or 0), row[2]))
        return _response(requested_provider=self.mode, effective_provider=self.mode, status="HEURISTIC_PASS",
                         query=query, candidates=candidates, ranked=scored, limit=limit, started=started)


def rank_candidates(query: str, candidates: Sequence[Mapping[str, Any]], *, provider: str = "disabled",
                    limit: int | None = None, project_root: str | Path | None = None,
                    model: str | None = None, endpoint: str | None = None) -> dict[str, Any]:
    checked = _validate(query, candidates, limit)
    if provider == "disabled":
        engine = DisabledDecisionProvider()
    elif provider == "heuristic":
        engine = HeuristicDecisionProvider()
    elif provider == "jev_api":
        from .jev_provider import JevApiDecisionProvider
        engine = JevApiDecisionProvider(project_root=project_root, model=model, endpoint=endpoint)
    else:
        raise ValueError("unknown_decision_provider")
    return engine.rank(query, checked, limit=limit)
