"""Deterministic Jev subagent-router eligibility and shadow receipts.

The router never executes a host or accepts an arbitrary model identifier from
Jev.  It builds a closed eligible set first, then records a typed shadow
decision.  Credentials, permissions and budgets remain host/policy-owned.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping


ROLES = ("explorer", "implementer", "reviewer")
MODEL_TIERS = ("lite", "standard", "reasoning", "inherit")
EXPLICIT_MODELS = ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol")
EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
EFFORT_RANK = {name: index for index, name in enumerate(EFFORTS)}
MODEL_PRICE_RANK = {name: index for index, name in enumerate(EXPLICIT_MODELS)}
MAX_EXECUTION_ATTEMPTS = 2
MAX_CALIBRATION_CALLS = 6
MAX_SOL_MAX_RUNS = 1


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _as_bool(value: Any) -> bool:
    return value is True or str(value).casefold() in {"1", "true", "yes", "pass", "available", "logged_in"}


def _host_models(host: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    models = host.get("models", [])
    if isinstance(models, Mapping):
        return [{"id": str(key), **(value if isinstance(value, Mapping) else {})} for key, value in models.items()]
    return [row for row in models if isinstance(row, Mapping)] if isinstance(models, list) else []


def _codex_model_allowed(model: Mapping[str, Any]) -> bool:
    """Accept only an explicit observed GPT-5.6 model for Codex routing."""

    model_id = str(model.get("id") or "").strip().casefold()
    if model_id not in EXPLICIT_MODELS:
        return False
    return not any(_as_bool(model.get(key)) for key in ("fallback", "is_fallback", "fallback_used"))


def route_id(host: str, model: str, effort: str, role: str) -> str:
    """Return the canonical v2 route identity."""

    return f"{host}:{model}:{effort}:{role}"


def build_eligible_set(task: Mapping[str, Any]) -> dict[str, Any]:
    required_boundary = str(task.get("data_boundary") or "local")
    required_tools = {str(x) for x in task.get("required_tools", []) if str(x)}
    requested_role = str(task.get("requested_role") or "").casefold()
    requested_tier = str(task.get("requested_model_tier") or "inherit").casefold()
    budget = float(task.get("budget") or 0)
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    hosts = task.get("hosts", [])
    if isinstance(hosts, Mapping):
        hosts = [{"id": key, **(value if isinstance(value, Mapping) else {})} for key, value in hosts.items()]
    for raw_host in hosts if isinstance(hosts, list) else []:
        if not isinstance(raw_host, Mapping):
            continue
        host_id = str(raw_host.get("id") or "unknown")
        reasons: list[str] = []
        if not _as_bool(raw_host.get("available", True)):
            reasons.append("host_unavailable")
        if not _as_bool(raw_host.get("logged_in", raw_host.get("login", True))):
            reasons.append("login_unavailable")
        boundaries = {str(x) for x in raw_host.get("data_boundaries", ["local"])}
        if required_boundary not in boundaries and "any" not in boundaries:
            reasons.append("data_boundary_mismatch")
        tools = {str(x) for x in raw_host.get("tools", [])}
        if not required_tools.issubset(tools):
            reasons.append("tool_permission_missing")
        if float(raw_host.get("budget_remaining", float("inf"))) < budget:
            reasons.append("budget_insufficient")
        models = _host_models(raw_host)
        if not models:
            reasons.append("no_installed_models")
        codex_scope = host_id.casefold() == "codex" or _as_bool(task.get("codex_only"))
        if codex_scope:
            models = [model for model in models if _codex_model_allowed(model)]
            if not models:
                reasons.append("codex_requires_observed_gpt56_non_fallback_model")
        if reasons:
            rejected.append({"host_id": host_id, "reasons": sorted(set(reasons))})
            continue
        seen_model_ids: set[str] = set()
        for raw_model in models:
            model_id = str(raw_model.get("id") or "unknown")
            if model_id in seen_model_ids:
                continue
            seen_model_ids.add(model_id)
            tier = str(raw_model.get("tier") or "standard").casefold()
            if requested_tier not in {"", "inherit"} and tier != requested_tier:
                continue
            for role in ROLES:
                if requested_role and requested_role != role:
                    continue
                if not _as_bool(raw_model.get("supports_roles", True)):
                    continue
                rows.append({"id": f"{host_id}:{model_id}:{role}", "host_id": host_id, "model_id": model_id, "role": role, "model_tier": tier})
    rows.sort(key=lambda row: row["id"])
    return {
        "schema": "contextcord-eligible-set-v1",
        "eligible": rows,
        "eligible_ids": [row["id"] for row in rows],
        "rejected_hosts": sorted(rejected, key=lambda row: row["host_id"]),
        "eligible_set_sha256": _sha([row["id"] for row in rows]),
    }


def shadow_route(task: Mapping[str, Any]) -> dict[str, Any]:
    eligible = build_eligible_set(task)
    requested = {
        "role": str(task.get("requested_role") or "inherit"),
        "model_tier": str(task.get("requested_model_tier") or "inherit"),
        "context_profile": str(task.get("context_profile") or "bounded"),
    }
    requested_id = task.get("requested_id")
    if requested_id is not None and str(requested_id) in eligible["eligible_ids"]:
        choice = {"kind": "Choice", "value": str(requested_id)}
    elif eligible["eligible"]:
        # Shadow mode records the deterministic candidate without granting
        # permission to execute it.
        choice = {"kind": "Choice", "value": eligible["eligible_ids"][0]}
    else:
        choice = {"kind": "Noul", "value": "NO_ELIGIBLE_ROUTE"}
    observed = task.get("observed") if isinstance(task.get("observed"), Mapping) else {}
    observed_id = observed.get("route_id")
    effective = observed_id if observed_id in eligible["eligible_ids"] else "unknown"
    receipt = {
        "schema": "contextcord-subagent-routing-shadow-v1",
        "mode": "SHADOW",
        "executed": False,
        "requested": requested,
        "eligible_set": eligible,
        "decision": choice,
        "scores": [{"kind": "Score", "name": "eligible_count", "value": len(eligible["eligible"]) }],
        "parallel": {"kind": "Noul", "value": bool(task.get("should_parallelize")) if "should_parallelize" in task else None},
        "independent_review": {"kind": "Noul", "value": bool(task.get("needs_independent_review")) if "needs_independent_review" in task else None},
        "requested_role": requested["role"],
        "requested_model_tier": requested["model_tier"],
        "effective_observed_route": effective,
        "effective_observed_role": observed.get("role") if effective != "unknown" else "unknown",
        "effective_observed_model": observed.get("model_id") if effective != "unknown" else "unknown",
        "jev_usage": None,
        "host_usage": observed.get("usage") if effective != "unknown" else None,
        "errors": sorted(str(x) for x in task.get("errors", []) if str(x)),
        "truth_boundary": "Shadow-only typed choice. No credential, permission, budget override or host execution authority is granted.",
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def _beta_estimate(
    *,
    external_mean: float | None,
    external_task_count: int,
    local_successes: int,
    local_failures: int,
    max_external_strength: float = 8.0,
) -> tuple[float, float]:
    """Return a posterior mean and conservative lower estimate.

    External observations are capped because their task distribution differs
    from the local repository.  Local outcomes remain the dominant signal as
    they accumulate.
    """

    external_strength = 0.0
    if external_mean is not None and 0 <= external_mean <= 1 and external_task_count > 0:
        external_strength = min(
            max_external_strength,
            max_external_strength * external_task_count / (external_task_count + 30.0),
        )
    alpha = 2.0 + max(0, local_successes)
    beta = 2.0 + max(0, local_failures)
    if external_strength:
        alpha += external_strength * float(external_mean)
        beta += external_strength * (1.0 - float(external_mean))
    total = alpha + beta
    mean = alpha / total
    variance = (alpha * beta) / (total * total * (total + 1.0))
    lower = max(0.0, mean - math.sqrt(max(0.0, variance)))
    return mean, lower


def _cost_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    """Compare separate cost units without pretending they are one currency."""

    quota = candidate.get("estimated_quota_pct")
    if isinstance(quota, (int, float)) and not isinstance(quota, bool):
        return (0, float(quota), candidate.get("latency_minutes") or float("inf"))
    api_cost = candidate.get("api_equivalent_cost_usd")
    if isinstance(api_cost, (int, float)) and not isinstance(api_cost, bool):
        return (1, float(api_cost), candidate.get("latency_minutes") or float("inf"))
    return (
        2,
        MODEL_PRICE_RANK.get(str(candidate["model_id"]), 99),
        EFFORT_RANK.get(str(candidate["reasoning_effort"]), 99),
    )


def build_shortlist(
    *,
    role: str,
    risk: int,
    available_routes: list[Mapping[str, Any]],
    external_routes: Mapping[tuple[str, str], Mapping[str, Any]],
    local_routes: Mapping[tuple[str, str, str], Mapping[str, Any]],
    allow_sol_max_calibration: bool = False,
    max_external_strength: float = 8.0,
) -> dict[str, Any]:
    """Build a deterministic near-best-quality/minimum-cost shortlist."""

    role = str(role).casefold()
    if role not in ROLES:
        role = "implementer"
    risk = max(1, min(5, int(risk)))
    regret = {"explorer": 0.10, "implementer": 0.06, "reviewer": 0.035}.get(role, 0.06)
    if risk >= 4:
        regret = min(regret, 0.02)

    scored: list[dict[str, Any]] = []
    for raw in available_routes:
        model = str(raw.get("model_id") or "")
        effort = str(raw.get("reasoning_effort") or "").casefold()
        host = str(raw.get("host_id") or raw.get("host") or "codex").casefold()
        if host != "codex" or model not in EXPLICIT_MODELS or effort not in EFFORTS:
            continue
        if raw.get("fallback") is True or raw.get("fallback_used") is True:
            continue
        if model == "gpt-5.6-sol" and effort == "max" and risk < 4 and not allow_sol_max_calibration:
            continue
        ext = external_routes.get((model, effort), {})
        loc = local_routes.get((model, effort, role), {})
        ext_mean = ext.get("task_equal_pass_rate")
        ext_mean = float(ext_mean) if isinstance(ext_mean, (int, float)) else None
        ext_count = int(ext.get("task_count") or 0)
        local_successes = int(loc.get("successes") or 0)
        local_failures = int(loc.get("failures") or 0)
        quality_mean, quality_conservative = _beta_estimate(
            external_mean=ext_mean,
            external_task_count=ext_count,
            local_successes=local_successes,
            local_failures=local_failures,
            max_external_strength=max_external_strength,
        )
        if isinstance(ext.get("median_estimated_quota_pct"), (int, float)) and not isinstance(ext.get("median_estimated_quota_pct"), bool):
            cost_basis = "median_estimated_quota_pct"
        elif isinstance(ext.get("median_api_equivalent_cost_usd"), (int, float)) and not isinstance(ext.get("median_api_equivalent_cost_usd"), bool):
            cost_basis = "median_api_equivalent_cost_usd"
        else:
            cost_basis = "explicit_model_effort_order"
        scored.append({
            "route_id": route_id("codex", model, effort, role),
            "model_id": model,
            "reasoning_effort": effort,
            "role": role,
            "quality_mean": quality_mean,
            "quality_conservative": quality_conservative,
            "local_successes": local_successes,
            "local_failures": local_failures,
            "external_task_count": ext_count,
            "estimated_quota_pct": ext.get("median_estimated_quota_pct"),
            "api_equivalent_cost_usd": ext.get("median_api_equivalent_cost_usd"),
            "latency_minutes": ext.get("median_duration_minutes"),
            "cost_basis": cost_basis,
        })

    if not scored:
        return {
            "status": "NO_ELIGIBLE_ROUTE",
            "role": role,
            "risk": risk,
            "shortlist": [],
            "eligible_route_ids": [],
            "recommended_route_id": None,
            "quality_regret_tolerance": regret,
        }

    best_quality = max(row["quality_conservative"] for row in scored)
    near_best = [row for row in scored if row["quality_conservative"] >= best_quality - regret]
    near_best.sort(key=_cost_key)
    shortlist = near_best[:4]
    return {
        "status": "SHORTLIST_READY",
        "role": role,
        "risk": risk,
        "quality_regret_tolerance": regret,
        "best_conservative_quality": best_quality,
        "shortlist": shortlist,
        "eligible_route_ids": [row["route_id"] for row in shortlist],
        "recommended_route_id": shortlist[0]["route_id"] if shortlist else None,
        "truth_boundary": (
            "External benchmark data is an advisory prior. Local outcome evidence "
            "updates the estimate; Jev may choose only from this closed shortlist."
        ),
    }


def _catalog_source_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        value = value.get("routes", [])
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _catalog_row(
    raw: Mapping[str, Any],
    *,
    availability_source: str,
    execution_eligible: str | bool,
) -> dict[str, Any] | None:
    model = str(raw.get("model_id") or raw.get("model") or "").strip().casefold()
    effort = str(raw.get("reasoning_effort") or raw.get("effort") or "").strip().casefold()
    host = str(raw.get("host_id") or raw.get("host") or "codex").strip().casefold()
    if host != "codex" or model not in EXPLICIT_MODELS or effort not in EFFORTS:
        return None
    tools = raw.get("tools", [])
    boundaries = raw.get("data_boundaries", ["local"])
    return {
        **dict(raw),
        "host_id": host,
        "model_id": model,
        "reasoning_effort": effort,
        "available": raw.get("available", raw.get("provider_available", True)),
        "logged_in": raw.get("logged_in", raw.get("authenticated", True)),
        "execution_eligible": raw.get("execution_eligible", execution_eligible),
        "availability_source": raw.get("availability_source", availability_source),
        "tools": [str(item) for item in tools] if isinstance(tools, (list, tuple, set)) else [],
        "data_boundaries": [str(item) for item in boundaries] if isinstance(boundaries, (list, tuple, set)) else ["local"],
    }


def _catalog_sort_key(row: Mapping[str, Any]) -> tuple[int, int, str]:
    return (
        MODEL_PRICE_RANK.get(str(row.get("model_id")), 99),
        EFFORT_RANK.get(str(row.get("reasoning_effort")), 99),
        str(row.get("route_id") or ""),
    )


def discover_analysis_routes(
    task: Mapping[str, Any] | None = None,
    *,
    snapshot: Mapping[str, Any] | None = None,
    official_models: tuple[str, ...] = EXPLICIT_MODELS,
) -> list[dict[str, Any]]:
    """Build the advisory analysis Catalog without granting execution authority."""

    task = task if isinstance(task, Mapping) else {}
    official = {str(model).casefold() for model in official_models}
    prior = snapshot
    if prior is None and isinstance(task.get("codexradar_prior"), Mapping):
        prior = task.get("codexradar_prior")
    if isinstance(task.get("analysis_routes"), (list, Mapping)):
        source = task.get("analysis_routes")
        source_name = "runtime_analysis_catalog"
    elif "available_routes" in task:
        source = task.get("available_routes")
        source_name = "runtime_declared_catalog"
    elif prior is not None:
        source = prior
        source_name = "external_analysis_catalog"
    else:
        source = task.get("official_routes")
        source_name = "official_capability_catalog"

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in _catalog_source_rows(source):
        row = _catalog_row(raw, availability_source=source_name, execution_eligible="unknown")
        if row is None or row["model_id"] not in official:
            continue
        key = (row["model_id"], row["reasoning_effort"])
        rows.setdefault(key, row)
    if not rows:
        for model in EXPLICIT_MODELS:
            if model not in official:
                continue
            for effort in EFFORTS:
                row = _catalog_row(
                    {"model_id": model, "reasoning_effort": effort},
                    availability_source=source_name,
                    execution_eligible="unknown",
                )
                if row is not None:
                    rows[(model, effort)] = row
    return sorted(rows.values(), key=_catalog_sort_key)


def discover_execution_routes(observed_routes: Any) -> list[dict[str, Any]]:
    """Return only explicitly observed, non-fallback host capabilities."""

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in _catalog_source_rows(observed_routes):
        capability_state = str(raw.get("capability_state") or "").upper()
        confirmed = raw.get("real_identity_observed") is True or capability_state == "CONFIRMED"
        configured_explicit = capability_state == "CONFIGURED_EXPLICIT" and str(raw.get("identity_evidence") or "") == "configured_explicit"
        if not confirmed and not configured_explicit:
            continue
        if raw.get("available") is not True or raw.get("logged_in") is not True:
            continue
        if raw.get("fallback") is True or raw.get("fallback_used") is True or raw.get("fallback_observed") is True:
            continue
        row = _catalog_row(raw, availability_source="host_observed", execution_eligible=True)
        if row is None:
            continue
        row["capability_state"] = "CONFIRMED" if confirmed else "CONFIGURED_EXPLICIT"
        row["identity_evidence"] = "resolved_telemetry" if confirmed else "configured_explicit"
        key = (row["model_id"], row["reasoning_effort"])
        rows.setdefault(key, row)
    return sorted(rows.values(), key=_catalog_sort_key)


def _route_map(value: Any, key_size: int) -> dict[tuple[str, ...], Mapping[str, Any]]:
    if isinstance(value, Mapping):
        result: dict[tuple[str, ...], Mapping[str, Any]] = {}
        for key, row in value.items():
            if isinstance(key, tuple) and len(key) == key_size and isinstance(row, Mapping):
                result[tuple(str(part) for part in key)] = row
            elif isinstance(key, str) and isinstance(row, Mapping):
                parts = tuple(part.casefold() for part in key.replace(":", "|").split("|"))
                if len(parts) == key_size:
                    result[parts] = row
        return result
    result = {}
    if isinstance(value, list):
        for row in value:
            if not isinstance(row, Mapping):
                continue
            fields = ("model_id", "reasoning_effort") if key_size == 2 else ("model_id", "reasoning_effort", "role")
            parts = tuple(str(row.get(field) or "").casefold() for field in fields)
            if all(parts):
                result[parts] = row
    return result


def _hard_filter_routes(task: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]]]:
    """Apply host/model/effort/policy gates before any quality estimate."""

    required_tools = {str(item) for item in task.get("required_tools", []) if str(item)}
    required_boundary = str(task.get("data_boundary") or "local")
    required_budget = float(task.get("budget") or 0)
    raw_routes = task.get("available_routes", task.get("routes", []))
    if isinstance(raw_routes, Mapping):
        raw_routes = [{"route_id": key, **(value if isinstance(value, Mapping) else {})} for key, value in raw_routes.items()]
    eligible: list[Mapping[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in raw_routes if isinstance(raw_routes, list) else []:
        if not isinstance(raw, Mapping):
            continue
        host = str(raw.get("host_id") or raw.get("host") or "codex").casefold()
        model = str(raw.get("model_id") or "").casefold()
        effort = str(raw.get("reasoning_effort") or "").casefold()
        reasons: list[str] = []
        if host != "codex":
            reasons.append("codex_host_required")
        if model not in EXPLICIT_MODELS:
            reasons.append("explicit_gpt56_model_required")
        if effort not in EFFORTS:
            reasons.append("unsupported_reasoning_effort")
        if not _as_bool(raw.get("available", raw.get("provider_available", True))):
            reasons.append("host_unavailable")
        if not _as_bool(raw.get("logged_in", raw.get("authenticated", True))):
            reasons.append("login_unavailable")
        if raw.get("fallback") is True or raw.get("fallback_used") is True:
            reasons.append("fallback_forbidden")
        supported_efforts = raw.get("supported_efforts")
        if isinstance(supported_efforts, (list, tuple, set)) and effort not in {str(item).casefold() for item in supported_efforts}:
            reasons.append("reasoning_effort_not_supported_by_host")
        boundaries = {str(item) for item in raw.get("data_boundaries", ["local"])}
        if required_boundary not in boundaries and "any" not in boundaries:
            reasons.append("data_boundary_mismatch")
        tools = {str(item) for item in raw.get("tools", [])}
        if not required_tools.issubset(tools):
            reasons.append("tool_permission_missing")
        if float(raw.get("budget_remaining", float("inf"))) < required_budget:
            reasons.append("budget_insufficient")
        if reasons:
            rejected.append({"route_id": str(raw.get("route_id") or route_id(host, model, effort, str(raw.get("role") or "unknown"))), "reasons": sorted(set(reasons))})
        else:
            eligible.append({**dict(raw), "host_id": host, "model_id": model, "reasoning_effort": effort})
    return eligible, rejected


def model_route_decision(task: Mapping[str, Any], *, mode: str = "SHADOW") -> dict[str, Any]:
    """Create the historical v2 receipt, or dispatch an explicit v3 request.

    The v2 shape remains a read-only compatibility reader for existing callers
    and receipts.  New CLI/MCP requests set ``router_version=v3`` and use the
    active Router v3 implementation below.
    """

    if str(task.get("router_version") or "").casefold() == "v3":
        return model_route_decision_v3(task, mode=mode)

    role = str(task.get("role") or task.get("requested_role") or "implementer").casefold()
    if role not in ROLES:
        role = "implementer"
    risk = max(1, min(5, int(task.get("failure_cost") or task.get("risk") or 3)))
    routes, rejected = _hard_filter_routes(task)
    external_rows: list[Any] = list(task.get("external_routes", [])) if isinstance(task.get("external_routes", []), list) else []
    prior = task.get("codexradar_prior")
    if isinstance(prior, Mapping) and isinstance(prior.get("routes"), list):
        # CodexRadar remains an advisory prior.  Local outcomes are still
        # applied separately by build_shortlist and no raw provider payload is
        # copied into the decision receipt.
        external_rows.extend(prior["routes"])
    external_routes = _route_map(external_rows, 2)
    local_routes = _route_map(task.get("local_routes", []), 3)
    shortlist = build_shortlist(
        role=role,
        risk=risk,
        available_routes=routes,
        external_routes=external_routes,
        local_routes=local_routes,
        allow_sol_max_calibration=bool(task.get("allow_sol_max_calibration")),
        max_external_strength=min(8.0, float(task.get("max_external_prior_strength", 8.0))),
    )
    recommended = shortlist.get("recommended_route_id")
    if recommended:
        chosen = next(row for row in shortlist["shortlist"] if row["route_id"] == recommended)
        jev_decision: dict[str, Any] = {
            "kind": "Choice",
            "route_id": recommended,
            "model_id": chosen["model_id"],
            "reasoning_effort": chosen["reasoning_effort"],
            "role": chosen["role"],
            "confidence": max(0.0, min(1.0, float(chosen["quality_conservative"]))),
        }
    else:
        jev_decision = {"kind": "Noul", "value": "NO_ELIGIBLE_ROUTE", "route_id": ""}
    task_profile = {
        "role": role,
        "complexity": max(1, min(5, int(task.get("complexity") or 3))),
        "failure_cost": risk,
        "context_pressure": max(1, min(5, int(task.get("context_pressure") or 3))),
        "should_parallelize": task.get("should_parallelize"),
        "needs_independent_review": task.get("needs_independent_review"),
        "context_profile": str(task.get("context_profile") or "bounded"),
    }
    observed = task.get("observed") if isinstance(task.get("observed"), Mapping) else {}
    execution_requested = str(mode).upper() == "EXECUTE"
    identity_matches = bool(
        recommended
        and observed.get("model_id") == (jev_decision.get("model_id"))
        and observed.get("reasoning_effort") == (jev_decision.get("reasoning_effort"))
        and _as_bool(observed.get("real_identity_observed"))
    )
    execution = {
        "executed": bool(execution_requested and identity_matches),
        "observed_model_id": observed.get("model_id"),
        "observed_reasoning_effort": observed.get("reasoning_effort"),
        "identity_evidence": observed.get("identity_evidence") or ("resolved_telemetry" if observed.get("real_identity_observed") is True else None),
        "verifier_pass": observed.get("verifier_pass"),
        "observed_subscription_quota_pct": observed.get("observed_subscription_quota_pct"),
        "external_estimated_quota_pct": observed.get("external_estimated_quota_pct"),
        "api_equivalent_usd": observed.get("api_equivalent_usd"),
        "input_tokens": observed.get("input_tokens"),
        "output_tokens": observed.get("output_tokens"),
        "latency_seconds": observed.get("latency_seconds"),
        "execution_guard": "OBSERVED_IDENTITY_REQUIRED",
    }
    receipt: dict[str, Any] = {
        "schema": "contextcord-model-route-decision-v2",
        "mode": str(mode).upper() if str(mode).upper() in {"SHADOW", "EXECUTE"} else "SHADOW",
        "task_profile": task_profile,
        "eligible_routes": shortlist.get("shortlist", []),
        "rejected_routes": rejected,
        "shortlist": shortlist,
        "jev_decision": jev_decision,
        "typed_fields": [
            {"kind": "Score", "name": "task_complexity", "value": task_profile["complexity"]},
            {"kind": "Score", "name": "failure_cost", "value": task_profile["failure_cost"]},
            {"kind": "Score", "name": "context_pressure", "value": task_profile["context_pressure"]},
            {"kind": "Noul", "name": "should_parallelize", "value": task_profile["should_parallelize"]},
            {"kind": "Noul", "name": "needs_independent_review", "value": task_profile["needs_independent_review"]},
            {"kind": "Choice", "name": "context_profile", "value": task_profile["context_profile"]},
        ],
        "policy": {"max_attempts": MAX_EXECUTION_ATTEMPTS, "fallback_allowed": False, "max_auto_escalations": 1},
        "execution": execution,
        "sources": list(task.get("sources") or []),
        "external_prior_status": task.get(
            "external_prior_status",
            prior.get("status", "UNAVAILABLE") if isinstance(prior, Mapping) else "UNAVAILABLE",
        ),
        "budget": {"calibration_live_call_cap": MAX_CALIBRATION_CALLS, "sol_max_runs_cap": MAX_SOL_MAX_RUNS},
        "truth_boundary": "Jev may choose only from the deterministic closed shortlist; host permissions, credentials and execution remain authoritative.",
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def router_gate0(*, task: Mapping[str, Any], shortlist: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Decide deterministically whether a semantic Jev call is warranted."""

    if not shortlist:
        return {"outcome": "BYPASS_JEV_NO_SHORTLIST", "reason_codes": ["no_eligible_route"]}
    if len(shortlist) < 2:
        return {"outcome": "BYPASS_JEV_SIMPLE_CASE", "reason_codes": ["shortlist_has_at_most_one_route"]}
    jev_mode = str(task.get("jev_mode") or "on_demand").casefold()
    if jev_mode in {"off", "disabled", "false", "0"} or task.get("jev_enabled") is False:
        return {"outcome": "BYPASS_JEV_DISABLED", "reason_codes": ["jev_disabled_or_mode_off"]}
    if task.get("jev_ready") is False or task.get("jev_unready") is True:
        return {"outcome": "BYPASS_JEV_UNREADY", "reason_codes": ["jev_not_ready"]}

    risk = max(1, min(5, int(task.get("failure_cost") or task.get("risk") or 3)))
    pressure = max(1, min(5, int(task.get("context_pressure") or 3)))
    semantic_markers = task.get("semantic_conflict_markers") or task.get("blast_radius") or []
    if isinstance(semantic_markers, (str, bytes)):
        semantic_markers = [semantic_markers]
    review_uncertainty = any(
        _as_bool(task.get(name))
        for name in ("review_uncertainty", "needs_independent_review", "independent_review_uncertain")
    )
    local_conflict = any(
        _as_bool(task.get(name))
        for name in ("local_conflict", "planner_local_conflict", "local_outcome_conflict")
    )
    reasons = ["shortlist_tradeoff_close"]
    if risk >= 4:
        reasons.append("failure_cost_high")
    if semantic_markers:
        reasons.append("semantic_or_blast_radius_uncertain")
    if pressure >= 4:
        reasons.append("context_pressure_high")
    if review_uncertainty:
        reasons.append("review_uncertainty")
    if local_conflict:
        reasons.append("planner_local_conflict")
    if risk <= 2 and len(reasons) == 1:
        return {"outcome": "BYPASS_JEV_LOW_RISK", "reason_codes": ["low_risk_clear_planner"]}
    return {"outcome": "REQUEST_JEV", "reason_codes": reasons}


ROUTER_TYPED_QUESTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "route_choice",
        "type": "choice",
        "instructions": "Choose exactly one route from the closed shortlist. Do not invent a route or override host permissions.",
    },
    {"id": "task_complexity", "type": "score", "levels": ["1", "2", "3", "4", "5"]},
    {"id": "failure_cost", "type": "score", "levels": ["1", "2", "3", "4", "5"]},
    {"id": "context_pressure", "type": "score", "levels": ["1", "2", "3", "4", "5"]},
    {"id": "should_parallelize", "type": "noul"},
    {"id": "needs_independent_review", "type": "noul"},
    {
        "id": "context_profile",
        "type": "choice",
        "options": ["minimal", "bounded", "continuity_only", "full"],
    },
)


def _router_provider_usage(provider_result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(provider_result, Mapping):
        return None
    return {
        "status": provider_result.get("status"),
        "effective_provider": provider_result.get("effective_provider"),
        "model": provider_result.get("model"),
        "usage": provider_result.get("usage"),
        "latency_ms": provider_result.get("latency_ms"),
        "key_source": provider_result.get("key_source"),
        "attempts": provider_result.get("attempts", 0),
        "fallback_used": bool(provider_result.get("fallback_used")),
        "fallback_reason": provider_result.get("fallback_reason"),
    }


def _router_answer_value(answer: Any) -> Any:
    if isinstance(answer, Mapping):
        for key in ("value", "choice", "noul", "score"):
            if key in answer:
                return answer[key]
    return answer


def model_route_decision_v3(
    task: Mapping[str, Any],
    *,
    mode: str = "SHADOW",
    jev_provider: Any = None,
) -> dict[str, Any]:
    """Build the active Router v3 receipt with a closed Jev choice boundary."""

    mode_value = str(mode).upper() if str(mode).upper() in {"SHADOW", "EXECUTE"} else "SHADOW"
    role = str(task.get("role") or task.get("requested_role") or "implementer").casefold()
    if role not in ROLES:
        role = "implementer"
    risk = max(1, min(5, int(task.get("failure_cost") or task.get("risk") or 3)))

    analysis_catalog = discover_analysis_routes(task)
    observed_routes = task.get("execution_routes", task.get("observed_routes", []))
    execution_catalog = discover_execution_routes(observed_routes)
    available_catalog = execution_catalog if mode_value == "EXECUTE" else analysis_catalog
    planning_task = {**dict(task), "available_routes": available_catalog}
    routes, rejected = _hard_filter_routes(planning_task)

    external_rows: list[Any] = list(task.get("external_routes", [])) if isinstance(task.get("external_routes", []), list) else []
    prior = task.get("codexradar_prior")
    if isinstance(prior, Mapping) and isinstance(prior.get("routes"), list):
        external_rows.extend(prior["routes"])
    external_routes = _route_map(external_rows, 2)
    local_routes = _route_map(task.get("local_routes", []), 3)
    shortlist = build_shortlist(
        role=role,
        risk=risk,
        available_routes=routes,
        external_routes=external_routes,
        local_routes=local_routes,
        allow_sol_max_calibration=bool(task.get("allow_sol_max_calibration")),
        max_external_strength=min(8.0, float(task.get("max_external_prior_strength", 8.0))),
    )
    shortlist_rows = list(shortlist.get("shortlist") or [])
    planner = None
    if shortlist_rows:
        planner = {
            **dict(shortlist_rows[0]),
            "reason": "near_best_quality_minimum_cost",
            "selection_basis": "conservative_quality_then_separate_cost_units",
        }
    task_profile = {
        "role": role,
        "complexity": max(1, min(5, int(task.get("complexity") or 3))),
        "failure_cost": risk,
        "context_pressure": max(1, min(5, int(task.get("context_pressure") or 3))),
        "should_parallelize": task.get("should_parallelize"),
        "needs_independent_review": task.get("needs_independent_review"),
        "context_profile": str(task.get("context_profile") or "bounded"),
    }
    gate = router_gate0(task=task, shortlist=shortlist_rows)
    semantic_decision = None
    provider_result: Mapping[str, Any] | None = None
    decision_source = "deterministic_planner" if planner is None else "jev_bypassed"
    effective = {**dict(planner), "source": "planner"} if planner is not None else None

    if planner is not None and gate["outcome"] == "REQUEST_JEV":
        if jev_provider is None:
            decision_source = "jev_unavailable"
            effective = {**dict(planner), "source": "jev_fallback"}
        else:
            questions: list[dict[str, Any]] = []
            allowed_ids = [str(row["route_id"]) for row in shortlist_rows]
            for question in ROUTER_TYPED_QUESTIONS:
                item = dict(question)
                if item["id"] == "route_choice":
                    item["options"] = allowed_ids
                questions.append(item)
            request_state = {
                "candidate_count": len(shortlist_rows),
                "candidates": shortlist_rows,
                "route_uncertainty": len(shortlist_rows) > 1,
                "failure_cost": task_profile["failure_cost"],
                "context_pressure": task_profile["context_pressure"],
                "task_complexity": task_profile["complexity"],
                "semantic_conflict_markers": task.get("semantic_conflict_markers"),
                "planner_local_conflict": task.get("planner_local_conflict"),
            }
            try:
                result = jev_provider.decide(request_state, questions, stage="router")
                provider_result = result if isinstance(result, Mapping) else None
            except Exception as exc:
                provider_result = {
                    "status": "FALLBACK",
                    "effective_provider": "deterministic_fallback",
                    "fallback_used": True,
                    "fallback_reason": type(exc).__name__,
                    "attempts": 1,
                }
            if provider_result and provider_result.get("effective_provider") == "jev_api" and not provider_result.get("fallback_used"):
                answers = provider_result.get("answers") if isinstance(provider_result.get("answers"), Mapping) else {}
                route_answer = answers.get("route_choice")
                chosen = _router_answer_value(route_answer)
                if str(chosen) not in set(allowed_ids):
                    decision_source = "jev_invalid_choice"
                    effective = {**dict(planner), "source": "jev_fallback"}
                else:
                    chosen_row = next(row for row in shortlist_rows if row["route_id"] == str(chosen))
                    semantic_decision = {
                        "provider": "jev_api",
                        "kind": "Choice",
                        "route_id": str(chosen),
                        "confidence": route_answer.get("confidence") if isinstance(route_answer, Mapping) else None,
                        "usage": provider_result.get("usage"),
                        "latency_ms": provider_result.get("latency_ms"),
                    }
                    decision_source = "jev_api"
                    effective = {**dict(chosen_row), "source": "jev_api"}
            else:
                decision_source = "jev_unavailable"
                effective = {**dict(planner), "source": "jev_fallback"}

    cost_note = None
    if external_rows and not any(
        isinstance(row.get("median_estimated_quota_pct"), (int, float)) and not isinstance(row.get("median_estimated_quota_pct"), bool)
        for row in external_rows if isinstance(row, Mapping)
    ):
        cost_note = "subscription_quota_optimization_not_yet_observed"
    observed = task.get("observed") if isinstance(task.get("observed"), Mapping) else {}
    execution_requested = mode_value == "EXECUTE"
    identity_matches = bool(
        effective
        and observed.get("model_id") == effective.get("model_id")
        and observed.get("reasoning_effort") == effective.get("reasoning_effort")
        and (
            observed.get("real_identity_observed") is True
            or str(observed.get("identity_evidence") or "").casefold() == "configured_explicit"
            or str(observed.get("capability_state") or "").upper() == "CONFIGURED_EXPLICIT"
        )
        and observed.get("fallback_observed") is not True
        and observed.get("fallback_used") is not True
    )
    execution = {
        "executed": bool(execution_requested and identity_matches),
        "observed_model_id": observed.get("model_id"),
        "observed_reasoning_effort": observed.get("reasoning_effort"),
        "verifier_pass": observed.get("verifier_pass"),
        "observed_subscription_quota_pct": observed.get("observed_subscription_quota_pct"),
        "external_estimated_quota_pct": observed.get("external_estimated_quota_pct"),
        "api_equivalent_usd": observed.get("api_equivalent_usd"),
        "input_tokens": observed.get("input_tokens"),
        "output_tokens": observed.get("output_tokens"),
        "latency_seconds": observed.get("latency_seconds"),
        "execution_guard": "OBSERVED_IDENTITY_REQUIRED",
    }
    receipt: dict[str, Any] = {
        "schema": "contextcord-model-route-decision-v3",
        "mode": mode_value,
        "task_profile": task_profile,
        "eligible_routes": shortlist_rows,
        "rejected_routes": rejected,
        "shortlist": shortlist,
        "planner_recommendation": planner,
        "semantic_decision": semantic_decision,
        "decision_source": decision_source,
        "effective_route": effective,
        "semantic_gate": gate,
        "provider_usage": _router_provider_usage(provider_result),
        "provider_calls": 1 if provider_result and int(provider_result.get("attempts") or 0) > 0 else 0,
        "typed_fields": [
            {
                "kind": "Choice",
                "name": "route_choice",
                "options": list(shortlist.get("eligible_route_ids") or []),
                "value": planner.get("route_id") if planner else None,
            },
            {"kind": "Score", "name": "task_complexity", "value": task_profile["complexity"]},
            {"kind": "Score", "name": "failure_cost", "value": task_profile["failure_cost"]},
            {"kind": "Score", "name": "context_pressure", "value": task_profile["context_pressure"]},
            {"kind": "Noul", "name": "should_parallelize", "value": task_profile["should_parallelize"]},
            {"kind": "Noul", "name": "needs_independent_review", "value": task_profile["needs_independent_review"]},
            {"kind": "Choice", "name": "context_profile", "value": task_profile["context_profile"]},
        ],
        "policy": {"max_attempts": MAX_EXECUTION_ATTEMPTS, "fallback_allowed": False, "max_auto_escalations": 1},
        "execution": execution,
        "sources": list(task.get("sources") or []),
        "external_prior_status": task.get(
            "external_prior_status",
            prior.get("status", "UNAVAILABLE") if isinstance(prior, Mapping) else "UNAVAILABLE",
        ),
        "catalog": {
            "analysis_route_count": len(analysis_catalog),
            "execution_route_count": len(execution_catalog),
            "analysis_execution_boundary": "analysis_catalog_is_advisory; execution_catalog_requires_observed_identity_and_host_capability",
        },
        "quality_cost_basis": cost_note,
        "budget": {"calibration_live_call_cap": MAX_CALIBRATION_CALLS, "sol_max_runs_cap": MAX_SOL_MAX_RUNS},
        "truth_boundary": "Jev may choose only from the deterministic closed shortlist; host permissions, credentials, budget and execution remain authoritative.",
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def decide_route_v3(*, task: Mapping[str, Any], shortlist: list[Mapping[str, Any]] | None = None,
                    planner_recommendation: Mapping[str, Any] | None = None, jev_provider: Any = None) -> dict[str, Any]:
    """Compatibility helper matching the attached v3 reference shape."""

    if shortlist is None:
        return model_route_decision_v3(task, jev_provider=jev_provider)
    value = dict(task)
    value["available_routes"] = list(shortlist)
    if planner_recommendation:
        value["planner_recommendation"] = dict(planner_recommendation)
    return model_route_decision_v3(value, jev_provider=jev_provider)


def recommendation_pair(task: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the external-prior planner with the same planner plus local outcomes."""

    base = dict(task)
    base["jev_mode"] = "off"
    radar_only = model_route_decision_v3({**base, "local_routes": []})
    radar_local = model_route_decision_v3({**base, "local_routes": list(task.get("local_routes") or [])})
    return {
        "schema": "contextcord-router-recommendation-pair-v1",
        "radar_only": {
            "route_id": (radar_only.get("effective_route") or {}).get("route_id"),
            "decision_source": radar_only.get("decision_source"),
            "catalog": radar_only.get("catalog"),
        },
        "radar_plus_local": {
            "route_id": (radar_local.get("effective_route") or {}).get("route_id"),
            "decision_source": radar_local.get("decision_source"),
            "catalog": radar_local.get("catalog"),
        },
        "local_outcome_count": sum(int(row.get("observations") or 0) for row in (task.get("local_routes") or []) if isinstance(row, Mapping)),
        "truth_boundary": "CodexRadar is an external prior capped at eight equivalent observations; local execution outcomes remain separate and host_only is excluded from model-specific learning.",
    }


def validate_jev_choice(shortlist: Mapping[str, Any], route_choice: str) -> bool:
    """Verify that a typed Jev route remains inside the closed shortlist."""

    return str(route_choice) in set(shortlist.get("eligible_route_ids") or [])


def next_escalation_route(decision: Mapping[str, Any], *, verifier_pass: bool, attempts_used: int) -> str | None:
    """Return at most one next Pareto candidate after a hard failure."""

    if verifier_pass or attempts_used >= MAX_EXECUTION_ATTEMPTS:
        return None
    shortlist = decision.get("shortlist") if isinstance(decision.get("shortlist"), Mapping) else {}
    ids = list(shortlist.get("eligible_route_ids") or [])
    current = decision.get("effective_route") if isinstance(decision.get("effective_route"), Mapping) else {}
    if not current:
        current = decision.get("jev_decision") if isinstance(decision.get("jev_decision"), Mapping) else {}
    current_id = str(current.get("route_id") or "")
    if current_id not in ids:
        return None
    index = ids.index(current_id)
    return ids[index + 1] if index + 1 < len(ids) else None


@dataclass
class CalibrationBudget:
    """Hard cap for a calibration round; cost units stay separate."""

    live_call_cap: int = MAX_CALIBRATION_CALLS
    sol_max_runs_cap: int = MAX_SOL_MAX_RUNS
    calls_used: int = 0
    sol_max_runs: int = 0
    routes: list[dict[str, Any]] = field(default_factory=list)

    def admit(self, model_id: str, reasoning_effort: str) -> tuple[bool, str]:
        if self.calls_used >= min(MAX_CALIBRATION_CALLS, max(1, self.live_call_cap)):
            return False, "live_call_cap_reached"
        if model_id == "gpt-5.6-sol" and reasoning_effort == "max" and self.sol_max_runs >= min(MAX_SOL_MAX_RUNS, max(0, self.sol_max_runs_cap)):
            return False, "sol_max_cap_reached"
        if model_id not in EXPLICIT_MODELS or reasoning_effort not in EFFORTS:
            return False, "route_not_in_explicit_catalog"
        return True, "admitted"

    def record(self, route: Mapping[str, Any], *, verifier_pass: bool | None = None, **costs: Any) -> dict[str, Any]:
        model = str(route.get("model_id") or "")
        effort = str(route.get("reasoning_effort") or "")
        allowed, reason = self.admit(model, effort)
        if not allowed:
            raise ValueError(reason)
        self.calls_used += 1
        if model == "gpt-5.6-sol" and effort == "max":
            self.sol_max_runs += 1
        row = {
            "route_id": str(route.get("route_id") or route_id("codex", model, effort, str(route.get("role") or "implementer"))),
            "model_id": model,
            "reasoning_effort": effort,
            "verifier_pass": verifier_pass,
            "observed_subscription_quota_pct": costs.get("observed_subscription_quota_pct"),
            "external_estimated_quota_pct": costs.get("external_estimated_quota_pct"),
            "api_equivalent_usd": costs.get("api_equivalent_usd"),
            "input_tokens": costs.get("input_tokens"),
            "output_tokens": costs.get("output_tokens"),
            "latency_seconds": costs.get("latency_seconds"),
        }
        self.routes.append(row)
        return row

    def receipt(self, round_id: str, *, early_stop: bool = False, stop_reason: str | None = None) -> dict[str, Any]:
        value = {
            "schema": "contextcord-router-calibration-receipt-v1",
            "round_id": str(round_id),
            "live_call_cap": min(MAX_CALIBRATION_CALLS, max(1, self.live_call_cap)),
            "calls_used": self.calls_used,
            "sol_max_runs": self.sol_max_runs,
            "routes": list(self.routes),
            "early_stop": bool(early_stop),
            "stop_reason": stop_reason,
            "truth_boundary": "API-equivalent USD, observed subscription quota, external estimated quota and tokens are separate units.",
        }
        value["receipt_sha256"] = _sha(value)
        return value
