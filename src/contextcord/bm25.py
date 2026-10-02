"""Small, deterministic BM25 selector used by bounded-context workflows.

The selector is intentionally independent of host adapters.  It ranks the
candidate pool it is given and returns only the selected rows; packet assembly
and archive restoration remain separate, code-owned steps.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(value: Any) -> list[str]:
    return TOKEN_RE.findall(str(value or "").casefold())


def _candidate_id(row: Mapping[str, Any]) -> str:
    value = row.get("memory_id", row.get("id"))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("candidate_memory_id_required")
    return value.strip()


def _candidate_text(row: Mapping[str, Any]) -> str:
    return " ".join(
        str(row.get(key, ""))
        for key in ("summary", "text", "content", "next_action", "source", "kind")
    )


def candidate_pool_sha256(candidates: Sequence[Mapping[str, Any]]) -> str:
    """Return a stable hash of the exact pool supplied to the selector."""
    raw = json.dumps(
        [dict(row) for row in candidates],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class BM25Selection:
    query: str
    selected: tuple[dict[str, Any], ...]
    candidate_pool_sha256: str
    duration_ms: float
    k1: float
    b: float

    @property
    def selected_memory_ids(self) -> tuple[str, ...]:
        return tuple(str(row["memory_id"]) for row in self.selected)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "contextcord-bm25-selection-v1",
            "selector": "bm25",
            "query": self.query,
            "selected_memory_ids": list(self.selected_memory_ids),
            "selected": [dict(row) for row in self.selected],
            "candidate_pool_sha256": self.candidate_pool_sha256,
            "duration_ms": self.duration_ms,
            "parameters": {"k1": self.k1, "b": self.b},
            "truth_boundary": "BM25 ranks the supplied pool; it does not establish freshness, authorization or completion.",
        }


class BM25Selector:
    """Deterministic Okapi BM25 selector with stable tie breaking."""

    def __init__(self, *, k1: float = 1.2, b: float = 0.75) -> None:
        if k1 < 0 or not 0 <= b <= 1:
            raise ValueError("invalid_bm25_parameters")
        self.k1 = float(k1)
        self.b = float(b)

    def select(
        self,
        query: str,
        candidates: Sequence[Mapping[str, Any]],
        *,
        limit: int = 4,
    ) -> BM25Selection:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query_must_be_nonempty")
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            raise ValueError("candidates_must_be_sequence")
        if not candidates:
            raise ValueError("candidates_must_not_be_empty")
        if type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("limit_out_of_range")

        started = time.monotonic()
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in candidates:
            if not isinstance(raw, Mapping):
                raise ValueError("candidate_must_be_object")
            row = dict(raw)
            memory_id = _candidate_id(row)
            if memory_id in seen:
                raise ValueError("candidate_memory_id_must_be_unique")
            seen.add(memory_id)
            row["memory_id"] = memory_id
            rows.append(row)

        query_tokens = _tokens(query)
        documents = [_tokens(_candidate_text(row)) for row in rows]
        average_length = sum(len(doc) for doc in documents) / max(1, len(documents))
        frequencies: dict[str, int] = {}
        for document in documents:
            for token in set(document):
                frequencies[token] = frequencies.get(token, 0) + 1

        scored: list[tuple[float, int, dict[str, Any]]] = []
        document_count = len(documents)
        for index, (row, document) in enumerate(zip(rows, documents)):
            score = 0.0
            document_length = len(document)
            for token in query_tokens:
                term_frequency = document.count(token)
                if not term_frequency:
                    continue
                document_frequency = frequencies.get(token, 0)
                idf = math.log(1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
                normalizer = term_frequency + self.k1 * (
                    1.0 - self.b + self.b * document_length / max(1.0, average_length)
                )
                score += idf * ((term_frequency * (self.k1 + 1.0)) / normalizer)
            scored.append((score, index, row))

        scored.sort(key=lambda item: (-item[0], item[1], str(item[2]["memory_id"])))
        selected = []
        for rank, (score, original_index, row) in enumerate(scored[:limit], start=1):
            selected.append(
                {
                    **row,
                    "bm25_score": round(float(score), 9),
                    "rank": rank,
                    "original_index": original_index,
                }
            )
        return BM25Selection(
            query=query,
            selected=tuple(selected),
            candidate_pool_sha256=candidate_pool_sha256(rows),
            duration_ms=round((time.monotonic() - started) * 1000, 3),
            k1=self.k1,
            b=self.b,
        )


def select_bm25(query: str, candidates: Sequence[Mapping[str, Any]], *, limit: int = 4) -> dict[str, Any]:
    """Convenience API for adapters and benchmark runners."""
    return BM25Selector().select(query, candidates, limit=limit).as_dict()


__all__ = ["BM25Selection", "BM25Selector", "candidate_pool_sha256", "select_bm25"]
