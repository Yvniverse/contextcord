from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import HarnessConfig
from .gitops import head
from .identity import source_identity
from .store import StateStore
from .util import ensure_repo_path, sha256_file

ALLOWED_STATUS = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}


def _identity_binding(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": identity.get("mode"),
        "git_commit": identity.get("git_commit"),
        "truth_sha256": identity.get("truth_fingerprint", {}).get("sha256"),
        "policy_sha256": identity.get("policy_fingerprint", {}).get("sha256"),
        "memory_sha256": identity.get("memory_fingerprint", {}).get("sha256"),
    }


def resolve_evidence_path(cfg: HarnessConfig, raw: str, *, must_exist: bool = True) -> tuple[Path, str]:
    allow_external = bool(cfg.evidence.get("rules", {}).get("allow_external_paths", False))
    path, stored = ensure_repo_path(cfg.repo, Path(raw), label="evidence", allow_external=allow_external)
    if must_exist and not path.is_file():
        raise ValueError(f"evidence_missing:{raw}")
    if path.is_symlink():
        raise ValueError(f"evidence_symlink_forbidden:{raw}")
    return path, stored


def prepare_records(
    cfg: HarnessConfig,
    *,
    tests: list[dict[str, Any]],
    evidence_paths: list[str],
    identity: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate evidence without mutating the SQLite store.

    This two-phase design prevents failed closeout attempts from partially adding
    evidence before another trust invariant (workflow/policy/identity) rejects the
    closeout.
    """
    rules = cfg.evidence.get("rules", {})
    require_file_for_pass = bool(rules.get("require_file_for_pass", True))
    exact_revision = bool(rules.get("exact_revision_required", True))
    identity = identity or source_identity(cfg)
    current_head = str(identity["git_commit"])
    identity_hash = str(identity["identity_sha256"])

    listed: dict[str, dict[str, Any]] = {}
    refs: list[dict[str, Any]] = []
    for raw in evidence_paths:
        p, stored = resolve_evidence_path(cfg, str(raw))
        if stored in listed:
            continue
        row = {"path": stored, "sha256": sha256_file(p), "bytes": p.stat().st_size}
        listed[stored] = row; refs.append(row)

    records: list[dict[str, Any]] = []
    for item in tests:
        status = str(item.get("status", "")).upper()
        name = str(item.get("name") or "unnamed")
        if status not in ALLOWED_STATUS:
            raise ValueError(f"invalid_test_status:{name}:{status}")
        evidence = item.get("evidence")
        stored_evidence: str | None = None
        ref: dict[str, Any] | None = None
        if evidence:
            _, stored_evidence = resolve_evidence_path(cfg, str(evidence))
            ref = listed.get(stored_evidence)
            if ref is None:
                raise ValueError(f"test_evidence_not_listed:{evidence}")
        if status == "PASS" and require_file_for_pass and not evidence:
            raise ValueError(f"PASS_requires_evidence:{name}")
        if status != "PASS" and not item.get("reason"):
            raise ValueError(f"nonpass_requires_reason:{name}")
        revision = str(item.get("revision") or current_head)
        if status == "PASS" and exact_revision and revision != current_head:
            raise ValueError(f"evidence_revision_mismatch:{name}:{revision}!={current_head}")
        if status == "PASS" and identity.get("mode") == "exact_commit" and identity.get("dirty_truth"):
            raise ValueError(f"exact_identity_evidence_requires_clean_truth:{name}")
        metadata = dict(item.get("metadata") or {})
        metadata["source_identity"] = _identity_binding(identity)
        records.append({
            "name": name,
            "status": status,
            "path": stored_evidence,
            "sha256": ref.get("sha256") if ref else None,
            "bytes": ref.get("bytes") if ref else None,
            "revision": revision,
            "source_identity_sha256": identity_hash,
            "reason": item.get("reason"),
            "metadata": metadata,
        })
    return records, refs


def record_prepared(store: StateStore, *, session_id: str, task_id: str, records: list[dict[str, Any]]) -> None:
    for row in records:
        metadata = dict(row.get("metadata") or {})
        metadata.update({"reason": row.get("reason"), "bytes": row.get("bytes")})
        store.add_evidence(
            session_id=session_id,
            task_id=task_id,
            name=str(row["name"]),
            status=str(row["status"]),
            path=row.get("path"),
            sha256=row.get("sha256"),
            revision=row.get("revision"),
            source_identity_sha256=row.get("source_identity_sha256"),
            metadata=metadata,
        )


def validate_and_record(store: StateStore, repo: Path, *, session_id: str, task_id: str, tests: list[dict[str, Any]], evidence_paths: list[str], evidence_cfg: dict[str, Any], cfg: HarnessConfig | None = None) -> list[dict[str, Any]]:
    """Compatibility wrapper for v0.2 callers."""
    if cfg is None:
        from .config import discover
        cfg = discover(repo)
    records, refs = prepare_records(cfg, tests=tests, evidence_paths=evidence_paths)
    record_prepared(store, session_id=session_id, task_id=task_id, records=records)
    return refs


def verify_evidence_records(cfg: HarnessConfig, records: list[dict[str, Any]], *, current_identity: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    current_identity = current_identity or source_identity(cfg)
    for row in records:
        name = str(row.get("name") or "unnamed")
        status = str(row.get("status") or "")
        path = row.get("path")
        if status not in ALLOWED_STATUS:
            errors.append(f"{name}:invalid_status")
        if status == "PASS" and bool(cfg.evidence.get("rules", {}).get("require_file_for_pass", True)) and not path:
            errors.append(f"{name}:pass_without_evidence")
        if path:
            try:
                p, _ = resolve_evidence_path(cfg, str(path))
            except ValueError as exc:
                errors.append(f"{name}:{exc}")
                continue
            actual = sha256_file(p)
            if actual != row.get("sha256"):
                errors.append(f"{name}:hash_mismatch:{path}")
            if isinstance(row.get("bytes"), int) and p.stat().st_size != row.get("bytes"):
                errors.append(f"{name}:size_mismatch:{path}")
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        sealed = metadata.get("source_identity") if isinstance(metadata, dict) else None
        if isinstance(sealed, dict):
            if sealed.get("truth_sha256") != current_identity.get("truth_fingerprint", {}).get("sha256"):
                errors.append(f"{name}:source_truth_mismatch")
            if sealed.get("policy_sha256") != current_identity.get("policy_fingerprint", {}).get("sha256"):
                errors.append(f"{name}:source_policy_mismatch")
            if sealed.get("memory_sha256") != current_identity.get("memory_fingerprint", {}).get("sha256"):
                errors.append(f"{name}:source_memory_mismatch")
            if sealed.get("mode") == "exact_commit" and sealed.get("git_commit") != current_identity.get("git_commit"):
                errors.append(f"{name}:source_commit_mismatch")
        elif row.get("source_identity_sha256") and row.get("source_identity_sha256") != current_identity.get("identity_sha256"):
            # Legacy unified-alpha records only carried the aggregate identity hash.
            # Exact mode must fail closed; content-equivalent mode can only use the
            # recorded revision as a conservative compatibility fallback.
            if current_identity.get("mode") == "exact_commit":
                errors.append(f"{name}:source_identity_mismatch")
            elif row.get("revision") and row.get("revision") != current_identity.get("git_commit"):
                errors.append(f"{name}:legacy_source_identity_unverifiable")
    return errors
