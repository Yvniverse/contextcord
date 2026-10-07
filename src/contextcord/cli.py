from __future__ import annotations

import argparse
import json
import os
import sys
import sqlite3
from pathlib import Path
from typing import Any

from .adapters import capabilities as adapter_capabilities, check_requirements as adapter_check_requirements, render as render_adapter
from .build_identity import build_identity
from .capabilities import (
    CapabilityConfigError,
    atomic_write_features,
    enabled as capability_enabled,
    product_module_projection,
    resolve_features,
    status as capability_status,
)
from .closeout import closeout as run_closeout
from .config import ConfigError, discover
from .context import render_context, resolve_context
from .decision_fabric import evaluate_decision_fabric
from .dualrun import record as dual_record, summary as dual_summary
from .evidence import prepare_records, record_prepared, verify_evidence_records
from .fingerprint import policy_fingerprint
from .gitops import branch, head, repo_root, status_porcelain
from .hostbridge import HostAction, authorize_host_action, classify_tool_call, qoder_pretool_result
from .host_configs import generate_host_config
from .handoff import assist_handoff
from .identity import exact_closeout_errors, source_identity
from .profiles import PROFILES, write_profile
from .portable import export_bundle as portable_export, import_bundle as portable_import, verify_bundle as portable_verify
from .memory import add_context_job, add_note, export_memory, import_memory, inspect_memory_bundle, memory_context
from .migration import migrate_state
from .model_intelligence import load_codexradar_prior
from .providers import inspect_codexradar, inspect_jev, list_provider_statuses
from .qualification import deploy as qualification_deploy
from .qualification import read_note as qualification_read_note
from .qualification import record as qualification_record
from .qualification import verify as qualification_verify
from .receipt import (
    matching_complete_receipt,
    matching_handoff_receipt,
    verify_handoff_receipt,
    verify_receipt,
    verify_receipt_chain,
    write_sealed_receipt,
)
from .release_identity import collect as collect_release_identity
from .router import model_route_decision, model_route_decision_v3, recommendation_pair, shadow_route
from .execution_routes import discover_codex_execution_routes
from .runner import run_check
from .runtime import run_probes
from .store import StateStore
from .truth import classification_counts
from .util import atomic_write_json, safe_id, utc_now
from .workflow import advance as workflow_advance
from .workflow import initial_task, phase_ids, required_phases_for_scope, validate_workflow
from .workflow_checks import phase_contract_verdict, workflow_completion_verdict


def _repo(value: str | None) -> Path:
    return repo_root(Path(value).resolve() if value else Path.cwd())


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _feature_resolution(repo: Path):
    cfg = discover(repo)
    return cfg, resolve_features(cfg.project)


def _require_capability(repo: Path, capability: str) -> bool:
    """Return false with a structured response when a command is disabled.

    Projects without a ``[features]`` table intentionally use the
    ``legacy_current`` compatibility surface.  This fallback also keeps direct
    programmatic calls to older handlers working for uninitialized fixtures.
    """

    try:
        cfg, resolved = _feature_resolution(repo)
    except ConfigError:
        return True
    if capability_enabled(resolved, capability):
        return True
    _json({
        "status": "FEATURE_DISABLED",
        "capability": capability,
        "hint": f"contextcord feature enable {capability}",
    })
    return False


def _project_provider_config(project: dict[str, Any], provider: str) -> dict[str, Any]:
    providers = project.get("providers", {})
    if not isinstance(providers, dict):
        return {}
    value = providers.get(provider, {})
    return dict(value) if isinstance(value, dict) else {}


def _features_file(cfg) -> Path:
    return cfg.root / "project.toml"


def _feature_mutation(cfg, *, operation: str, value: str) -> dict[str, Any]:
    raw = cfg.project.get("features")
    if isinstance(raw, dict):
        features = dict(raw)
        profile = str(features.get("profile") or "custom")
        enable = {str(item) for item in features.get("enable", [])}
        disable = {str(item) for item in features.get("disable", [])}
    else:
        features = {}
        profile = "legacy_current"
        enable = set()
        disable = set()
    if operation == "profile":
        profile = str(value)
    elif operation == "enable":
        enable.add(str(value)); disable.discard(str(value))
    elif operation == "disable":
        disable.add(str(value)); enable.discard(str(value))
    else:
        raise ValueError(f"unknown_feature_mutation:{operation}")
    candidate = {"features": {"profile": profile, "enable": sorted(enable), "disable": sorted(disable)}}
    resolved = resolve_features(candidate)
    atomic_write_features(cfg.root / "project.toml", profile=profile, enable=enable, disable=disable)
    return {
        "status": "PASS",
        "operation": operation,
        "value": value,
        "config_path": str((cfg.root / "project.toml").relative_to(cfg.repo)),
        "resolved": resolved,
    }


def cmd_feature(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    cfg, resolved = _feature_resolution(repo)
    command = args.feature_command
    if command == "list":
        _json(capability_status(cfg.project, project_root=repo)); return 0
    if command == "modules":
        _json(
            product_module_projection(
                resolved,
                capability_status=capability_status(cfg.project, project_root=repo),
            )
        ); return 0
    if command == "status":
        value = capability_status(cfg.project, project_root=repo)
        row = next((item for item in value["capabilities"] if item["id"] == args.capability), None)
        if row is None:
            raise CapabilityConfigError("unknown_capability", f"unknown_capability:{args.capability}")
        _json({"schema": value["schema"], "profile": value["profile"], "capability": row}); return 0
    value = _feature_mutation(cfg, operation=command, value=args.value)
    _json(value)
    return 0


def cmd_provider(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    cfg, resolved = _feature_resolution(repo)
    provider_command = args.provider_command
    provider = getattr(args, "provider", None)
    statuses = list_provider_statuses(project_root=repo, resolved_features=resolved, project=cfg.project)
    if provider_command == "list":
        _json({"schema": "contextcord-provider-list-v1", "providers": statuses}); return 0
    if provider != "jev":
        raise ValueError(f"unknown_provider:{provider}")
    value = next(item for item in statuses if item["provider"] == "jev")
    if provider_command == "status":
        _json(value); return 0
    if provider_command != "doctor":
        raise ValueError(f"unknown_provider_command:{provider_command}")
    value = dict(value)
    value["doctor_mode"] = "live" if args.live else "local"
    if not args.live:
        value["status"] = "PASS" if value.get("ready") else "NOT_READY"
        _json(value); return 0
    if not value.get("ready"):
        value.update({"status": "NOT_RUN", "network_probe_performed": False})
        _json(value); return 0
    # Explicit --live is the only path that can issue a Jev request.  The
    # request is a single typed smoke question and the provider response is
    # already secret-safe.
    from .jev_provider import JevApiDecisionProvider

    try:
        result = JevApiDecisionProvider(
            project_root=repo,
            model=str(value.get("model") or "jev-latest"),
            endpoint=str(value.get("endpoint") or "https://api.typesafe.ai"),
            max_retries=0,
        ).decide(
            {"task_id": "provider-doctor", "data_boundary": "local"},
            [{"id": "smoke", "type": "noul", "instructions": "Return one typed smoke response."}],
            stage="provider_doctor",
        )
        value.update({"status": result.get("status"), "network_probe_performed": True, "receipt": {
            "schema": result.get("question_schema"),
            "status": result.get("status"),
            "latency_ms": result.get("latency_ms"),
            "attempts": result.get("attempts"),
            "usage": result.get("usage"),
            "fallback_used": result.get("fallback_used"),
            "fallback_reason": result.get("fallback_reason"),
        }})
    except Exception as exc:  # provider failures are local doctor evidence
        value.update({"status": "FAIL", "network_probe_performed": True, "error": type(exc).__name__})
    _json(value)
    return 0 if value.get("status") not in {"FAIL"} else 2


def _codexradar_cache_status(cache_path: Path) -> dict[str, Any]:
    if not cache_path.is_file():
        return {"cache_present": False, "cache_status": "EMPTY", "cache_age_seconds": None}
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched = float(raw.get("fetched_at"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"cache_present": True, "cache_status": "MALFORMED", "cache_age_seconds": None}
    return {"cache_present": True, "cache_status": "PRESENT", "cache_age_seconds": max(0.0, __import__("time").time() - fetched)}


def cmd_model_intelligence(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    cfg, resolved = _feature_resolution(repo)
    provider_cfg = _project_provider_config(cfg.project, "codexradar")
    value = inspect_codexradar(
        project_root=repo,
        feature_enabled=capability_enabled(resolved, "model_intelligence"),
        provider_config=provider_cfg,
    )
    cache_path = Path(value["cache_path"])
    value.update(_codexradar_cache_status(cache_path))
    if args.model_intelligence_command == "status":
        _json(value); return 0
    if not _require_capability(repo, "model_intelligence"):
        return 2
    enabled_provider = bool(value.get("enabled"))
    options = {
        "url": str(provider_cfg.get("source_url") or provider_cfg.get("api_url") or "https://api.codexradar.com/api/v1/table?benchmark=deep-swe"),
        "ttl_seconds": int(provider_cfg.get("ttl_seconds", 600)),
        "max_stale_seconds": int(provider_cfg.get("max_stale_seconds", 86400)),
        "timeout_seconds": float(provider_cfg.get("timeout_seconds", 3)),
        "refresh": bool(args.refresh),
    }
    prior = load_codexradar_prior(repo, enabled=enabled_provider, **options)
    # Persist only the derived receipt.  The raw table remains in the ignored
    # local cache and is never copied into a release artifact.
    receipt_path = repo / ".contextcord" / "cache" / "model-intelligence" / "latest-snapshot.json"
    atomic_write_json(receipt_path, prior)
    prior["receipt_path"] = str(receipt_path.relative_to(repo)).replace("\\", "/")
    _json(prior)
    return 0


def cmd_router_outcomes(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "router"):
        return 2
    with StateStore(repo) as store:
        if args.outcome_command == "record":
            cfg = None
            source_identity_sha = None
            try:
                cfg = discover(repo)
                source_identity_sha = source_identity(cfg)["identity_sha256"]
            except ConfigError:
                pass
            value = store.record_model_outcome(
                task_class=args.task_class,
                role=args.role,
                model_id=args.model,
                reasoning_effort=args.effort,
                verifier_pass=bool(args.verifier_pass),
                identity_evidence=args.identity_evidence,
                attempts=args.attempts,
                context_profile=args.context_profile,
                source_identity_sha256=source_identity_sha,
                route_decision_receipt_sha256=args.receipt_sha256,
                verifier_id=args.verifier_id,
                elapsed_ms=args.elapsed_ms,
                input_tokens=args.input_tokens,
                output_tokens=args.output_tokens,
                observed_subscription_quota_delta=args.quota_delta,
                api_equivalent_usd=args.api_equivalent_usd,
                external_prior_source=args.external_prior_source,
                external_prior_age_seconds=args.external_prior_age_seconds,
                task_id=args.task_id,
            )
            _json({"status": "RECORDED", "outcome": value}); return 0
        if args.outcome_command == "show":
            rows = store.model_outcomes(model_id=args.model, reasoning_effort=args.effort, role=args.role, task_class=args.task_class, limit=args.limit)
            _json({"schema": "contextcord-model-route-outcomes-v1", "count": len(rows), "outcomes": rows}); return 0
        rows = store.model_outcome_summary(model_id=args.model, reasoning_effort=args.effort, role=args.role, task_class=args.task_class)
    _json({"schema": "contextcord-model-route-outcome-summary-v1", "local_evidence": True, "routes": rows}); return 0


def _find_unresolved(value: Any, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(value, str) and "${" in value:
        out.append(f"{path}:{value}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            out += _find_unresolved(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for k, item in value.items():
            out += _find_unresolved(item, f"{path}.{k}" if path else str(k))
    return out


def cmd_init(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    state_dir = getattr(args, "state_dir", None) or os.environ.get("CONTEXTCORD_INIT_STATE_DIR", ".contextcord")
    paths = write_profile(repo, args.profile, force=args.force, state_dir=state_dir)
    _json({"status": "PASS", "profile": args.profile, "state_dir": state_dir, "written": [str(p.relative_to(repo)) for p in paths]})
    return 0


def doctor_value(repo: Path) -> dict[str, Any]:
    cfg = discover(repo); failures = validate_workflow(cfg.workflow); warnings: list[str] = []
    for rel in cfg.knowledge_entrypoints:
        p = repo / rel
        if not p.is_file() or p.is_symlink():
            failures.append(f"knowledge_entrypoint_missing_or_invalid:{rel}")
    unresolved = []
    for name, value in [("project", cfg.project), ("truth", cfg.truth), ("authority", cfg.authority), ("runtime", cfg.runtime), ("evidence", cfg.evidence), ("qualification", cfg.qualification)]:
        unresolved += [f"{name}:{x}" for x in _find_unresolved(value)]
    warnings += [f"unresolved_environment_variable:{x}" for x in unresolved]
    current_policy = policy_fingerprint(repo, cfg.policy_entrypoints)
    ident = source_identity(cfg)
    with StateStore(repo) as store:
        chain_ok, bad = store.verify_event_chain()
        if not chain_ok:
            failures.append(f"event_chain_invalid:{bad}")
        rchain = verify_receipt_chain(cfg, store=store)
        if rchain["status"] != "PASS":
            failures.extend(rchain["errors"])
        for rec in store.open_sessions():
            started = rec.get("start_policy_fingerprint")
            if started and started != current_policy["sha256"]:
                failures.append(f"open_session_policy_drift:{rec['session_id']}")
        state_path = str(store.path)
    return {
        "status": "PASS" if not failures else "BLOCKED",
        "repo": str(repo), "branch": branch(repo), "head": head(repo), "dirty": bool(status_porcelain(repo)),
        "state_store": state_path, "source_identity": ident, "classification_counts": classification_counts(cfg),
        "receipt_chain": rchain, "failures": failures, "warnings": warnings, "profiles": sorted(PROFILES),
        "capabilities": capability_status(cfg.project, project_root=repo),
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    value = doctor_value(_repo(args.repo)); _json(value); return 0 if value["status"] == "PASS" else 2


def _task_or_create(store: StateStore, cfg, task_id: str, scope: str) -> dict[str, Any]:
    task = store.get_task(task_id)
    if task is None:
        if scope not in cfg.authority.get("scopes", {}):
            raise ValueError(f"unknown scope: {scope}")
        task = initial_task(task_id, scope, cfg.workflow); store.upsert_task(task); store.event("TASK_CREATED", {"scope": scope, "phase": task.get("current_phase")}, task_id=task_id)
    elif task.get("scope") != scope:
        raise ValueError(f"task_scope_mismatch existing={task.get('scope')} requested={scope}")
    return task


def cmd_start(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "continuity"):
        return 2
    cfg = discover(repo); dv = doctor_value(repo)
    if dv["status"] != "PASS" and not args.allow_doctor_warnings:
        _json(dv); return 2
    ident = source_identity(cfg)
    with StateStore(repo) as store, store.transaction():
        _task_or_create(store, cfg, args.task_id, args.scope)
        session_id = store.create_session(task_id=args.task_id, scope=args.scope, head=ident["git_commit"], fingerprint=ident["truth_fingerprint"]["sha256"], policy_fingerprint=ident["policy_fingerprint"]["sha256"], source_identity_sha256=ident["identity_sha256"], session_id=args.session_id)
        context = resolve_context(cfg, store, task_id=args.task_id, include_fingerprint=True); context["session_id"] = session_id
    if args.json: _json(context)
    else: print(render_context(context) + f"\n\nsession      {session_id}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "continuity"):
        return 2
    cfg = discover(repo)
    with StateStore(repo) as store: value = resolve_context(cfg, store, task_id=args.task_id, include_fingerprint=args.fingerprint)
    if args.write_generated:
        gen = cfg.root / "generated"; gen.mkdir(parents=True, exist_ok=True); atomic_write_json(gen / "CURRENT_CONTEXT.json", value); (gen / "CURRENT_CONTEXT.md").write_text(render_context(value) + "\n", encoding="utf-8")
    if args.json: _json(value)
    else: print(render_context(value))
    return 0


def _session_for_task(store: StateStore, task_id: str, explicit: str | None) -> str | None:
    if explicit: return explicit
    rows = store.open_sessions(task_id)
    return rows[0]["session_id"] if len(rows) == 1 else None


def cmd_state(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "continuity"):
        return 2
    cfg = discover(repo)
    with StateStore(repo) as store, store.transaction():
        if args.state_command == "show":
            _json(store.get_task(args.task_id) if args.task_id else store.active_tasks()); return 0
        task = store.get_task(args.task_id)
        if task is None: raise ValueError(f"unknown task: {args.task_id}")
        if args.state_command == "advance":
            sid = _session_for_task(store, args.task_id, args.session_id)
            required = required_phases_for_scope(cfg.workflow, str(task.get("scope") or ""))
            if args.phase not in required:
                _json({"status": "FAIL", "phase": args.phase, "failures": [f"phase_not_required_for_scope:{task.get('scope')}:{args.phase}"], "required_phases": required}); return 2
            verdict = phase_contract_verdict(cfg, store, task=task, phase=args.phase, session_id=sid)
            if verdict["status"] != "PASS":
                _json(verdict); return 2
            task = workflow_advance(task, cfg.workflow, args.phase, args.next_action)
            if all(phase in task.get("completed", []) for phase in required):
                task["current_phase"] = None
                task["status"] = "READY_TO_FINISH"
                task["next_action"] = args.next_action
            store.upsert_task(task); store.event("PHASE_ADVANCED", {"completed": args.phase, "next_phase": task.get("current_phase"), "next_action": task.get("next_action"), "scope_boundary_reached": task.get("status") == "READY_TO_FINISH"}, session_id=sid, task_id=args.task_id)
        elif args.state_command == "block":
            task = dict(task); task.setdefault("blockers", []).append({"phase": task.get("current_phase"), "reason": args.reason, "at": utc_now()}); task["next_action"] = args.next_action; store.upsert_task(task); store.event("TASK_BLOCKED", {"phase": task.get("current_phase"), "reason": args.reason, "next_action": args.next_action}, task_id=args.task_id)
        elif args.state_command == "finish":
            verdict = workflow_completion_verdict(cfg, store, task_id=args.task_id, session_id=_session_for_task(store, args.task_id, args.session_id))
            if verdict["status"] != "PASS": _json(verdict); return 2
            task = dict(task); task["status"] = "COMPLETE"; task["next_action"] = "complete"; store.upsert_task(task); store.event("TASK_FINISHED", {"completed": task.get("completed", [])}, task_id=args.task_id)
        _json(task)
    return 0


def cmd_authorize(args: argparse.Namespace) -> int:
    repo = _repo(args.repo); cfg = discover(repo); action = HostAction(args.operation, args.target, "high", "cli_authorize")
    with StateStore(repo) as store:
        result = authorize_host_action(cfg, store, action=action, scope=args.scope, task_id=args.task_id, session_id=args.session_id)
        store.event("AUTHORIZATION_DECISION", result, session_id=args.session_id, task_id=args.task_id)
    _json(result); return 0 if result["allowed"] else 3


def _resolve_session(store: StateStore, session_id: str | None) -> dict[str, Any]:
    if session_id:
        rec = store.session(session_id)
        if not rec: raise ValueError(f"unknown session: {session_id}")
        return rec
    rows = store.open_sessions()
    if len(rows) != 1: raise ValueError(f"session_id_required_open_sessions={len(rows)}")
    return rows[0]


def cmd_checkpoint(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "continuity"):
        return 2
    cfg = discover(repo); ident = source_identity(cfg)
    with StateStore(repo) as store:
        rec = _resolve_session(store, args.session_id); payload = {"summary": args.summary, "source_identity": ident, "dirty": bool(status_porcelain(repo))}; store.event("CHECKPOINT_CREATED", payload, session_id=rec["session_id"], task_id=rec["task_id"])
    _json(payload); return 0


def cmd_run(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "continuity"):
        return 2
    cfg = discover(repo); command = list(args.run_command); command = command[1:] if command and command[0] == "--" else command
    with StateStore(repo) as store:
        rec = _resolve_session(store, args.session_id); result = run_check(cfg, store, session_id=rec["session_id"], task_id=rec["task_id"], name=args.name, command=command, timeout=args.timeout, cwd=args.cwd)
    _json(result); return 0 if result["status"] == "PASS" else (1 if result["status"] == "FAIL" else 2)


def _db_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        meta = dict(row.get("metadata") or {})
        out.append({"name": row.get("name"), "status": row.get("status"), "path": row.get("path"), "sha256": row.get("sha256"), "bytes": meta.get("bytes"), "revision": row.get("revision"), "source_identity_sha256": row.get("source_identity_sha256"), "reason": meta.get("reason"), "metadata": meta})
    return out


def cmd_evidence(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "evidence"):
        return 2
    cfg = discover(repo)
    with StateStore(repo) as store:
        if args.evidence_command == "list":
            rows = store.evidence_for_session(args.session_id) if args.session_id else store.evidence_for_task(args.task_id) if args.task_id else []
            _json(rows); return 0
        rec = _resolve_session(store, args.session_id)
        if args.evidence_command == "add":
            test = {"name": args.name, "status": args.status, "evidence": args.path, "reason": args.reason, "revision": args.revision}
            records, _ = prepare_records(cfg, tests=[test], evidence_paths=[args.path] if args.path else []); record_prepared(store, session_id=rec["session_id"], task_id=rec["task_id"], records=records); _json(records[0]); return 0
        rows = _db_evidence(store.evidence_for_session(rec["session_id"])); errors = verify_evidence_records(cfg, rows)
        _json({"status": "PASS" if not errors else "FAIL", "errors": errors, "records": rows}); return 0 if not errors else 2


def _summary(args: argparse.Namespace) -> dict[str, Any]:
    if args.summary_file:
        value = json.loads(Path(args.summary_file).read_text(encoding="utf-8"))
        if not isinstance(value, dict): raise ValueError("summary file must contain a JSON object")
        return value
    return {"summary": args.summary_text or "session closeout", "tests": [], "evidence_paths": [], "risks": [], "next_steps": []}


def _latest_by_name(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in records: latest[str(row.get("name"))] = row
    return list(latest.values())


def cmd_finish(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "continuity"):
        return 2
    cfg = discover(repo); summary = _summary(args); summary.setdefault("tests", []); summary.setdefault("evidence_paths", [])
    mode = args.mode.upper()
    with StateStore(repo) as store, store.transaction():
        rec = _resolve_session(store, args.session_id)
        if rec.get("status") != "OPEN": raise ValueError("session_not_open")
        ident = source_identity(cfg)
        failures: list[str] = []
        if rec.get("start_build_sha256") != build_identity()["sha256"]:
            failures.append("core_build_drift_since_session_start")
        if bool(cfg.evidence.get("rules", {}).get("require_policy_stable", True)) and rec.get("start_policy_fingerprint") != ident["policy_fingerprint"]["sha256"]:
            failures.append("policy_drift_since_session_start")
        failures.extend(exact_closeout_errors(cfg, ident))
        workflow_verdict = {"status": "NOT_REQUIRED", "failures": []}
        if mode == "COMPLETE" and bool(cfg.evidence.get("rules", {}).get("require_workflow_complete", True)):
            workflow_verdict = workflow_completion_verdict(cfg, store, task_id=rec["task_id"], session_id=rec["session_id"])
            failures.extend(workflow_verdict.get("failures", []))
        runtime = run_probes(repo, cfg.runtime, scope=str(rec["scope"]))
        if runtime.get("required_by_scope") and runtime.get("status") != "PASS":
            failures.append(f"required_runtime_not_pass:{runtime.get('status')}")
        # Validate summary evidence without mutating state.
        prepared, _ = prepare_records(cfg, tests=list(summary["tests"]), evidence_paths=list(summary["evidence_paths"]), identity=ident)
        existing = _db_evidence(store.evidence_for_task(rec["task_id"]))
        if mode == "COMPLETE" and bool(cfg.evidence.get("rules", {}).get("require_any_test_for_complete", True)) and not existing and not prepared:
            failures.append("complete_closeout_requires_evidence")
        if failures:
            value = {"status": "BLOCKED", "receipt_type": mode, "failures": failures, "workflow": workflow_verdict, "runtime": runtime, "source_identity": ident}
            _json(value); return 2
        # Only after all trust preconditions pass do we mutate evidence/session state.
        record_prepared(store, session_id=rec["session_id"], task_id=rec["task_id"], records=prepared)
        all_records = _latest_by_name(_db_evidence(store.evidence_for_task(rec["task_id"])))
        evidence_errors = verify_evidence_records(cfg, all_records, current_identity=ident)
        statuses = [str(x.get("status")) for x in all_records]
        if mode == "HANDOFF": closeout_status = "HANDOFF"
        elif evidence_errors: closeout_status = "FAIL"
        elif any(x == "FAIL" for x in statuses): closeout_status = "FAIL"
        elif any(x in {"BLOCKED", "NOT_RUN"} for x in statuses): closeout_status = "BLOCKED"
        elif statuses and all(x == "PASS" for x in statuses): closeout_status = "PASS"
        else: closeout_status = "FAIL"
        chain_ok, bad = store.verify_event_chain()
        if not chain_ok: raise RuntimeError(f"event_chain_invalid:{bad}")
        if mode == "COMPLETE" and closeout_status == "PASS":
            task = store.get_task(rec["task_id"])
            if task:
                task = dict(task); task["status"] = "COMPLETE"; task["current_phase"] = None; task["next_action"] = "complete"; store.upsert_task(task); store.event("TASK_FINISHED", {"completed": task.get("completed", []), "scope": task.get("scope")}, session_id=rec["session_id"], task_id=rec["task_id"])
        store.close_session(rec["session_id"], fingerprint=ident["truth_fingerprint"]["sha256"], end_head=ident["git_commit"], summary=summary, policy_fingerprint=ident["policy_fingerprint"]["sha256"], source_identity_sha256=ident["identity_sha256"], status="CLOSED" if closeout_status in {"PASS", "HANDOFF"} else "CLOSED_FAILED")
        event_head = store.event_chain_head(); chain_ok, bad = store.verify_event_chain()
        payload = {
            "schema": "contextcord-session-receipt-v3",
            "store_id": store.store_id,
            "build_identity": build_identity(),
            "receipt_type": mode,
            "session_id": rec["session_id"], "task_id": rec["task_id"], "scope": rec["scope"],
            "source_identity": ident,
            "summary": summary,
            "evidence_records": all_records,
            "evidence_verdict": {"status": "PASS" if not evidence_errors else "FAIL", "errors": evidence_errors},
            "runtime": runtime,
            "workflow_verdict": workflow_verdict,
            "event_chain_head": event_head,
            "integrity_status": "PASS" if chain_ok else "FAIL",
            "closeout_status": closeout_status,
            "finished_at": utc_now(),
        }
        if mode == "HANDOFF":
            payload["handoff_packet"] = {
                "schema": "contextcord-handoff-continuation-v1",
                "task_id": rec["task_id"],
                "session_id": rec["session_id"],
                "scope": rec["scope"],
                "summary": str(summary.get("summary") or "session handoff")[:2048],
                "next_steps": [str(item)[:512] for item in summary.get("next_steps", []) if str(item)][:32],
                "risks": [str(item)[:512] for item in summary.get("risks", []) if str(item)][:32],
                "source_identity_sha256": ident["identity_sha256"],
            }
        path, sealed = write_sealed_receipt(cfg, store, payload)
        sealed["receipt_path"] = path.relative_to(repo).as_posix()
    _json(sealed)
    return 0 if closeout_status in {"PASS", "HANDOFF"} else 2


def cmd_verify(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "evidence"):
        return 2
    cfg = discover(repo); failures = validate_workflow(cfg.workflow); warnings: list[str] = []
    for rel in cfg.knowledge_entrypoints:
        p = repo / rel
        if not p.is_file() or p.is_symlink(): failures.append(f"knowledge_entrypoint_missing_or_invalid:{rel}")
    profile = "complete" if args.ci or args.profile == "complete" else "handoff" if args.profile == "handoff" else "default"
    current = source_identity(cfg)
    with StateStore(repo) as store:
        eok, bad = store.verify_event_chain()
        if not eok: failures.append(f"event_chain_invalid:{bad}")
        chain = verify_receipt_chain(cfg, store=store)
        receipt_verification = None
        path = None
        receipt = None
        if chain["status"] != "PASS":
            failures.extend(chain["errors"])
        else:
            if profile == "handoff":
                path, receipt = matching_handoff_receipt(cfg, current)
                if receipt is not None:
                    receipt_verification = verify_handoff_receipt(cfg, store, receipt); failures.extend(receipt_verification["failures"])
                else:
                    failures.append("no_handoff_receipt_matches_current_source_identity")
            else:
                path, receipt = matching_complete_receipt(cfg, current)
                if receipt is not None:
                    receipt_verification = verify_receipt(cfg, store, receipt, require_complete=True); failures.extend(receipt_verification["failures"])
                elif profile == "complete":
                    failures.append("no_complete_closeout_receipt_matches_current_source_identity")
    runtime = run_probes(repo, cfg.runtime, scope=receipt.get("scope") if receipt else None)
    if args.require_runtime and runtime["status"] != "PASS": failures.append("required_runtime_provenance_not_pass")
    qualification = None
    if args.qualification_profile:
        qualification = qualification_verify(cfg, commitish="HEAD", profile=args.qualification_profile)
        if qualification["status"] != "PASS": failures.append(f"qualification_profile_not_pass:{args.qualification_profile}")
    value = {
        "status": "PASS" if not failures else "FAIL",
        "profile": profile,
        "required_receipt_states": ["HANDOFF"] if profile == "handoff" else ["COMPLETE"],
        "observed_terminal_state": receipt.get("receipt_type") if receipt else None,
        "repo": str(repo), "head": head(repo), "source_identity": current,
        "matching_receipt": str(path.relative_to(repo)) if path else None,
        "receipt_verification": receipt_verification, "receipt_chain": chain,
        "runtime": runtime, "qualification": qualification, "failures": failures, "warnings": warnings,
    }
    _json(value); return 0 if not failures else 2


def _hook_payload() -> dict[str, Any]:
    try: raw = sys.stdin.read()
    except OSError: raw = ""
    if not raw.strip(): return {}
    try: value = json.loads(raw); return value if isinstance(value, dict) else {}
    except json.JSONDecodeError as exc: raise ValueError("invalid_hook_json") from exc


def _host_session_id(payload: dict[str, Any], host: str) -> str:
    raw = payload.get("session_id") or payload.get("sessionId") or os.environ.get("HARNESS_PLATFORM_SESSION_ID") or "default"
    return f"host-{safe_id(host)}-{safe_id(str(raw))}"


def cmd_hook_start(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "hosts"):
        return 2
    cfg = discover(repo); payload = _hook_payload(); sid = _host_session_id(payload, args.host); ident = source_identity(cfg)
    with StateStore(repo) as store:
        rec = store.session(sid)
        if rec is not None and rec.get("status") != "OPEN":
            raise ValueError("host_session_closed_use_new_platform_session_id")
        if rec is None:
            store.create_session(task_id=f"host:{sid}", scope="hook", head=ident["git_commit"], fingerprint=ident["truth_fingerprint"]["sha256"], policy_fingerprint=ident["policy_fingerprint"]["sha256"], source_identity_sha256=ident["identity_sha256"], session_id=sid)
        tasks = store.active_tasks(); task_id = tasks[0]["task_id"] if len(tasks) == 1 else None; context = resolve_context(cfg, store, task_id=task_id)
    text = render_context(context) + f"\n\ncontextcord_session {sid}\nFor lifecycle handoff use `contextcord finish --mode handoff --session-id {sid} --summary-text ...`. Complete CI closeout requires a real task/workflow/evidence."
    if args.host in {"codex", "qoder", "claude"}: _json({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}})
    else: _json({"host": args.host, "session_id": sid, "additionalContext": text})
    return 0


def cmd_hook_stop(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "hosts"):
        return 2
    cfg = discover(repo); payload = _hook_payload(); sid = _host_session_id(payload, args.host); current = source_identity(cfg); stop_active = bool(payload.get("stop_hook_active") or payload.get("stopHookActive"))
    with StateStore(repo) as store: rec = store.session(sid)
    reason = None
    if rec and rec.get("status") == "OPEN":
        if rec.get("start_policy_fingerprint") != current["policy_fingerprint"]["sha256"]: reason = "policy_drift_since_session_start"
        elif rec.get("start_identity_sha256") != current["identity_sha256"]: reason = "project_identity_changed_without_closeout"
    elif rec and rec.get("finish_identity_sha256") and rec.get("finish_identity_sha256") != current["identity_sha256"]:
        reason = "project_identity_changed_after_closeout"
    blocked = bool(reason) and not stop_active
    if args.host in {"codex", "claude"}:
        if blocked: _json({"decision": "block", "reason": f"ContextCord: {reason}"})
        else: _json({"systemMessage": f"ContextCord {'did not re-block active Stop hook; CI remains authoritative' if stop_active and reason else 'closeout current'} ({sid})"})
        return 0
    if args.host == "qoder":
        if blocked: print(f"ContextCord blocked stop: {reason}", file=sys.stderr); return 2
        _json({"status": "PASS", "session_id": sid, "warning": reason if stop_active else None}); return 0
    _json({"status": "BLOCKED" if blocked else "PASS", "session_id": sid, "reason": reason, "stop_hook_active": stop_active}); return 2 if blocked else 0


def cmd_host_event(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "hosts"):
        return 2
    cfg = discover(repo); payload = _hook_payload(); tool_name = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or ""); tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}; action = classify_tool_call(tool_name, tool_input)
    if not tool_name or not isinstance(tool_input, dict):
        raise ValueError("invalid_host_tool_payload")
    scope = args.scope or os.environ.get("HARNESS_SCOPE"); task_id = args.task_id or os.environ.get("HARNESS_TASK_ID"); sid = args.session_id or _host_session_id(payload, args.host)
    with StateStore(repo) as store:
        decision = authorize_host_action(cfg, store, action=action, scope=scope, task_id=task_id, session_id=sid); store.event("HOST_AUTHORIZATION_DECISION", {"host": args.host, "tool_name": tool_name, **decision}, session_id=sid, task_id=task_id)
    if args.host in {"qoder", "codex", "claude"}:
        code, out, err = qoder_pretool_result(decision)
        if out and args.host == "claude" and decision.get("allowed"):
            out = {}  # Defer to native permissions; never auto-approve via a policy allow.
        if out: _json(out)
        if err: print(err, file=sys.stderr)
        return code
    _json({"host": args.host, **decision}); return 0 if decision.get("allowed") else 3


def cmd_drift(args: argparse.Namespace) -> int:
    repo = _repo(args.repo); cfg = discover(repo); current = policy_fingerprint(repo, cfg.policy_entrypoints); rows = []
    with StateStore(repo) as store:
        for rec in store.open_sessions():
            started = rec.get("start_policy_fingerprint"); rows.append({"session_id": rec["session_id"], "task_id": rec["task_id"], "start_policy_fingerprint": started, "current_policy_fingerprint": current["sha256"], "drifted": bool(started and started != current["sha256"])})
    drifted = [x for x in rows if x["drifted"]]; _json({"status": "DRIFT" if drifted else "PASS", "policy_fingerprint": current, "sessions": rows}); return 2 if drifted else 0


def cmd_lease(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "continuity"):
        return 2
    with StateStore(repo) as store:
        if args.lease_command == "list": _json(store.active_leases()); return 0
        if args.lease_command == "acquire":
            rec = store.session(args.session_id)
            if not rec or rec.get("status") != "OPEN": raise ValueError("lease_requires_open_session")
            result = store.acquire_lease(lease_key=args.key, session_id=args.session_id, task_id=rec["task_id"], ttl_seconds=args.ttl); _json(result); return 0 if result.get("acquired") else 3
        result = store.release_lease(lease_key=args.key, session_id=args.session_id); _json(result); return 0 if result.get("released") else 3


def cmd_events(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "evidence"):
        return 2
    with StateStore(repo) as store:
        if args.verify_chain:
            ok, bad = store.verify_event_chain(); _json({"status": "PASS" if ok else "FAIL", "bad_event": bad, "head": store.event_chain_head()}); return 0 if ok else 2
        _json(store.recent_events(args.limit)); return 0


def cmd_qualification(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "evidence"):
        return 2
    cfg = discover(repo)
    if args.qualification_command == "show":
        from .gitops import resolve_commit
        _json(qualification_read_note(cfg, resolve_commit(repo, args.commit))); return 0
    if args.qualification_command == "record":
        value = qualification_record(cfg, commitish=args.commit, status=args.status, evidence=Path(args.evidence), summary=args.summary, kind=args.kind)
    elif args.qualification_command == "deploy":
        value = qualification_deploy(cfg, commitish=args.commit, status=args.status, environment=args.environment, runtime_revisions=args.runtime_revision, summary=args.summary, evidence_paths=[Path(x) for x in args.evidence])
    else:
        value = qualification_verify(cfg, commitish=args.commit, require_qualified=args.require_qualified, require_deployed=args.require_deployed, environment=args.environment, profile=args.profile); _json(value); return 0 if value["status"] == "PASS" else 2
    _json(value); return 0


def cmd_dual_run(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "evidence"):
        return 2
    cfg = discover(repo)
    if args.dual_command == "record":
        row = dual_record(cfg, task_id=args.task, task_class=args.task_class, legacy_status=args.legacy_status, harness_status=args.harness_status, expected_status=args.expected_status, adjudication=args.adjudication, notes=args.notes, legacy_evidence=args.legacy_evidence, harness_receipt=args.harness_receipt); _json({"status": "PASS", "record": row}); return 0
    value = dual_summary(cfg); _json(value); return 0 if value["status"] == "PASS" else 2


def cmd_receipt(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "evidence"):
        return 2
    cfg = discover(repo)
    with StateStore(repo) as store:
        value = verify_receipt_chain(cfg, store=store)
    _json(value); return 0 if value["status"] == "PASS" else 2


def cmd_identity(args: argparse.Namespace) -> int:
    cfg = discover(_repo(args.repo)); _json(source_identity(cfg, include_files=args.files)); return 0


def cmd_release_identity(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "core"):
        return 2
    cfg = discover(repo); value = collect_release_identity(cfg, scope=args.scope); _json(value); return 0 if value["status"] == "PASS" else 2


def cmd_bundle(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "memory"):
        return 2
    cfg = discover(repo); path = Path(args.path)
    if args.bundle_command == "export":
        value = portable_export(cfg, output=path); _json(value); return 0
    if args.bundle_command == "import":
        value = portable_import(cfg, path=path); _json(value); return 0 if value["status"] == "PASS" else 2
    value = portable_verify(cfg, path=path); _json(value); return 0 if value["status"] == "PASS" else 2


def cmd_memory(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "memory"):
        return 2
    cfg = discover(repo)
    command = args.memory_command
    if command == "export":
        task_id = args.task_id or args.task
        value = export_memory(cfg, task_id=task_id, output=Path(args.out)); _json(value); return 0
    if command == "import":
        value = import_memory(cfg, bundle=Path(args.bundle), dry_run=bool(args.dry_run))
        _json(value); return 0 if value.get("status") == "PASS" else 2
    if command == "inspect":
        manifest, data = inspect_memory_bundle(Path(args.bundle))
        _json({"status": "PASS", "bundle_sha256": manifest["bundle_sha256"], "task_id": manifest["task_id"],
               "object_count": len(manifest.get("objects", [])), "payload_count": len(manifest.get("payloads", [])),
               "members": len(data), "current_qualification": manifest.get("current_qualification")})
        return 0
    if command in {"next", "show"}:
        value = memory_context(cfg, task_id=args.task_id)
        if command == "next" and args.task_id:
            value["next_action"] = value["task"].get("next_action")
            value["handoff_command"] = f"contextcord --repo {repo} memory handoff --task-id {args.task_id} --scope {value['task'].get('scope')}"
        _json(value); return 0
    if command == "handoff":
        ident = source_identity(cfg)
        with StateStore(repo) as store:
            task = store.get_task(args.task_id)
            if task is None:
                raise ValueError(f"unknown task: {args.task_id}")
            with store.transaction():
                session_id = store.create_session(
                    task_id=args.task_id, scope=args.scope or str(task["scope"]), head=ident["git_commit"],
                    fingerprint=ident["truth_fingerprint"]["sha256"], policy_fingerprint=ident["policy_fingerprint"]["sha256"],
                    source_identity_sha256=ident["identity_sha256"], session_id=args.session_id,
                )
        value = memory_context(cfg, task_id=args.task_id); value["session_id"] = session_id; value["continued"] = True
        _json(value); return 0
    if command == "note":
        if args.note_command == "add":
            value = add_note(cfg, task_id=args.task_id, session_id=args.session_id, text=args.text, depends_on=args.depends_on, note_id=args.note_id)
        else:
            value = memory_context(cfg, task_id=args.task_id).get("notes", [])
        _json(value); return 0
    if command == "job":
        if args.job_command != "record":
            raise ValueError("unknown memory job command")
        packet = json.loads(Path(args.packet_file).read_text(encoding="utf-8")) if args.packet_file else json.loads(args.packet)
        value = add_context_job(cfg, task_id=args.task_id, session_id=args.session_id, provider=args.provider, packet=packet, archive_refs=args.archive_ref, job_id=args.job_id)
        _json(value); return 0
    raise ValueError(f"unknown memory command: {command}")


def cmd_adapter(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "hosts"):
        return 2
    if args.adapter_command == "config":
        value = generate_host_config(args.host, repo_path=args.repo_path or args.repo or ".")
        _json(value); return 0
    if args.adapter_command == "capabilities":
        value = adapter_capabilities(args.host) if args.host else adapter_capabilities(); _json({"status": "PASS", "host": args.host, "capabilities": value}); return 0
    if args.adapter_command == "check":
        cfg = discover(repo); requirements = cfg.project.get("adapter_requirements", {}).get(args.scope, {}); value = adapter_check_requirements(args.host, requirements); value["scope"] = args.scope; _json(value); return 0 if value["status"] == "PASS" else 2
    dest = Path(args.destination); dest = dest if dest.is_absolute() else repo / dest; paths = render_adapter(args.host, dest); _json({"host": args.host, "written": [str(p) for p in paths]}); return 0


def cmd_assisted_handoff(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "handoff"):
        return 2
    cfg = discover(repo)
    value = assist_handoff(cfg, task_id=args.task_id, host=args.host, provider=args.provider,
                          confirm=bool(args.yes), session_id=args.session_id)
    _json(value)
    return 0 if value.get("status") in {"AWAITING_CONFIRMATION", "PASS", "SELECT_TASK", "NO_UNFINISHED_TASK"} else 2


def cmd_decision_fabric(args: argparse.Namespace) -> int:
    if not _require_capability(_repo(args.repo), "decision"):
        return 2
    state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("decision_state_must_be_object")
    value = evaluate_decision_fabric(state, provider=args.provider, project_root=str(_repo(args.repo)),
                                     model=args.model, endpoint=args.endpoint, force=bool(args.force))
    if args.out:
        atomic_write_json(Path(args.out).resolve(), value)
    _json(value)
    return 0


def cmd_router(args: argparse.Namespace) -> int:
    if args.router_command == "recommendations":
        repo = _repo(getattr(args, "repo", None))
        if not _require_capability(repo, "router"):
            return 2
        state: dict[str, Any] = {}
        if args.input:
            supplied = json.loads(Path(args.input).read_text(encoding="utf-8"))
            if not isinstance(supplied, dict):
                raise ValueError("router_input_must_be_object")
            state = dict(supplied)
        try:
            cfg, resolved = _feature_resolution(repo)
            with StateStore(repo) as store:
                state.setdefault("local_routes", store.model_outcome_summary())
            provider_cfg = _project_provider_config(cfg.project, "codexradar")
            if "codexradar_prior" not in state:
                state["codexradar_prior"] = load_codexradar_prior(
                    repo,
                    enabled=bool(provider_cfg.get("enabled", False)) and capability_enabled(resolved, "model_intelligence"),
                    url=str(provider_cfg.get("source_url") or "https://api.codexradar.com/api/v1/table?benchmark=deep-swe"),
                    ttl_seconds=int(provider_cfg.get("ttl_seconds", 600)),
                    max_stale_seconds=int(provider_cfg.get("max_stale_seconds", 86400)),
                    timeout_seconds=float(provider_cfg.get("timeout_seconds", 3)),
                )
            if isinstance(state.get("codexradar_prior"), dict):
                state["codexradar_prior"].pop("payload", None)
        except ConfigError:
            state.setdefault("local_routes", [])
        state.setdefault("router_version", "v3")
        value = recommendation_pair(state)
        if args.out:
            atomic_write_json(Path(args.out).resolve(), value)
        _json(value)
        return 0
    if args.router_command == "discover":
        repo = _repo(getattr(args, "repo", None))
        if not _require_capability(repo, "router"):
            return 2
        state: dict[str, Any] = {}
        if args.input:
            state_value = json.loads(Path(args.input).read_text(encoding="utf-8"))
            if not isinstance(state_value, dict):
                raise ValueError("router_input_must_be_object")
            state = dict(state_value)
        try:
            cfg, resolved = _feature_resolution(repo)
            with StateStore(repo) as store:
                state.setdefault("local_routes", store.model_outcome_summary())
            provider_cfg = _project_provider_config(cfg.project, "codexradar")
            radar_enabled = bool(provider_cfg.get("enabled", False)) and capability_enabled(resolved, "model_intelligence")
            prior = state.get("codexradar_prior") if isinstance(state.get("codexradar_prior"), dict) else load_codexradar_prior(
                repo,
                enabled=radar_enabled,
                url=str(provider_cfg.get("source_url") or "https://api.codexradar.com/api/v1/table?benchmark=deep-swe"),
                ttl_seconds=int(provider_cfg.get("ttl_seconds", 600)),
                max_stale_seconds=int(provider_cfg.get("max_stale_seconds", 86400)),
                timeout_seconds=float(provider_cfg.get("timeout_seconds", 3)),
            )
            if isinstance(prior, dict):
                prior.pop("payload", None)
                state["codexradar_prior"] = prior
        except ConfigError:
            prior = state.get("codexradar_prior") if isinstance(state.get("codexradar_prior"), dict) else None
        value = discover_codex_execution_routes(state, snapshot=prior if isinstance(prior, dict) else None, probe=bool(args.probe), repo=repo)
        if args.out:
            atomic_write_json(Path(args.out).resolve(), value)
        _json(value)
        return 0
    if args.router_command == "calibrate":
        repo = _repo(getattr(args, "repo", None))
        if not _require_capability(repo, "router"):
            return 2
        from .calibration import run_adaptive_calibration
        if args.discovery:
            discovery = json.loads(Path(args.discovery).read_text(encoding="utf-8"))
        else:
            discovery = discover_codex_execution_routes({"role": "implementer"}, probe=False, repo=repo)
        if not isinstance(discovery, dict):
            raise ValueError("calibration_discovery_must_be_object")
        routes = discovery.get("execution_routes") if isinstance(discovery.get("execution_routes"), list) else []
        try:
            cfg = discover(repo)
            identity_sha = source_identity(cfg)["identity_sha256"]
        except ConfigError:
            cfg = None
            identity_sha = None
        def record(route: dict[str, Any], role: str, result: dict[str, Any]) -> None:
            model = str(route.get("requested_model") or route.get("model_id") or "")
            effort = str(route.get("requested_effort") or route.get("reasoning_effort") or "").casefold()
            evidence = "confirmed" if str(route.get("capability_state") or "").upper() == "CONFIRMED" else "configured_explicit"
            with StateStore(repo) as store:
                store.record_model_outcome(
                    task_class=role, role=role, model_id=model, reasoning_effort=effort,
                    verifier_pass=bool(result.get("verifier_pass")), identity_evidence=evidence,
                    attempts=1, context_profile="bounded", source_identity_sha256=identity_sha,
                    verifier_id=f"calibration-{role}", elapsed_ms=result.get("latency_ms"),
                    input_tokens=result.get("input_tokens"), output_tokens=result.get("output_tokens"),
                    observed_subscription_quota_delta=result.get("observed_subscription_quota_delta"),
                    api_equivalent_usd=result.get("api_equivalent_usd"),
                    external_prior_source="Codex Radar / Distributed Radar" if discovery.get("analysis_route_count") else None,
                )
        value = run_adaptive_calibration(routes, record_outcome=record, round_id=args.round_id)
        value["status"] = "PASS" if routes else "BLOCKED_HOST"
        if args.out:
            atomic_write_json(Path(args.out).resolve(), value)
        _json(value)
        return 0
    if args.router_command != "shadow":
        raise ValueError(f"unknown router command: {args.router_command}")
    repo = _repo(getattr(args, "repo", None))
    if not _require_capability(repo, "router"):
        return 2
    state = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("router_input_must_be_object")
    # Keep the legacy shadow contract for legacy inputs. Explicit v2 inputs
    # remain read-only compatibility; new route requests use the active v3
    # Catalog and receipt.
    router_version = str(state.get("router_version") or "").casefold()
    route_shaped = "available_routes" in state or "analysis_routes" in state or any(
        isinstance(row, dict) and "reasoning_effort" in row for row in state.get("routes", [])
    )
    uses_v2_routes = (
        router_version == "v2"
        or (not router_version and route_shaped)
    )
    uses_v3_routes = router_version == "v3" or (
        not uses_v2_routes
        and any(key in state for key in ("role", "requested_role", "failure_cost", "codexradar_prior", "analysis_routes"))
    )
    if uses_v2_routes or uses_v3_routes:
        state = dict(state)
        try:
            cfg, resolved = _feature_resolution(repo)
            provider_cfg = _project_provider_config(cfg.project, "codexradar")
            with StateStore(repo) as store:
                local_routes = store.model_outcome_summary()
            if "local_routes" not in state:
                state["local_routes"] = local_routes
        except ConfigError:
            provider_cfg = {}
            resolved = {"effective": []}
        codexradar = state.get("codexradar")
        if not isinstance(codexradar, dict):
            codexradar = {}
        radar_enabled = bool(codexradar.get("enabled", provider_cfg.get("enabled", False)))
        radar_enabled = radar_enabled and capability_enabled(resolved, "model_intelligence")
        prior_options: dict[str, Any] = {
            "enabled": radar_enabled,
            "ttl_seconds": int(provider_cfg.get("ttl_seconds", 600)),
            "max_stale_seconds": int(provider_cfg.get("max_stale_seconds", 86400)),
            "timeout_seconds": float(provider_cfg.get("timeout_seconds", 3)),
        }
        url = codexradar.get("url") or provider_cfg.get("source_url")
        if isinstance(url, str) and url:
            prior_options["url"] = url
        supplied_prior = state.get("codexradar_prior")
        if isinstance(supplied_prior, dict):
            prior = dict(supplied_prior)
        else:
            prior = load_codexradar_prior(repo, **prior_options)
        # The raw payload is never added to the route receipt.
        prior.pop("payload", None)
        state["codexradar_prior"] = prior
        state.setdefault("external_prior_status", prior.get("status", "UNAVAILABLE"))
        if uses_v3_routes:
            jev_provider = None
            provider_name = str(state.get("provider") or state.get("jev_provider") or "").casefold()
            jev_cfg = _project_provider_config(cfg.project, "jev") if "cfg" in locals() else {}
            if (
                provider_name == "jev_api"
                or bool(jev_cfg.get("enabled", False))
                or state.get("jev_enabled") is True
                or capability_enabled(resolved, "jev")
            ):
                from .jev_provider import JevApiDecisionProvider
                jev_provider = JevApiDecisionProvider(
                    project_root=repo,
                    model=str(state.get("jev_model") or jev_cfg.get("model") or "jev-latest"),
                    endpoint=str(state.get("jev_endpoint") or jev_cfg.get("endpoint") or "https://api.typesafe.ai"),
                    max_retries=0,
                )
            state["router_version"] = "v3"
            value = model_route_decision_v3(state, mode=state.get("mode", "SHADOW"), jev_provider=jev_provider)
        else:
            value = model_route_decision(state, mode=state.get("mode", "SHADOW"))
    else:
        value = shadow_route(state)
    if args.out:
        atomic_write_json(Path(args.out).resolve(), value)
    _json(value)
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    value = migrate_state(_repo(args.repo), apply=bool(args.apply))
    _json(value)
    return 0 if value.get("status") in {"DRY_RUN", "PLANNED", "RECORDED", "NOOP", "NOT_APPLICABLE"} else 2


def cmd_closeout(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    if not _require_capability(repo, "closeout"):
        return 2
    cfg = discover(repo)
    value = run_closeout(cfg, summary_path=Path(args.summary_file).resolve() if args.summary_file else None,
                         summary_text=args.summary_text, task_id=args.task_id, session_id=args.session_id,
                         update_memory=bool(args.update_memory), update_docs=bool(args.update_docs),
                         architecture=args.architecture)
    _json(value)
    return 0 if value.get("status") in {"RECORDED", "NOOP"} else 2


def cmd_adapters(args: argparse.Namespace) -> int:
    from .adapter_lab import certify_manifest, discover_manifests, init_manifest, load_manifest, probe_manifest, render_manifest, validate_manifest

    command = args.adapters_command
    repo = _repo(args.repo)
    if command == "list":
        _json({"status": "PASS", "manifests": discover_manifests(Path(args.directory) if args.directory else None)}); return 0
    if command == "init":
        output = Path(args.out) if args.out else repo / "support" / "adapters" / f"{args.id}.adapter.json"
        _json(init_manifest(args.id, output.resolve(), display_name=args.display_name, force=bool(args.force))); return 0
    value = load_manifest(Path(args.manifest).resolve())
    if command == "validate":
        result = validate_manifest(value); _json(result); return 0 if result["status"] == "PASS" else 2
    if command == "render":
        result = render_manifest(value, output=Path(args.out).resolve(), repo=repo, force=bool(args.force)); _json(result); return 0 if result["status"] == "PASS" else 2
    if command == "probe":
        result = probe_manifest(value, repo=repo, execute=bool(args.execute)); _json(result); return 0 if result["status"] in {"PASS", "PARTIAL", "NOT_RUN_USER_APPROVAL"} else 2
    if command == "certify":
        fixture = Path(args.fixture).resolve() if args.fixture else None
        result = certify_manifest(value, repo=repo, execute=bool(args.execute), fixture=fixture); _json(result); return 0 if result["status"] in {"PASS", "PARTIAL"} else 2
    raise ValueError(f"unknown adapters command: {command}")


def cmd_replay(args):
    if not _require_capability(_repo(args.repo), "evidence"):
        return 2
    from .replay import replay
    result = replay(_repo(args.repo), task_id=args.task_id, after=args.after, limit=args.limit)
    _json(result)
    return 0 if result["status"] == "PASS" else 2


def cmd_mcp(args):
    if not _require_capability(_repo(args.repo), "mcp"):
        return 2
    from .mcp import serve
    return serve(_repo(args.repo), allow_mutations=args.allow_mutations)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="contextcord", description="ContextCord: portable engineering continuity for coding agents")
    p.add_argument("--repo", default=None, help="Repository path; defaults to current Git repository")
    sub = p.add_subparsers(dest="command", required=True)
    f = sub.add_parser("feature", help="list and configure runtime capabilities")
    f.add_argument("--repo", dest="repo", default=argparse.SUPPRESS)
    fs = f.add_subparsers(dest="feature_command", required=True)
    x = fs.add_parser("list"); x.set_defaults(func=cmd_feature)
    x = fs.add_parser("modules", help="show the product-module projection derived from SPECS"); x.set_defaults(func=cmd_feature)
    x = fs.add_parser("status"); x.add_argument("capability"); x.set_defaults(func=cmd_feature)
    x = fs.add_parser("enable"); x.add_argument("value"); x.set_defaults(func=cmd_feature)
    x = fs.add_parser("disable"); x.add_argument("value"); x.set_defaults(func=cmd_feature)
    x = fs.add_parser("profile"); x.add_argument("value"); x.set_defaults(func=cmd_feature)
    pv = sub.add_parser("provider", help="inspect optional providers without exposing secrets")
    pv.add_argument("--repo", dest="repo", default=argparse.SUPPRESS)
    ps = pv.add_subparsers(dest="provider_command", required=True)
    x = ps.add_parser("list"); x.set_defaults(func=cmd_provider)
    j = ps.add_parser("jev")
    js = j.add_subparsers(dest="jev_command", required=True)
    x = js.add_parser("status"); x.add_argument("--json", action="store_true"); x.set_defaults(func=cmd_provider, provider="jev", provider_command="status")
    x = js.add_parser("doctor"); x.add_argument("--live", action="store_true"); x.add_argument("--json", action="store_true"); x.set_defaults(func=cmd_provider, provider="jev", provider_command="doctor")
    mi = sub.add_parser("model-intelligence", help="read-only model-quality priors")
    mi.add_argument("--repo", dest="repo", default=argparse.SUPPRESS)
    mis = mi.add_subparsers(dest="model_intelligence_command", required=True)
    x = mis.add_parser("status"); x.add_argument("--json", action="store_true"); x.set_defaults(func=cmd_model_intelligence)
    cr = mis.add_parser("codexradar")
    crs = cr.add_subparsers(dest="codexradar_command", required=True)
    x = crs.add_parser("snapshot"); x.add_argument("--refresh", action="store_true"); x.add_argument("--json", action="store_true"); x.set_defaults(func=cmd_model_intelligence)
    s = sub.add_parser("mcp"); s.add_argument("--allow-mutations", action="store_true"); s.set_defaults(func=cmd_mcp)
    s = sub.add_parser("replay"); s.add_argument("--task-id"); s.add_argument("--after", type=int, default=0); s.add_argument("--limit", type=int, default=1000); s.set_defaults(func=cmd_replay)
    s = sub.add_parser("handoff", help="Assisted Handoff preview/confirmation")
    s.add_argument("--repo", dest="repo", default=argparse.SUPPRESS)
    s.add_argument("--assist", action="store_true", help="use the bounded Assisted Handoff facade")
    s.add_argument("--task-id"); s.add_argument("--host"); s.add_argument("--provider", choices=["deterministic", "jev_api"], default="deterministic")
    s.add_argument("--session-id"); s.add_argument("--yes", action="store_true", help="confirm creation of one local session and context job")
    s.set_defaults(func=cmd_assisted_handoff)
    d = sub.add_parser("decision", help="evaluate a Decision Fabric state")
    d.add_argument("decision_command", choices=["fabric"]); d.add_argument("--state-file", required=True); d.add_argument("--provider", choices=["deterministic", "jev_api"], default="deterministic"); d.add_argument("--model"); d.add_argument("--endpoint"); d.add_argument("--out"); d.add_argument("--force", action="store_true"); d.set_defaults(func=cmd_decision_fabric)
    j = sub.add_parser("jev", help="Decision Fabric alias")
    j.add_argument("jev_command", choices=["fabric"]); j.add_argument("--state-file", required=True); j.add_argument("--provider", choices=["deterministic", "jev_api"], default="deterministic"); j.add_argument("--model"); j.add_argument("--endpoint"); j.add_argument("--out"); j.add_argument("--force", action="store_true"); j.set_defaults(func=cmd_decision_fabric)
    r = sub.add_parser("router", aliases=["routing", "route"], help="Jev typed routing and bounded execution-route discovery")
    r.add_argument("--repo", dest="repo", default=argparse.SUPPRESS)
    rs = r.add_subparsers(dest="router_command", required=True)
    x = rs.add_parser("discover", help="discover at most five explicit Codex execution capabilities")
    x.add_argument("--input"); x.add_argument("--probe", action="store_true"); x.add_argument("--out"); x.set_defaults(func=cmd_router)
    x = rs.add_parser("calibrate", help="run bounded Explorer/Implementer/Reviewer calibration")
    x.add_argument("--discovery"); x.add_argument("--round-id", default="0.6.2a1-calibration"); x.add_argument("--out"); x.set_defaults(func=cmd_router)
    x = rs.add_parser("recommendations", help="compare Radar-only and Radar plus local outcome recommendations")
    x.add_argument("--input"); x.add_argument("--out"); x.set_defaults(func=cmd_router)
    x = rs.add_parser("shadow", help="build eligible set and record a non-executing shadow receipt")
    x.add_argument("--input", required=True); x.add_argument("--out"); x.set_defaults(func=cmd_router)
    o = rs.add_parser("outcomes", help="local model-route outcome ledger")
    osub = o.add_subparsers(dest="outcome_command", required=True)
    for command in ("summary", "show"):
        x = osub.add_parser(command); x.add_argument("--model"); x.add_argument("--effort"); x.add_argument("--role"); x.add_argument("--task-class", dest="task_class")
        if command == "show": x.add_argument("--limit", type=int, default=1000)
        x.set_defaults(func=cmd_router_outcomes)
    x = osub.add_parser("record")
    x.add_argument("--task-class", required=True); x.add_argument("--role", required=True); x.add_argument("--model", required=True)
    x.add_argument("--effort", required=True, choices=["none", "low", "medium", "high", "xhigh", "max"])
    x.add_argument("--identity-evidence", choices=["confirmed", "configured_explicit", "host_only"], default="confirmed")
    x.add_argument("--verifier-pass", action="store_true"); x.add_argument("--attempts", type=int, default=1)
    x.add_argument("--context-profile"); x.add_argument("--verifier-id"); x.add_argument("--elapsed-ms", type=float)
    x.add_argument("--input-tokens", type=int); x.add_argument("--output-tokens", type=int)
    x.add_argument("--quota-delta", type=float); x.add_argument("--api-equivalent-usd", type=float)
    x.add_argument("--external-prior-source"); x.add_argument("--external-prior-age-seconds", type=float)
    x.add_argument("--receipt-sha256", dest="receipt_sha256"); x.add_argument("--task-id")
    x.set_defaults(func=cmd_router_outcomes)
    s=sub.add_parser("init"); s.add_argument("--profile", choices=sorted(PROFILES), default="generic"); s.add_argument("--state-dir", choices=[".contextcord"], default=None, help="state directory; ContextCord defaults to .contextcord"); s.add_argument("--force", action="store_true"); s.set_defaults(func=cmd_init)
    s=sub.add_parser("migrate", help="plan or apply an explicit .harness to .contextcord migration"); s.add_argument("--apply", action="store_true", help="copy with backup and equality verification"); s.add_argument("--dry-run", action="store_true", help="show the migration plan (default)"); s.set_defaults(func=cmd_migrate)
    s=sub.add_parser("closeout", help="single idempotent state/memory/docs/architecture closeout facade"); s.add_argument("--summary-file"); s.add_argument("--summary-text"); s.add_argument("--task-id"); s.add_argument("--session-id"); s.add_argument("--update-memory", action="store_true"); s.add_argument("--update-docs", action="store_true"); s.add_argument("--architecture", choices=["auto", "if-changed", "never"], default="auto"); s.set_defaults(func=cmd_closeout)
    s=sub.add_parser("doctor"); s.set_defaults(func=cmd_doctor)
    s=sub.add_parser("identity"); s.add_argument("--files", action="store_true"); s.set_defaults(func=cmd_identity)
    s=sub.add_parser("release-identity"); s.add_argument("--scope"); s.set_defaults(func=cmd_release_identity)
    b=sub.add_parser("bundle"); bs=b.add_subparsers(dest="bundle_command", required=True)
    x=bs.add_parser("export"); x.add_argument("--path", required=True); x.set_defaults(func=cmd_bundle)
    x=bs.add_parser("import"); x.add_argument("--path", required=True); x.set_defaults(func=cmd_bundle)
    x=bs.add_parser("verify"); x.add_argument("--path", required=True); x.set_defaults(func=cmd_bundle)
    memory=sub.add_parser("memory", help="portable live Task/Session/Note memory")
    memory.add_argument("--repo", dest="repo", default=argparse.SUPPRESS, help="target repository path (may also be placed before memory)")
    ms=memory.add_subparsers(dest="memory_command", required=True)
    x=ms.add_parser("export"); x.add_argument("--task-id"); x.add_argument("--task"); x.add_argument("--out", required=True); x.set_defaults(func=cmd_memory)
    x=ms.add_parser("import"); x.add_argument("--bundle", required=True); x.add_argument("--dry-run", action="store_true"); x.set_defaults(func=cmd_memory)
    x=ms.add_parser("inspect"); x.add_argument("--bundle", required=True); x.set_defaults(func=cmd_memory)
    x=ms.add_parser("next"); x.add_argument("--task-id"); x.set_defaults(func=cmd_memory)
    x=ms.add_parser("show"); x.add_argument("--task-id", required=True); x.set_defaults(func=cmd_memory)
    x=ms.add_parser("handoff"); x.add_argument("--task-id", required=True); x.add_argument("--scope"); x.add_argument("--session-id"); x.set_defaults(func=cmd_memory)
    note=ms.add_parser("note"); ns=note.add_subparsers(dest="note_command", required=True)
    x=ns.add_parser("add"); x.add_argument("--task-id", required=True); x.add_argument("--session-id"); x.add_argument("--text", required=True); x.add_argument("--depends-on", action="append", default=[]); x.add_argument("--note-id"); x.set_defaults(func=cmd_memory)
    x=ns.add_parser("list"); x.add_argument("--task-id", required=True); x.set_defaults(func=cmd_memory)
    job=ms.add_parser("job"); js=job.add_subparsers(dest="job_command", required=True)
    x=js.add_parser("record"); x.add_argument("--task-id", required=True); x.add_argument("--session-id"); x.add_argument("--provider", required=True); source=x.add_mutually_exclusive_group(required=True); source.add_argument("--packet-file"); source.add_argument("--packet"); x.add_argument("--archive-ref", action="append", default=[]); x.add_argument("--job-id"); x.set_defaults(func=cmd_memory)
    s=sub.add_parser("start"); s.add_argument("--task-id", required=True); s.add_argument("--scope", required=True); s.add_argument("--session-id"); s.add_argument("--json", action="store_true"); s.add_argument("--allow-doctor-warnings", action="store_true"); s.set_defaults(func=cmd_start)
    s=sub.add_parser("context"); s.add_argument("--task-id"); s.add_argument("--json", action="store_true"); s.add_argument("--fingerprint", action="store_true"); s.add_argument("--write-generated", action="store_true"); s.set_defaults(func=cmd_context)
    state=sub.add_parser("state"); ss=state.add_subparsers(dest="state_command", required=True)
    x=ss.add_parser("show"); x.add_argument("--task-id"); x.set_defaults(func=cmd_state)
    x=ss.add_parser("advance"); x.add_argument("--task-id", required=True); x.add_argument("--phase", required=True); x.add_argument("--next-action", required=True); x.add_argument("--session-id"); x.set_defaults(func=cmd_state)
    x=ss.add_parser("block"); x.add_argument("--task-id", required=True); x.add_argument("--reason", required=True); x.add_argument("--next-action", required=True); x.set_defaults(func=cmd_state)
    x=ss.add_parser("finish"); x.add_argument("--task-id", required=True); x.add_argument("--session-id"); x.set_defaults(func=cmd_state)
    s=sub.add_parser("authorize"); s.add_argument("--scope", required=True); s.add_argument("--operation", required=True); s.add_argument("--target"); s.add_argument("--task-id"); s.add_argument("--session-id"); s.set_defaults(func=cmd_authorize)
    s=sub.add_parser("checkpoint"); s.add_argument("--session-id"); s.add_argument("--summary", required=True); s.set_defaults(func=cmd_checkpoint)
    s=sub.add_parser("run"); s.add_argument("--session-id"); s.add_argument("--name", required=True); s.add_argument("--timeout", type=float); s.add_argument("--cwd"); s.add_argument("run_command", nargs=argparse.REMAINDER); s.set_defaults(func=cmd_run)
    ev=sub.add_parser("evidence"); es=ev.add_subparsers(dest="evidence_command", required=True)
    x=es.add_parser("add"); x.add_argument("--session-id"); x.add_argument("--name", required=True); x.add_argument("--status", choices=["PASS","FAIL","BLOCKED","NOT_RUN"], required=True); x.add_argument("--path"); x.add_argument("--reason"); x.add_argument("--revision"); x.set_defaults(func=cmd_evidence)
    x=es.add_parser("list"); x.add_argument("--session-id"); x.add_argument("--task-id"); x.set_defaults(func=cmd_evidence)
    x=es.add_parser("verify"); x.add_argument("--session-id"); x.set_defaults(func=cmd_evidence)
    s=sub.add_parser("finish"); s.add_argument("--session-id"); s.add_argument("--mode", choices=["complete","handoff"], default="complete"); g=s.add_mutually_exclusive_group(required=True); g.add_argument("--summary-file"); g.add_argument("--summary-text"); s.set_defaults(func=cmd_finish)
    s=sub.add_parser("verify"); s.add_argument("--ci", action="store_true"); s.add_argument("--profile", choices=["handoff", "complete"]); s.add_argument("--require-runtime", action="store_true"); s.add_argument("--qualification-profile"); s.set_defaults(func=cmd_verify)
    s=sub.add_parser("hook-start"); s.add_argument("--host", default="generic"); s.set_defaults(func=cmd_hook_start)
    s=sub.add_parser("hook-stop"); s.add_argument("--host", default="generic"); s.set_defaults(func=cmd_hook_stop)
    s=sub.add_parser("host-event"); s.add_argument("--host", required=True); s.add_argument("--event", choices=["pre-tool-use"], required=True); s.add_argument("--scope"); s.add_argument("--task-id"); s.add_argument("--session-id"); s.set_defaults(func=cmd_host_event)
    s=sub.add_parser("drift"); s.set_defaults(func=cmd_drift)
    l=sub.add_parser("lease"); ls=l.add_subparsers(dest="lease_command", required=True)
    x=ls.add_parser("list"); x.set_defaults(func=cmd_lease)
    x=ls.add_parser("acquire"); x.add_argument("--key", required=True); x.add_argument("--session-id", required=True); x.add_argument("--ttl", type=int, default=900); x.set_defaults(func=cmd_lease)
    x=ls.add_parser("release"); x.add_argument("--key", required=True); x.add_argument("--session-id", required=True); x.set_defaults(func=cmd_lease)
    s=sub.add_parser("events"); s.add_argument("--limit", type=int, default=50); s.add_argument("--verify-chain", action="store_true"); s.set_defaults(func=cmd_events)
    q=sub.add_parser("qualification"); qs=q.add_subparsers(dest="qualification_command", required=True)
    x=qs.add_parser("show"); x.add_argument("--commit", default="HEAD"); x.set_defaults(func=cmd_qualification)
    x=qs.add_parser("record"); x.add_argument("--commit", default="HEAD"); x.add_argument("--kind", default="review"); x.add_argument("--status", choices=["PASS","FAIL","BLOCKED","NOT_RUN"], required=True); x.add_argument("--evidence", required=True); x.add_argument("--summary", default=""); x.set_defaults(func=cmd_qualification)
    x=qs.add_parser("deploy"); x.add_argument("--commit", default="HEAD"); x.add_argument("--status", choices=["PASS","FAIL","ROLLED_BACK"], required=True); x.add_argument("--environment", required=True); x.add_argument("--runtime-revision", action="append", required=True); x.add_argument("--evidence", action="append", default=[]); x.add_argument("--summary", default=""); x.set_defaults(func=cmd_qualification)
    x=qs.add_parser("verify"); x.add_argument("--commit", default="HEAD"); x.add_argument("--profile"); x.add_argument("--require-qualified", action="store_true"); x.add_argument("--require-deployed", action="store_true"); x.add_argument("--environment"); x.set_defaults(func=cmd_qualification)
    d=sub.add_parser("dual-run"); ds=d.add_subparsers(dest="dual_command", required=True)
    x=ds.add_parser("record"); x.add_argument("--task", required=True); x.add_argument("--task-class", required=True); x.add_argument("--legacy-status", choices=sorted(["PASS","FAIL","BLOCKED","NOT_RUN"]), required=True); x.add_argument("--harness-status", choices=sorted(["PASS","FAIL","BLOCKED","NOT_RUN"]), required=True); x.add_argument("--expected-status", choices=sorted(["PASS","FAIL","BLOCKED","NOT_RUN"]), required=True); x.add_argument("--adjudication", choices=sorted(["BOTH_CORRECT","LEGACY_CORRECT","HARNESS_CORRECT","BOTH_WRONG","UNRESOLVED"]), required=True); x.add_argument("--notes", default=""); x.add_argument("--legacy-evidence"); x.add_argument("--harness-receipt"); x.set_defaults(func=cmd_dual_run)
    x=ds.add_parser("summary"); x.set_defaults(func=cmd_dual_run)
    s=sub.add_parser("receipt"); s.add_argument("--verify-chain", action="store_true"); s.set_defaults(func=cmd_receipt)
    a=sub.add_parser("adapter"); aa=a.add_subparsers(dest="adapter_command", required=True)
    x=aa.add_parser("render"); x.add_argument("--host", choices=["codex","qoder","opencode","deepseek","claude","cursor","workbuddy","generic"], required=True); x.add_argument("--destination", required=True); x.set_defaults(func=cmd_adapter)
    x=aa.add_parser("capabilities"); x.add_argument("--host", choices=["codex","qoder","opencode","deepseek","claude","cursor","workbuddy","generic"]); x.set_defaults(func=cmd_adapter)
    x=aa.add_parser("check"); x.add_argument("--host", choices=["codex","qoder","opencode","deepseek","claude","cursor","workbuddy","generic"], required=True); x.add_argument("--scope", required=True); x.set_defaults(func=cmd_adapter)
    x=aa.add_parser("config"); x.add_argument("--host", choices=["codex","qoder","opencode","claude","cursor","workbuddy","generic"], required=True); x.add_argument("--repo-path"); x.set_defaults(func=cmd_adapter)
    a=sub.add_parser("adapters", help="manifest-driven Bring Your Own Host Adapter Lab")
    aa=a.add_subparsers(dest="adapters_command", required=True)
    x=aa.add_parser("list"); x.add_argument("--directory"); x.set_defaults(func=cmd_adapters)
    x=aa.add_parser("init"); x.add_argument("id"); x.add_argument("--display-name"); x.add_argument("--out"); x.add_argument("--force", action="store_true"); x.set_defaults(func=cmd_adapters)
    x=aa.add_parser("validate"); x.add_argument("manifest"); x.set_defaults(func=cmd_adapters)
    x=aa.add_parser("render"); x.add_argument("manifest"); x.add_argument("--out", required=True); x.add_argument("--force", action="store_true"); x.set_defaults(func=cmd_adapters)
    x=aa.add_parser("probe"); x.add_argument("manifest"); x.add_argument("--execute", action="store_true"); x.set_defaults(func=cmd_adapters)
    x=aa.add_parser("certify"); x.add_argument("manifest"); x.add_argument("--fixture"); x.add_argument("--execute", action="store_true"); x.set_defaults(func=cmd_adapters)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(); args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except CapabilityConfigError as exc:
        _json({"status": "CONFIG_ERROR", "code": exc.code, "error": str(exc), "details": exc.details})
        return 2
    except (ConfigError, ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        _json({"status": "ERROR", "error": str(exc)}); return 2


if __name__ == "__main__":
    raise SystemExit(main())
