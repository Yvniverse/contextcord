"""Auditable semantic decisions with a deterministic outer boundary.

The Decision Fabric is intentionally small.  It does not replace the existing
memory store or policy engine: Gate 0 decides whether a semantic call is
warranted, a provider returns typed advisory answers, and this module turns
those answers into a receipt plus code-owned actions.  Integrity, secrets,
permissions, qualification, frozen tests, release gates and destructive
approval never come from Jev.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


QUESTION_SCHEMA_VERSION = "a12-decision-bundle-v1"
RECEIPT_SCHEMA = "contextcord-jev-decision-receipt-v1"
THRESHOLD_POLICY_VERSION = "a12-v1"
DEFAULT_CONFIDENCE_THRESHOLD = 0.72
DEFAULT_RERANK_THRESHOLD = 0.65

QUESTION_SPECS: tuple[dict[str, Any], ...] = (
    {"id": "needs_semantic_rerank", "type": "noul"},
    {"id": "stale_conflict_severity", "type": "score", "levels": ["none", "low", "medium", "high"]},
    {"id": "need_archive_restore", "type": "noul"},
    {"id": "handoff_mode", "type": "choice", "options": ["MINIMAL", "STANDARD", "FORENSIC"]},
    {"id": "expand_retrieval", "type": "noul"},
    {"id": "tool_profile", "type": "choice", "options": ["CONTINUITY_ONLY", "FULL"]},
    {"id": "ask_user", "type": "noul"},
    {"id": "route_recommendation", "type": "choice", "options": ["CURRENT_HOST", "QODER", "CURSOR", "OPENCODE", "WORKBUDDY", "USER_CHOICE"]},
    {"id": "claim_support_check", "type": "noul"},
    {"id": "merge_conflict_class", "type": "choice", "options": ["duplicate", "compatible", "semantic_conflict", "human_review"]},
)

HARD_GATE_FIELDS = (
    "integrity_status",
    "secret_blocker",
    "permission_allowed",
    "qualification_pass",
    "frozen_tests_pass",
    "release_gate_pass",
    "destructive_side_effects_approved",
)


class DecisionProvider(Protocol):
    mode: str

    def decide(self, state: Mapping[str, Any], questions: Sequence[Mapping[str, Any]], *, stage: str) -> Mapping[str, Any]: ...


def _json_default(value: Any) -> str:
    return str(value)


def state_sha256(state: Mapping[str, Any]) -> str:
    """Hash the decision state without retaining it in a receipt."""
    raw = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _bool_signal(value: Any) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return math.isfinite(float(value)) and float(value) >= 0.5
    return bool(value) if not isinstance(value, str) else value.casefold() in {"1", "true", "yes", "y", "high", "present"}


def _nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, result)


def _candidate_margin(state: Mapping[str, Any]) -> float:
    if state.get("relevance_margin") is not None:
        return max(0.0, _finite(state.get("relevance_margin")))
    scores = state.get("candidate_scores")
    if isinstance(scores, Sequence) and not isinstance(scores, (str, bytes)):
        numbers = sorted((_finite(value) for value in scores), reverse=True)
        if len(numbers) >= 2:
            return max(0.0, numbers[0] - numbers[1])
    candidates = state.get("candidates")
    if isinstance(candidates, Sequence) and len(candidates) <= 1:
        return 1.0
    return 0.0


def gate0(state: Mapping[str, Any], *, margin_threshold: float = 0.30) -> dict[str, Any]:
    """Return the deterministic first decision about making a semantic call."""
    candidates = state.get("candidates")
    candidate_count = state.get("candidate_count")
    if candidate_count is None:
        candidate_count = len(candidates) if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes)) else 0
    candidate_count = _nonnegative_int(candidate_count)
    stale_count = _nonnegative_int(state.get("stale_count", 0) or 0)
    hard_tokens = max(0.0, _finite(state.get("hard_relevant_estimated_tokens", 0)))
    budget = max(0.0, _finite(state.get("budget_tokens", 0)))
    semantic_markers = state.get("semantic_conflict_markers") or []
    if isinstance(semantic_markers, (str, bytes)):
        semantic_markers = [semantic_markers]
    reasons: list[str] = []
    if candidate_count > 1 and _candidate_margin(state) < margin_threshold:
        reasons.append("RELEVANCE_AMBIGUITY")
    if stale_count:
        reasons.append("STALE_PRESENT")
    if semantic_markers:
        reasons.append("SEMANTIC_CONFLICT_MARKER")
    if state.get("restore_uncertainty") or state.get("archive_restore_candidates"):
        reasons.append("RESTORE_UNCERTAINTY")
    if state.get("route_uncertainty") or state.get("host_model_uncertain"):
        reasons.append("ROUTE_UNCERTAINTY")
    if budget and hard_tokens > budget:
        reasons.append("BUDGET_PRESSURE")
    if state.get("retrieval_incomplete"):
        reasons.append("RETRIEVAL_INCOMPLETE")
    if state.get("ask_user_risk") or state.get("merge_conflict_uncertain"):
        reasons.append("ESCALATION_UNCERTAINTY")

    obvious_simple = (
        candidate_count <= 1
        or (
            not reasons
            and _candidate_margin(state) >= margin_threshold
            and (not budget or hard_tokens <= budget)
            and not state.get("tool_profile_uncertain")
        )
    )
    if obvious_simple:
        reasons = ["SINGLE_OR_CLEAR_CANDIDATE"] if candidate_count <= 1 else ["CLEAR_DETERMINISTIC_RANK"]
        outcome = "BYPASS_JEV_SIMPLE_CASE"
    else:
        outcome = "REQUEST_JEV_SEMANTIC_JUDGMENT"
    return {
        "outcome": outcome,
        "reason_codes": reasons,
        "signals": {
            "candidate_count": candidate_count,
            "stale_count": stale_count,
            "relevance_margin": round(_candidate_margin(state), 6),
            "budget_tokens": budget,
            "hard_relevant_estimated_tokens": hard_tokens,
            "semantic_marker_count": len(semantic_markers),
        },
        "threshold_policy_version": THRESHOLD_POLICY_VERSION,
    }


def _answer(value: Any, *, kind: str, confidence: float = 0.8, probabilities: Mapping[str, float] | None = None, reason: str = "") -> dict[str, Any]:
    value = value
    probabilities = dict(probabilities or {})
    return {
        "type": kind,
        "value": value,
        "confidence": max(0.0, min(1.0, _finite(confidence, 0.0))),
        "probabilities": probabilities,
        "reason": reason,
    }


def _value(answer: Any, default: Any = None) -> Any:
    if isinstance(answer, Mapping):
        return answer.get("value", answer.get("choice", answer.get("score", answer.get("noul", default))))
    return answer


class DeterministicDecisionProvider:
    """Local, auditable fallback used when no semantic service is available."""

    mode = "deterministic_fallback"

    def decide(self, state: Mapping[str, Any], questions: Sequence[Mapping[str, Any]], *, stage: str) -> Mapping[str, Any]:
        started = time.monotonic()
        stale = _nonnegative_int(state.get("stale_count", 0) or 0)
        candidates = state.get("candidates") or []
        candidate_count = int(state.get("candidate_count", len(candidates) if isinstance(candidates, Sequence) else 0) or 0)
        archive = bool(state.get("archive_restore_candidates") or state.get("archive_only_clue") or state.get("restore_uncertainty"))
        ambiguous = candidate_count > 1 and _candidate_margin(state) < 0.30
        answers: dict[str, Any] = {}
        for question in questions:
            ident = str(question.get("id"))
            kind = str(question.get("type", "noul"))
            if ident == "needs_semantic_rerank":
                answers[ident] = _answer(bool(ambiguous or stale or state.get("retrieval_incomplete")), kind=kind, confidence=0.92, reason="deterministic ambiguity/stale signals")
            elif ident == "stale_conflict_severity":
                level = 3 if state.get("semantic_conflict_markers") else 2 if stale else 0
                answers[ident] = _answer(level, kind=kind, confidence=0.95, probabilities={str(i): 1.0 if i == level else 0.0 for i in range(4)}, reason="hash freshness remains code-owned")
            elif ident == "need_archive_restore":
                answers[ident] = _answer(archive, kind=kind, confidence=0.90, reason="raw archive clue or restore uncertainty")
            elif ident == "handoff_mode":
                mode = "FORENSIC" if stale and archive else "STANDARD" if stale or candidate_count > 3 else "MINIMAL"
                answers[ident] = _answer(mode, kind=kind, confidence=0.86, probabilities={name: (1.0 if name == mode else 0.0) for name in ("MINIMAL", "STANDARD", "FORENSIC")}, reason="bounded mode from freshness and restore risk")
            elif ident == "expand_retrieval":
                answers[ident] = _answer(bool(state.get("retrieval_incomplete") or candidate_count < int(state.get("minimum_candidate_count", 3) or 3)), kind=kind, confidence=0.82, reason="candidate coverage")
            elif ident == "tool_profile":
                profile = "FULL" if state.get("requires_full_tool_profile") else "CONTINUITY_ONLY"
                answers[ident] = _answer(profile, kind=kind, confidence=0.88, reason="least privilege tool profile")
            elif ident == "ask_user":
                risk = bool(state.get("ask_user_risk") or state.get("merge_conflict_uncertain"))
                answers[ident] = _answer(risk, kind=kind, confidence=0.80, reason="human review for high-risk ambiguity")
            elif ident == "route_recommendation":
                answers[ident] = _answer("CURRENT_HOST", kind=kind, confidence=0.90, reason="recommendation cannot switch host")
            elif ident == "claim_support_check":
                answers[ident] = _answer(bool(state.get("evidence_supports_claim", False)), kind=kind, confidence=0.88, reason="only supplied evidence counts")
            elif ident == "memory_relevance":
                scores = state.get("candidate_scores")
                top = max((_finite(item) for item in scores), default=0.0) if isinstance(scores, Sequence) and not isinstance(scores, (str, bytes)) else 0.0
                answers[ident] = _answer(max(0.0, min(1.0, top / 10.0)), kind=kind, confidence=0.82, reason="deterministic lexical score only")
            elif ident == "merge_conflict_class":
                conflict = "human_review" if state.get("merge_conflict_uncertain") else "semantic_conflict" if state.get("semantic_conflict_markers") else "compatible"
                answers[ident] = _answer(conflict, kind=kind, confidence=0.84, reason="portable merge requires explicit classification")
            else:
                answers[ident] = _answer(None, kind=kind, confidence=0.0, reason="unknown question")
        return {
            "status": "DETERMINISTIC_PASS",
            "model": "deterministic-a12-fallback",
            "answers": answers,
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "stage": stage,
        }


def _normalise_answers(raw: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    answers = raw.get("answers") if isinstance(raw, Mapping) else None
    if not isinstance(answers, Mapping):
        answers = raw.get("nouls") if isinstance(raw, Mapping) else {}
    result: dict[str, dict[str, Any]] = {}
    for key, item in (answers or {}).items():
        if isinstance(item, Mapping):
            value = _value(item)
            confidence = item.get("confidence", 0.0)
            probabilities = item.get("probabilities") or {}
            result[str(key)] = {
                "type": item.get("type"),
                "value": value,
                "confidence": max(0.0, min(1.0, _finite(confidence))),
                "probabilities": dict(probabilities) if isinstance(probabilities, Mapping) else {},
                "reason": item.get("reason", ""),
            }
        else:
            result[str(key)] = _answer(item, kind="unknown", confidence=0.0)
    return result


def _code_actions(state: Mapping[str, Any], answers: Mapping[str, Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    actions: list[str] = []
    hard_overrides: list[str] = []
    # These are deliberately boring and explicit.  A semantic provider cannot
    # turn a hard failure into permission or qualification.
    if str(state.get("integrity_status", "PASS")).upper() != "PASS":
        hard_overrides.append("BLOCK_INTEGRITY")
    if _bool_signal(state.get("secret_blocker", False)):
        hard_overrides.append("BLOCK_SECRET")
    if state.get("permission_allowed") is False:
        hard_overrides.append("BLOCK_PERMISSION")
    if state.get("qualification_pass") is False:
        hard_overrides.append("BLOCK_QUALIFICATION")
    if state.get("frozen_tests_pass") is False:
        hard_overrides.append("BLOCK_FROZEN_ORACLE")
    if state.get("release_gate_pass") is False:
        hard_overrides.append("BLOCK_RELEASE_GATE")
    if state.get("destructive_side_effects_approved") is False:
        hard_overrides.append("BLOCK_DESTRUCTIVE_SIDE_EFFECT")
    if _nonnegative_int(state.get("stale_count", 0) or 0) > 0:
        actions.append("REVALIDATE_STALE")
    if _bool_signal(_value(answers.get("need_archive_restore"), False)) and state.get("archive_restore_candidates"):
        actions.append("RESTORE_ARCHIVE")
    if _bool_signal(_value(answers.get("needs_semantic_rerank"), False)):
        actions.append("RERANK_MEMORIES")
    if _bool_signal(_value(answers.get("expand_retrieval"), False)):
        actions.append("EXPAND_RETRIEVAL")
    if _bool_signal(_value(answers.get("ask_user"), False)):
        actions.append("ASK_USER")
    profile = str(_value(answers.get("tool_profile"), "CONTINUITY_ONLY"))
    actions.append("TOOL_PROFILE_" + ("FULL" if profile == "FULL" else "CONTINUITY_ONLY"))
    mode = str(_value(answers.get("handoff_mode"), "STANDARD"))
    actions.append("HANDOFF_MODE_" + (mode if mode in {"MINIMAL", "STANDARD", "FORENSIC"} else "STANDARD"))
    if hard_overrides:
        actions = hard_overrides + ["NO_SEMANTIC_OVERRIDE"]
    return actions, hard_overrides


@dataclass(frozen=True)
class DecisionFabricResult:
    receipt: dict[str, Any]
    selected_memory_ids: tuple[str, ...]


class DecisionFabric:
    def __init__(self, *, provider: DecisionProvider | None = None, provider_name: str = "deterministic", confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD, rerank_threshold: float = DEFAULT_RERANK_THRESHOLD) -> None:
        self.provider = provider or DeterministicDecisionProvider()
        self.provider_name = provider_name
        self.confidence_threshold = confidence_threshold
        self.rerank_threshold = rerank_threshold

    def evaluate(self, state: Mapping[str, Any], *, force: bool = False) -> DecisionFabricResult:
        state = dict(state)
        digest = state_sha256(state)
        first_gate = gate0(state)
        questions = list(QUESTION_SPECS)
        if first_gate["outcome"] == "BYPASS_JEV_SIMPLE_CASE" and not force:
            answers = {
                "needs_semantic_rerank": _answer(False, kind="noul", confidence=0.99, reason="Gate 0 bypass"),
                "need_archive_restore": _answer(False, kind="noul", confidence=0.99, reason="Gate 0 bypass"),
                "handoff_mode": _answer("MINIMAL", kind="choice", confidence=0.99, reason="Gate 0 bypass"),
                "tool_profile": _answer("CONTINUITY_ONLY", kind="choice", confidence=0.99, reason="Gate 0 bypass"),
            }
            actions, hard_overrides = _code_actions(state, answers)
            receipt = self._receipt(state, digest, first_gate, answers, actions, hard_overrides, calls=0, escalated=False, provider_result=None)
            return DecisionFabricResult(receipt, tuple())

        try:
            provider_result = dict(self.provider.decide(state, questions, stage="gate"))
        except Exception as exc:
            # A transient semantic-provider failure is never allowed to block
            # deterministic continuity or turn into an unverified claim.
            provider_result = dict(DeterministicDecisionProvider().decide(state, questions, stage="gate"))
            provider_result.update({
                "status": "FALLBACK",
                "fallback_used": True,
                "fallback_reason": type(exc).__name__,
                "requested_provider": self.provider_name,
                "effective_provider": "deterministic_fallback",
            })
        answers = _normalise_answers(provider_result)
        calls = 1
        escalated = False
        deep_result: dict[str, Any] | None = None
        rerank = answers.get("needs_semantic_rerank", {})
        if _bool_signal(rerank.get("value", False)) and _finite(rerank.get("confidence")) >= self.rerank_threshold:
            deep_questions = [
                {"id": "memory_relevance", "type": "score"},
                {"id": "claim_support_check", "type": "noul"},
                {"id": "merge_conflict_class", "type": "choice", "options": ["duplicate", "compatible", "semantic_conflict", "human_review"]},
            ]
            try:
                deep_result = dict(self.provider.decide(state, deep_questions, stage="deep"))
                deep_answers = _normalise_answers(deep_result)
                answers.update(deep_answers)
                calls += 1
                escalated = True
            except Exception as exc:
                deep_result = {"status": "FALLBACK", "fallback_reason": type(exc).__name__}

        actions, hard_overrides = _code_actions(state, answers)
        selected = tuple(
            str(row.get("memory_id"))
            for row in (state.get("candidates") or [])
            if isinstance(row, Mapping) and row.get("memory_id") and row.get("freshness", "").upper() not in {"STALE", "REVALIDATE"}
        )
        if "RERANK_MEMORIES" not in actions and selected:
            selected = selected[: max(1, _nonnegative_int(state.get("deterministic_limit", len(selected)) or len(selected), len(selected)))]
        receipt = self._receipt(state, digest, first_gate, answers, actions, hard_overrides, calls=calls, escalated=escalated, provider_result=provider_result, deep_result=deep_result)
        return DecisionFabricResult(receipt, selected)

    def select_candidates(
        self,
        state: Mapping[str, Any],
        *,
        query: str,
        limit: int = 4,
        force: bool = False,
    ) -> DecisionFabricResult:
        """Evaluate policy and, when available, perform provider-backed selection.

        This is the production boundary used by Live Benchmark v3.  The
        Decision Fabric receipt is created first.  A Jev-backed provider may
        then rank the bounded candidate projections through its real provider
        path.  A missing/unavailable provider never gets relabelled as a Jev
        selection; callers receive an empty selection and the receipt retains
        the truthful unavailable status.
        """
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("selection_limit_out_of_range")
        result = self.evaluate(state, force=force)
        candidates = [row for row in (state.get("candidates") or []) if isinstance(row, Mapping)]
        if not candidates:
            result.receipt["selection"] = {
                "status": "EMPTY_CANDIDATE_POOL",
                "selected_memory_ids": [],
                "candidate_pool_sha256": None,
            }
            return DecisionFabricResult(result.receipt, tuple())

        jev = result.receipt.get("jev") if isinstance(result.receipt.get("jev"), Mapping) else {}
        provider_available = (
            self.provider_name == "jev_api"
            and jev.get("effective_provider") == "jev_api"
            and not bool(jev.get("fallback_used"))
            and str(jev.get("status", "")).upper() in {"JEV_LIVE_PASS", "JEV_FAKE_PASS"}
        )
        selected_ids: list[str] = []
        selection: dict[str, Any] = {
            "selector": "decision_fabric",
            "provider": self.provider_name,
            "status": "PROVIDER_UNAVAILABLE" if self.provider_name == "jev_api" and not provider_available else "DETERMINISTIC_PASS",
            "selected_memory_ids": selected_ids,
        }
        if provider_available and hasattr(self.provider, "rank"):
            try:
                ranking = self.provider.rank(query, candidates, limit=limit)  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover - defensive provider boundary
                ranking = {"status": "PROVIDER_UNAVAILABLE", "fallback_used": True, "fallback_reason": type(exc).__name__}
            ranking_effective = str(ranking.get("effective_provider", ""))
            if ranking_effective == "jev_api" and not ranking.get("fallback_used"):
                selected_ids = [str(item) for item in ranking.get("selected_memory_ids") or []]
                selection.update(
                    {
                        "status": ranking.get("status", "JEV_LIVE_PASS"),
                        "candidate_pool_sha256": ranking.get("candidate_pool_sha256"),
                        "selected_memory_ids": selected_ids,
                        "usage": ranking.get("usage"),
                        "latency_ms": ranking.get("duration_ms"),
                        "model": ranking.get("model"),
                        "question_schema": ranking.get("question_schema"),
                    }
                )
            else:
                selection.update(
                    {
                        "status": "PROVIDER_UNAVAILABLE",
                        "fallback_reason": ranking.get("fallback_reason") or "provider_fallback",
                        "candidate_pool_sha256": ranking.get("candidate_pool_sha256"),
                    }
                )
        elif self.provider_name == "jev_api":
            selection["fallback_reason"] = jev.get("fallback_reason") or "provider_unavailable"
        else:
            selected_ids = [
                str(row.get("memory_id"))
                for row in candidates
                if row.get("memory_id") and str(row.get("freshness", "")).upper() not in {"STALE", "REVALIDATE", "STALE_REVALIDATE"}
            ][:limit]
            selection["selected_memory_ids"] = selected_ids

        result.receipt["selection"] = selection
        return DecisionFabricResult(result.receipt, tuple(selected_ids))

    def _receipt(self, state: Mapping[str, Any], digest: str, gate: Mapping[str, Any], answers: Mapping[str, Any], actions: Sequence[str], hard_overrides: Sequence[str], *, calls: int, escalated: bool, provider_result: Mapping[str, Any] | None, deep_result: Mapping[str, Any] | None = None) -> dict[str, Any]:
        jev_data: dict[str, Any] = {
            "provider": self.provider_name,
            "effective_provider": (provider_result or {}).get("effective_provider", self.provider_name),
            "model": (provider_result or {}).get("model"),
            "question_schema_version": QUESTION_SCHEMA_VERSION,
            "answers": dict(answers),
            "usage": (provider_result or {}).get("usage"),
            "latency_ms": (provider_result or {}).get("latency_ms"),
            "status": (provider_result or {}).get("status", "BYPASSED" if calls == 0 else "UNKNOWN"),
            "fallback_used": bool((provider_result or {}).get("fallback_used", False)),
            "fallback_reason": (provider_result or {}).get("fallback_reason"),
        }
        if deep_result is not None:
            jev_data["deep_stage"] = {
                "status": deep_result.get("status"),
                "model": deep_result.get("model"),
                "usage": deep_result.get("usage"),
                "latency_ms": deep_result.get("latency_ms"),
                "fallback_reason": deep_result.get("fallback_reason"),
            }
        return {
            "schema": RECEIPT_SCHEMA,
            "state_sha256": digest,
            "gate0": dict(gate),
            "jev": jev_data,
            "threshold_policy_version": THRESHOLD_POLICY_VERSION,
            "thresholds": {"confidence_auto": self.confidence_threshold, "deep_rerank": self.rerank_threshold},
            "code_actions": list(actions),
            "hard_gate_overrides": list(hard_overrides),
            "escalated_second_stage": bool(escalated),
            "provider_calls": calls,
            "truth_boundary": "Jev is advisory; code owns integrity, secrets, permissions, qualification, frozen tests, release gates and destructive side effects.",
        }


def make_provider(name: str = "deterministic", *, project_root: str | None = None, model: str | None = None, endpoint: str | None = None) -> DecisionProvider:
    name = str(name).casefold()
    if name in {"deterministic", "heuristic", "fallback", "disabled"}:
        return DeterministicDecisionProvider()
    if name == "jev_api":
        from .jev_provider import JevApiDecisionProvider

        return JevApiDecisionProvider(project_root=project_root, model=model, endpoint=endpoint)
    raise ValueError(f"unknown_decision_fabric_provider:{name}")


def evaluate_decision_fabric(state: Mapping[str, Any], *, provider: str = "deterministic", project_root: str | None = None, model: str | None = None, endpoint: str | None = None, force: bool = False) -> dict[str, Any]:
    """Convenience API used by CLI, Assisted Handoff and experiments."""
    engine = DecisionFabric(provider=make_provider(provider, project_root=project_root, model=model, endpoint=endpoint), provider_name=provider)
    return engine.evaluate(state, force=force).receipt


__all__ = [
    "DecisionFabric",
    "DecisionFabricResult",
    "DeterministicDecisionProvider",
    "QUESTION_SCHEMA_VERSION",
    "QUESTION_SPECS",
    "RECEIPT_SCHEMA",
    "gate0",
    "state_sha256",
    "evaluate_decision_fabric",
]
