"""Assisted Handoff: one bounded preview/confirm flow over live local state.

The default path stays inside Continuum/Context Engine and uses deterministic
local selection.  An explicitly requested semantic provider is an optional
lazy strategy; it never becomes a hard import or a requirement for continuity.
This facade does not create a second memory store, sync to a cloud, or mutate
host configuration.  Preview is read-only; confirmation creates one new local
session and one archived context job.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import HarnessConfig
from .identity import source_identity
from .memory import memory_context
from .store import StateStore
from .util import utc_now


TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
HANDOFF_SCHEMA = "agent-nexus-assisted-handoff-v1"


@dataclass(frozen=True)
class _HandoffDecision:
    receipt: dict[str, Any]
    selected_memory_ids: tuple[str, ...]


def _tokens(value: Any) -> set[str]:
    return set(TOKEN_RE.findall(str(value or "").casefold()))


def _bounded(value: Any, limit: int = 2048) -> str:
    return str(value or "").strip()[:limit]


def _freshness(dependency_status: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(row.get("status", "")).upper() for row in dependency_status}
    if "STALE" in statuses or "MISSING" in statuses:
        return "STALE"
    if statuses and statuses <= {"UNCHANGED"}:
        return "FRESH"
    return "UNVERIFIED"


def _last_activity(context: Mapping[str, Any], *, host: str | None) -> dict[str, Any]:
    sessions = list(context.get("sessions") or [])
    jobs = list(context.get("context_jobs") or [])
    last_session = sessions[-1] if sessions else None
    last_job = jobs[-1] if jobs else None
    summary: Any = {}
    if last_session:
        raw = last_session.get("summary_json")
        if isinstance(raw, str):
            try:
                summary = json.loads(raw)
            except (TypeError, ValueError):
                summary = {"summary": _bounded(raw, 512)}
        elif isinstance(raw, Mapping):
            summary = dict(raw)
    return {
        "host": host or (last_job or {}).get("provider") or "CURRENT_HOST",
        "session_id": (last_session or {}).get("session_id"),
        "session_status": (last_session or {}).get("status"),
        "closed_at": (last_session or {}).get("closed_at"),
        "last_context_job_id": (last_job or {}).get("job_id"),
        "last_provider": (last_job or {}).get("provider"),
        "summary": summary,
    }


def _candidate_rows(context: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    archive_refs: list[str] = []
    for note in context.get("notes") or []:
        dependencies = list(note.get("dependency_status") or [])
        freshness = _freshness(dependencies)
        rows.append({
            "memory_id": str(note.get("note_id")),
            "kind": "note",
            "summary": _bounded(note.get("text"), 1600),
            "text": _bounded(note.get("text"), 2400),
            "freshness": freshness,
            "authoritative": freshness == "FRESH" or not dependencies,
            "dependency_status": dependencies,
            "source_session_id": note.get("session_id"),
        })
    for job in context.get("context_jobs") or []:
        job_id = str(job.get("job_id"))
        packet = job.get("packet") if isinstance(job.get("packet"), Mapping) else {}
        summary = packet.get("next_action") or packet.get("summary") or packet.get("task_prompt") or job.get("provider")
        rows.append({
            "memory_id": job_id,
            "kind": "context_job",
            "summary": _bounded(summary, 1600),
            "text": _bounded(packet.get("context") or summary, 2400),
            "freshness": "HISTORICAL",
            "authoritative": False,
            "dependency_status": [],
            "source_session_id": job.get("session_id"),
        })
        archive_refs.append(job_id)
    for evidence in context.get("evidence") or []:
        evidence_id = str(evidence.get("portable_id") or evidence.get("evidence_id") or evidence.get("name"))
        if not evidence_id or evidence_id == "None":
            continue
        rows.append({
            "memory_id": "evidence:" + evidence_id,
            "kind": "evidence",
            "summary": _bounded(evidence.get("name"), 512),
            "text": _bounded(evidence.get("reason") or evidence.get("name"), 1200),
            "freshness": str(evidence.get("current_qualification") or "UNVERIFIED").upper(),
            "authoritative": str(evidence.get("classification", "CURRENT")).upper() == "CURRENT" and str(evidence.get("current_qualification", "")).upper() == "PASS",
            "dependency_status": [],
            "source_session_id": evidence.get("session_id"),
        })
    return rows, archive_refs


def _deterministic_scores(query: str, candidates: Sequence[Mapping[str, Any]]) -> list[float]:
    query_tokens = _tokens(query)
    values: list[float] = []
    for candidate in candidates:
        text = " ".join(str(candidate.get(key, "")) for key in ("summary", "text", "next_action"))
        overlap = len(query_tokens & _tokens(text))
        freshness_bonus = 0.05 if str(candidate.get("freshness", "")).upper() == "FRESH" else 0.0
        values.append(float(overlap) + freshness_bonus)
    return values


def _state_sha256(state: Mapping[str, Any]) -> str:
    raw = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _deterministic_handoff_decision(
    state: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    scores: Sequence[float],
) -> _HandoffDecision:
    """Select fresh local context without importing the Decision Plane.

    This is the Continuum selection boundary, not a second Decision Fabric:
    Handoff already owns the lexical scores and only needs a stable, bounded
    set of fresh candidates for its local packet.  Semantic decisions remain
    delegated to the lazy strategy below when explicitly requested.
    """

    ranked = sorted(
        zip(scores, candidates),
        key=lambda item: (-float(item[0]), str(item[1].get("memory_id") or "")),
    )
    fresh = [
        row
        for _, row in ranked
        if str(row.get("freshness", "")).upper() not in {"STALE", "REVALIDATE", "STALE_REVALIDATE"}
    ]
    selected = [
        str(row.get("memory_id"))
        for row in fresh
        if row.get("memory_id") and row.get("authoritative")
    ][:3]
    if not selected:
        selected = [str(row.get("memory_id")) for row in fresh if row.get("memory_id")][:3]

    hard_overrides: list[str] = []
    if str(state.get("integrity_status", "PASS")).upper() != "PASS":
        hard_overrides.append("BLOCK_INTEGRITY")
    if state.get("permission_allowed") is False:
        hard_overrides.append("BLOCK_PERMISSION")
    actions = ["TOOL_PROFILE_CONTINUITY_ONLY", "HANDOFF_MODE_STANDARD"]
    if any(str(row.get("freshness", "")).upper() in {"STALE", "REVALIDATE"} for row in candidates):
        actions.insert(0, "REVALIDATE_STALE")
    if hard_overrides:
        actions = hard_overrides + ["NO_SEMANTIC_OVERRIDE"]

    receipt = {
        "schema": "agent-nexus-jev-decision-receipt-v1",
        "state_sha256": _state_sha256(state),
        "gate0": {
            "outcome": "BYPASS_JEV_DETERMINISTIC_HANDOFF",
            "reason_codes": ["continuity_default_path"],
        },
        "jev": {
            "provider": "deterministic",
            "effective_provider": "deterministic_continuity",
            "model": None,
            "status": "BYPASSED",
            "fallback_used": False,
            "fallback_reason": None,
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "latency_ms": 0,
        },
        "threshold_policy_version": "continuum-handoff-v1",
        "thresholds": {"selection_limit": 3},
        "code_actions": actions,
        "hard_gate_overrides": hard_overrides,
        "escalated_second_stage": False,
        "provider_calls": 0,
        "selection": {
            "selector": "continuum_deterministic",
            "provider": "deterministic",
            "status": "DETERMINISTIC_PASS",
            "selected_memory_ids": selected,
        },
        "truth_boundary": "Continuum selects bounded local context; semantic advice, permissions and side effects remain outside this default path.",
    }
    return _HandoffDecision(receipt, tuple(selected))


def _handoff_decision(
    cfg: HarnessConfig,
    provider: str,
    state: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    scores: Sequence[float],
) -> _HandoffDecision:
    """Resolve the default local strategy or a user-requested enhancement.

    The import boundary is intentionally inside the explicit non-deterministic
    branch.  A deterministic preview/confirm therefore remains usable when
    Decision Plane and Jev are absent or unavailable.
    """

    normalized = str(provider or "deterministic").casefold()
    if normalized in {"deterministic", "heuristic", "fallback", "disabled"}:
        return _deterministic_handoff_decision(state, candidates, scores)
    from .decision_fabric import DecisionFabric, make_provider

    result = DecisionFabric(
        provider=make_provider(provider, project_root=str(cfg.repo)),
        provider_name=provider,
    ).evaluate(state)
    return _HandoffDecision(result.receipt, tuple(result.selected_memory_ids))


def _state_for_fabric(task: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]], scores: Sequence[float], *, archive_refs: Sequence[str], host: str | None) -> dict[str, Any]:
    sorted_scores = sorted((float(value) for value in scores), reverse=True)
    margin = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else 1.0
    stale = sum(1 for row in candidates if str(row.get("freshness", "")).upper() in {"STALE", "REVALIDATE"})
    return {
        "task_id": task.get("task_id"),
        "task_prompt": _bounded(task.get("next_action") or task.get("scope"), 2048),
        "next_action": _bounded(task.get("next_action"), 2048),
        "host": host or "CURRENT_HOST",
        "candidate_count": len(candidates),
        "candidates": list(candidates),
        "candidate_scores": list(scores),
        "relevance_margin": margin,
        "stale_count": stale,
        "archive_restore_candidates": list(archive_refs),
        "restore_uncertainty": bool(archive_refs),
        "budget_tokens": 3072,
        "hard_relevant_estimated_tokens": sum(len(str(row.get("text", ""))) // 4 for row in candidates),
        "minimum_candidate_count": 3,
        "permission_allowed": True,
        "secret_blocker": False,
        "integrity_status": "PASS",
        "handoff_mode_requested": True,
    }


def _continuation(task: Mapping[str, Any], identity: Mapping[str, Any], activity: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]], selected_ids: Sequence[str], receipt: Mapping[str, Any], *, host: str | None) -> dict[str, Any]:
    selected = [row for row in candidates if str(row.get("memory_id")) in set(selected_ids)]
    if not selected:
        selected = [row for row in candidates if row.get("authoritative")][:3]
    archive_refs = [str(row["memory_id"]) for row in candidates if row.get("kind") == "context_job"]
    source = {
        "identity_sha256": identity.get("identity_sha256"),
        "git_commit": identity.get("git_commit"),
        "truth_fingerprint_sha256": (identity.get("truth_fingerprint") or {}).get("sha256"),
        "policy_fingerprint_sha256": (identity.get("policy_fingerprint") or {}).get("sha256"),
    }
    return {
        "schema": HANDOFF_SCHEMA,
        "created_at": utc_now(),
        "task": {"task_id": task.get("task_id"), "scope": task.get("scope"), "next_action": task.get("next_action"), "status": task.get("status")},
        "last_activity": dict(activity),
        "target_host": host or activity.get("host") or "CURRENT_HOST",
        "source_identity": source,
        "freshness": {
            "selected_authoritative": sum(1 for row in selected if row.get("authoritative")),
            "selected_stale_or_historical": sum(1 for row in selected if not row.get("authoritative")),
            "revalidation_required": [row.get("memory_id") for row in candidates if str(row.get("freshness", "")).upper() in {"STALE", "REVALIDATE"}],
        },
        "selected_memory": [
            {"memory_id": row.get("memory_id"), "kind": row.get("kind"), "summary": row.get("summary"), "text": row.get("text"), "freshness": row.get("freshness"), "authoritative": bool(row.get("authoritative"))}
            for row in selected
        ],
        "archive_refs": archive_refs,
        "decision_receipt": dict(receipt),
        "confirmation": {"required": True, "scope": "create one local session and archive one local context job"},
    }


def assist_resume(cfg: HarnessConfig, *, task_id: str | None = None, host: str | None = None,
                  provider: str = "deterministic", confirm: bool = False,
                  session_id: str | None = None) -> dict[str, Any]:
    """Preview or confirm one Assisted Handoff.  Preview performs no writes."""
    context = memory_context(cfg, task_id=task_id)
    if task_id is None:
        tasks = list(context.get("tasks") or [])
        if len(tasks) != 1:
            return {
                "status": "SELECT_TASK" if tasks else "NO_UNFINISHED_TASK",
                "requires_confirmation": False,
                "tasks": [{"task_id": row.get("task_id"), "scope": row.get("scope"), "next_action": row.get("next_action")} for row in tasks],
            }
        task_id = str(tasks[0]["task_id"])
        context = memory_context(cfg, task_id=task_id)
    task = context.get("task")
    if not isinstance(task, Mapping) or str(task.get("status", "")).upper() not in {"ACTIVE", "READY_TO_FINISH"}:
        return {"status": "NO_UNFINISHED_TASK", "task_id": task_id, "requires_confirmation": False}

    candidates, archive_refs = _candidate_rows(context)
    query = str(task.get("next_action") or task.get("scope") or "continue task")
    scores = _deterministic_scores(query, candidates)
    state = _state_for_fabric(task, candidates, scores, archive_refs=archive_refs, host=host)
    identity = source_identity(cfg, include_files=False)
    result = _handoff_decision(cfg, provider, state, candidates, scores)
    selected_ids = list(result.selected_memory_ids)
    if not selected_ids:
        ranked = sorted(zip(scores, candidates), key=lambda row: (-row[0], str(row[1].get("memory_id"))))
        selected_ids = [str(row.get("memory_id")) for score, row in ranked if row.get("authoritative")][:3]
    activity = _last_activity(context, host=host)
    continuation = _continuation(task, identity, activity, candidates, selected_ids, result.receipt, host=host)
    preview = {
        "status": "AWAITING_CONFIRMATION",
        "requires_confirmation": True,
        "task_id": task_id,
        "last_host": activity.get("host"),
        "last_session_id": activity.get("session_id"),
        "decision_receipt": result.receipt,
        "continuation": continuation,
        "confirmation_message": "Review the bounded continuation and call again with --yes to create one local session.",
    }
    if not confirm:
        return preview

    open_sessions = []
    with StateStore(cfg.repo) as store:
        open_sessions = store.open_sessions(str(task_id))
    if open_sessions:
        preview.update({"status": "OPEN_SESSION_EXISTS", "requires_confirmation": True, "open_sessions": [{"session_id": row.get("session_id"), "started_at": row.get("started_at")} for row in open_sessions]})
        return preview

    with StateStore(cfg.repo) as store, store.transaction():
        new_session_id = store.create_session(
            task_id=str(task_id), scope=str(task.get("scope") or "default"), head=str(identity.get("git_commit") or "UNKNOWN"),
            fingerprint=str((identity.get("truth_fingerprint") or {}).get("sha256") or "UNKNOWN"),
            policy_fingerprint=str((identity.get("policy_fingerprint") or {}).get("sha256") or "UNKNOWN"),
            source_identity_sha256=str(identity.get("identity_sha256") or "UNKNOWN"), session_id=session_id,
        )
        job_id = store.create_context_job(
            task_id=str(task_id), provider=str(host or activity.get("host") or "assisted_handoff"), packet=continuation,
            session_id=new_session_id, archive_refs=list(continuation.get("archive_refs") or []),
            source_identity_sha256=str(identity.get("identity_sha256") or "UNKNOWN"),
        )
        store.event("ASSISTED_HANDOFF_CONFIRMED", {
            "job_id": job_id, "decision_state_sha256": result.receipt.get("state_sha256"),
            "target_host": continuation.get("target_host"), "selected_memory_ids": selected_ids,
        }, session_id=new_session_id, task_id=str(task_id))
    return {
        **preview,
        "status": "PASS",
        "requires_confirmation": False,
        "session_id": new_session_id,
        "context_job_id": job_id,
        "machine_receipt": {
            "schema": "agent-nexus-assisted-handoff-receipt-v1",
            "task_id": task_id,
            "session_id": new_session_id,
            "context_job_id": job_id,
            "decision_state_sha256": result.receipt.get("state_sha256"),
            "source_identity_sha256": identity.get("identity_sha256"),
        },
    }


__all__ = ["HANDOFF_SCHEMA", "assist_resume"]
