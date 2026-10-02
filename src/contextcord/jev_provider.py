"""Optional TypeSafe Jev adapter with a deterministic fallback boundary."""
from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from .jev_dotenv import ensure_jev_key


DEFAULT_ENDPOINT = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
QUESTION_SCHEMA = "contextcord-jev-memory-relevance-v1"
DECISION_BUNDLE_QUESTION_SCHEMA = "a12-decision-bundle-v1"


class JevTransport(Protocol):
    def system_one(self, state: Any, questions: Mapping[str, Any], *, model: str) -> Any: ...


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _usage(response: Any) -> dict[str, int] | None:
    raw = _field(response, "usage")
    if raw is None:
        return None
    result = {}
    for name in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens"):
        value = _field(raw, name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[name] = value
    return result or None


def _score(response: Any, key: str) -> float:
    answers = _field(response, "nouls") or _field(response, "answers")
    answer = _field(answers, key)
    value = _field(answer, "noul", _field(answer, "score", answer if isinstance(answer, (int, float)) else None))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise ValueError("jev_noul_score_invalid")
    return float(value)


def _reason(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int):
        return f"jev_http_{status}"
    name = type(exc).__name__.casefold()
    if "timeout" in name or "connection" in name:
        return "jev_connection_error"
    return "jev_request_error"


class JevApiDecisionProvider:
    mode = "jev_api"

    def __init__(self, *, project_root: str | Path | None = None, model: str | None = None,
                 endpoint: str | None = None, timeout: float = 15.0, max_retries: int = 0,
                 transport: JevTransport | None = None) -> None:
        self.project_root = Path(project_root).resolve() if project_root is not None else None
        self.model = (model or DEFAULT_MODEL).strip()
        self.endpoint = (endpoint or DEFAULT_ENDPOINT).strip().rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, min(int(max_retries), 2))
        parsed = urlsplit(self.endpoint)
        self.config_error = None if parsed.scheme == "https" and parsed.hostname == "api.typesafe.ai" and parsed.path in ("", "/") else "jev_endpoint_not_allowlisted"
        self.transport = transport

    @staticmethod
    def _projection(candidate: Mapping[str, Any]) -> dict[str, str]:
        return {key: str(candidate.get(key, ""))[:768] for key in ("memory_id", "summary", "next_action")}

    def _questions(self, candidates: Sequence[Mapping[str, Any]], noul_type: Any = None) -> dict[str, Any]:
        result = {}
        for index, candidate in enumerate(candidates):
            instructions = ("Rate relevance from 0.0 unrelated to 1.0 directly relevant. "
                            "Do not infer trust, freshness, authorization or completion. "
                            f"Candidate ID: {candidate.get('memory_id', '')}")
            result[f"candidate_{index}"] = noul_type(instructions=instructions) if noul_type else {"type": "noul", "instructions": instructions}
        return result

    def _call_once(self, state: Mapping[str, Any], questions: Mapping[str, Any]) -> Any:
        if self.transport is not None:
            return self.transport.system_one(state, questions, model=self.model)
        from typesafe_sdk import Choice, Noul, RetryPolicy, Score, TypeSafeClient
        sdk_questions = {}
        for key, value in questions.items():
            if not isinstance(value, Mapping):
                sdk_questions[key] = value
                continue
            instructions = str(value.get("instructions", ""))
            kind = str(value.get("type", "noul")).casefold()
            if kind == "score":
                criteria = value.get("criteria") or value.get("levels") or ["low", "medium", "high"]
                sdk_questions[key] = Score(instructions=instructions, criteria=[str(item) for item in criteria])
            elif kind == "choice":
                options = value.get("options") or value.get("criteria") or []
                sdk_questions[key] = Choice(instructions=instructions, criteria={str(item): None for item in options})
            else:
                sdk_questions[key] = Noul(instructions=instructions)
        with TypeSafeClient(model=self.model, base_url=self.endpoint, retry=RetryPolicy(max_retries=0), timeout=self.timeout) as client:
            return client.system_one(state, sdk_questions, model=self.model)

    @staticmethod
    def _fabric_projection(state: Mapping[str, Any]) -> dict[str, Any]:
        """Keep a Decision Fabric request bounded and free of host secrets."""
        allowed = {
            "task_id", "task_prompt", "next_action", "host", "model", "candidate_count",
            "stale_count", "relevance_margin", "budget_tokens", "hard_relevant_estimated_tokens",
            "semantic_conflict_markers", "restore_uncertainty", "archive_restore_candidates",
            "route_uncertainty", "host_model_uncertain", "retrieval_incomplete", "ask_user_risk",
            "merge_conflict_uncertain", "tool_profile_uncertain", "minimum_candidate_count",
        }
        projection = {key: state.get(key) for key in allowed if key in state}
        candidates = state.get("candidates")
        if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes)):
            projection["candidates"] = [JevApiDecisionProvider._projection(candidate) for candidate in candidates[:200] if isinstance(candidate, Mapping)]
        return projection

    @staticmethod
    def _bundle_questions(questions: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for question in questions:
            ident = str(question.get("id", "question"))
            kind = str(question.get("type", "noul")).casefold()
            item = {
                "type": kind if kind in {"noul", "score", "choice"} else "noul",
                "instructions": str(question.get("instructions") or (
                    "Answer this typed continuity decision. Do not decide integrity, secrets, permissions, qualification, frozen tests, release gates or destructive approval."
                )),
            }
            if kind == "score":
                item["levels"] = list(question.get("levels") or question.get("criteria") or ["none", "low", "medium", "high"])
            if kind == "choice":
                item["options"] = list(question.get("options") or question.get("criteria") or [])
            result[ident] = item
        return result

    def _bundle_fallback(self, state: Mapping[str, Any], questions: Sequence[Mapping[str, Any]], *, reason: str, key_source: str | None, attempts: int = 0) -> dict[str, Any]:
        # Import lazily to avoid a module cycle: decision_fabric selects this provider.
        from .decision_fabric import DeterministicDecisionProvider
        result = dict(DeterministicDecisionProvider().decide(state, questions, stage="gate"))
        result.update({
            "requested_provider": self.mode,
            "effective_provider": "deterministic_fallback",
            "status": "NOT_RUN" if attempts == 0 else "FALLBACK",
            "fallback_used": True,
            "fallback_reason": reason,
            "key_source": key_source,
            "model": result.get("model"),
            "requested_model": self.model,
            "endpoint": self.endpoint,
            "attempts": attempts,
            "question_schema": DECISION_BUNDLE_QUESTION_SCHEMA,
            "usage": None,
        })
        return result

    @staticmethod
    def _bundle_answers(response: Any, questions: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        answers = _field(response, "answers") or _field(response, "nouls") or {}
        result: dict[str, dict[str, Any]] = {}
        for question in questions:
            ident = str(question.get("id", ""))
            answer = _field(answers, ident)
            if answer is None:
                continue
            value = _field(answer, "value")
            if value is None:
                for name in ("choice", "score", "noul"):
                    value = _field(answer, name)
                    if value is not None:
                        break
            if value is None and isinstance(answer, (str, int, float, bool)):
                value = answer
            confidence = _field(answer, "confidence", 0.0)
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence)) if math.isfinite(confidence) else 0.0
            probabilities = _field(answer, "probabilities", {}) or {}
            if not isinstance(probabilities, Mapping):
                probabilities = {}
            if not confidence and probabilities:
                numeric_probabilities = [float(item) for item in probabilities.values() if isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(float(item))]
                if numeric_probabilities:
                    confidence = max(numeric_probabilities)
            result[ident] = {
                "type": str(question.get("type", "noul")),
                "value": value,
                "confidence": confidence,
                "probabilities": {str(key): float(value) for key, value in probabilities.items() if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))},
                "reason": str(_field(answer, "reason", ""))[:512],
            }
        return result

    def decide(self, state: Mapping[str, Any], questions: Sequence[Mapping[str, Any]], *, stage: str) -> dict[str, Any]:
        """Answer a typed Decision Bundle, with a local fallback on every failure."""
        started = time.monotonic()
        if self.config_error:
            return self._bundle_fallback(state, questions, reason=self.config_error, key_source=None)
        key_source = "fake_transport" if self.transport is not None else None
        if self.transport is None:
            present, key_source = ensure_jev_key(self.project_root)
            if not present:
                return self._bundle_fallback(state, questions, reason="JEV_NOT_RUN_API_KEY_MISSING", key_source=key_source)
            try:
                import typesafe_sdk  # noqa: F401
            except ImportError:
                return self._bundle_fallback(state, questions, reason="JEV_NOT_RUN_SDK_MISSING", key_source=key_source)
        request_state = self._fabric_projection(state)
        request_questions = self._bundle_questions(questions)
        response = None
        last_error: BaseException | None = None
        attempts = 0
        for _ in range(self.max_retries + 1):
            attempts += 1
            try:
                response = self._call_once(request_state, request_questions)
                break
            except Exception as exc:
                last_error = exc
                break
        if response is None:
            return self._bundle_fallback(state, questions, reason=_reason(last_error or RuntimeError("jev_request_failed")), key_source=key_source, attempts=attempts)
        answers = self._bundle_answers(response, questions)
        if not answers:
            return self._bundle_fallback(state, questions, reason="JEV_RESPONSE_INVALID", key_source=key_source, attempts=attempts)
        return {
            "status": "JEV_FAKE_PASS" if self.transport is not None else "JEV_LIVE_PASS",
            "requested_provider": self.mode,
            "effective_provider": self.mode,
            "fallback_used": False,
            "model": _field(response, "model") or self.model,
            "requested_model": self.model,
            "endpoint": self.endpoint,
            "answers": answers,
            "usage": _usage(response),
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "attempts": attempts,
            "stage": stage,
            "question_schema": DECISION_BUNDLE_QUESTION_SCHEMA,
            "key_source": key_source,
        }

    def _fallback(self, query: str, candidates: Sequence[Mapping[str, Any]], *, limit: int | None,
                  started: float, reason: str, key_source: str | None, attempts: int = 0) -> dict[str, Any]:
        from .decision import HeuristicDecisionProvider
        result = HeuristicDecisionProvider().rank(query, candidates, limit=limit)
        result.update({"requested_provider": self.mode, "effective_provider": "heuristic",
                       "status": "NOT_RUN" if attempts == 0 else "FALLBACK", "fallback_used": True,
                       "fallback_reason": reason, "key_source": key_source, "model": None,
                       "requested_model": self.model, "endpoint": self.endpoint, "attempts": attempts,
                       "question_schema": QUESTION_SCHEMA, "usage": None})
        return result

    def rank(self, query: str, candidates: Sequence[Mapping[str, Any]], *, limit: int | None = None) -> dict[str, Any]:
        started = time.monotonic()
        if self.config_error:
            return self._fallback(query, candidates, limit=limit, started=started, reason=self.config_error, key_source=None)
        key_source = "fake_transport" if self.transport is not None else None
        if self.transport is None:
            present, key_source = ensure_jev_key(self.project_root)
            if not present:
                return self._fallback(query, candidates, limit=limit, started=started,
                                      reason="JEV_NOT_RUN_API_KEY_MISSING", key_source=key_source)
            try:
                from typesafe_sdk import Noul
            except ImportError:
                return self._fallback(query, candidates, limit=limit, started=started,
                                      reason="JEV_NOT_RUN_SDK_MISSING", key_source=key_source)
        else:
            Noul = None
        projections = [self._projection(candidate) for candidate in candidates]
        state = {"query": query[:2048], "candidates": projections}
        questions = self._questions(projections, Noul)
        response = None
        last_error: BaseException | None = None
        attempts = 0
        for attempt in range(self.max_retries + 1):
            attempts += 1
            try:
                response = self._call_once(state, questions)
                break
            except Exception as exc:
                last_error = exc
                break
        if response is None:
            return self._fallback(query, candidates, limit=limit, started=started,
                                  reason=_reason(last_error or RuntimeError("jev_request_failed")),
                                  key_source=key_source, attempts=attempts)
        try:
            scored = [(_score(response, f"candidate_{index}"), index) for index in range(len(candidates))]
        except Exception:
            return self._fallback(query, candidates, limit=limit, started=started,
                                  reason="JEV_RESPONSE_INVALID", key_source=key_source, attempts=attempts)
        ranked = [(candidates[index], score, index) for score, index in scored]
        ranked.sort(key=lambda row: (-float(row[1] or 0), row[2]))
        from .decision import _response
        result = _response(requested_provider=self.mode, effective_provider=self.mode,
                           status="JEV_FAKE_PASS" if self.transport is not None else "JEV_LIVE_PASS",
                           query=query, candidates=candidates, ranked=ranked, limit=limit,
                           started=started, usage=_usage(response), model=_field(response, "model") or self.model,
                           key_source=key_source, question_schema=QUESTION_SCHEMA)
        result.update({"requested_model": self.model, "endpoint": self.endpoint, "attempts": attempts, "fallback_used": False})
        return result
