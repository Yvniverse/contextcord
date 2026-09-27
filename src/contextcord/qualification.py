from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .config import HarnessConfig
from .contracts import validate
from .evidence import resolve_evidence_path
from .gitops import notes_show, notes_write, resolve_commit, notes_compare_and_swap, git
from .util import sha256_file, sha256_json, utc_now

SCHEMA = "project-harness-qualification-v2"
LEGACY_SCHEMA = "project-operations-harness-qualification-v1"


def _record_hash(row: dict[str, Any]) -> str:
    return sha256_json(row, exclude_keys=("record_hash",))


def _migrate_legacy(value: dict[str, Any], commit: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    previous: str | None = None
    q = value.get("qualification")
    if isinstance(q, dict):
        evidence = []
        if q.get("evidence") and q.get("evidence_sha256"):
            evidence.append({"path": q["evidence"], "sha256": q["evidence_sha256"]})
        row = {
            "record_id": "legacy-qualification",
            "kind": "review",
            "status": str(q.get("status") or "NOT_RUN"),
            "recorded_at": str(q.get("recorded_at") or utc_now()),
            "evidence": evidence,
            "summary": str(q.get("summary") or ""),
            "metadata": dict(q.get("metadata") or {}),
            "environment": None,
            "runtime_revisions": [],
            "supersedes": None,
            "previous_record_hash": previous,
        }
        row["record_hash"] = _record_hash(row); previous = row["record_hash"]; records.append(row)
    for index, dep in enumerate(value.get("deployments", [])):
        env = str(dep.get("environment") or "unknown")
        row = {
            "record_id": f"legacy-deploy-{index}",
            "kind": f"deployment:{env}",
            "status": str(dep.get("status") or "NOT_RUN"),
            "recorded_at": str(dep.get("recorded_at") or utc_now()),
            "evidence": [],
            "summary": str(dep.get("summary") or ""),
            "metadata": dict(dep.get("metadata") or {}),
            "environment": env,
            "runtime_revisions": [str(x) for x in dep.get("runtime_revisions", [])],
            "supersedes": None,
            "previous_record_hash": previous,
        }
        row["record_hash"] = _record_hash(row); previous = row["record_hash"]; records.append(row)
    return {"schema": SCHEMA, "commit": commit, "records": records, "migrated_from_schema": value.get("schema") or LEGACY_SCHEMA}


def read_note(cfg: HarnessConfig, commit: str) -> dict[str, Any] | None:
    raw = notes_show(cfg.repo, cfg.notes_ref, commit)
    if not raw:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("qualification note must be an object")
    if value.get("schema") == LEGACY_SCHEMA:
        value = _migrate_legacy(value, commit)
    elif value.get("schema") != SCHEMA:
        raise ValueError("unknown_qualification_schema")
    validate("qualification-note", value)
    return value


def _write(cfg: HarnessConfig, commit: str, note: dict[str, Any]) -> None:
    validate("qualification-note", note)
    notes_write(cfg.repo, cfg.notes_ref, commit, json.dumps(note, ensure_ascii=False, indent=2, sort_keys=True))


def base_note(cfg: HarnessConfig, commit: str) -> dict[str, Any]:
    note = read_note(cfg, commit)
    if note is None:
        return {"schema": SCHEMA, "commit": commit, "records": []}
    if note.get("commit") != commit:
        raise ValueError("qualification note commit mismatch")
    return note


def _latest_by_kind(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in records:
        out[str(row.get("kind"))] = row
    return out


def _append(cfg: HarnessConfig, *, commit: str, kind: str, status: str, evidence_paths: list[Path], summary: str, metadata: dict[str, Any] | None, environment: str | None = None, runtime_revisions: list[str] | None = None) -> dict[str, Any]:
    for attempt in range(12):
        expected = git(cfg.repo, "rev-parse", "--verify", cfg.notes_ref, check=False)
        note = base_note(cfg, commit); records = list(note.get("records", [])); latest = _latest_by_kind(records)
        evidence = []
        for raw_path in evidence_paths:
            p, stored = resolve_evidence_path(cfg, str(raw_path))
            evidence.append({"path": stored, "sha256": sha256_file(p), "bytes": p.stat().st_size})
        previous = records[-1].get("record_hash") if records else None
        prior = latest.get(kind)
        row: dict[str, Any] = {
            "record_id": uuid.uuid4().hex,
            "kind": kind,
            "status": status,
            "recorded_at": utc_now(),
            "evidence": evidence,
            "summary": summary,
            "metadata": metadata or {},
            "environment": environment,
            "runtime_revisions": runtime_revisions or [],
            "supersedes": prior.get("record_id") if prior else None,
            "previous_record_hash": previous,
        }
        row["record_hash"] = _record_hash(row)
        note = {"schema": SCHEMA, "commit": commit, "records": [*records, row]}
        validate("qualification-note", note)
        if notes_compare_and_swap(cfg.repo, cfg.notes_ref, commit, json.dumps(note, ensure_ascii=False, sort_keys=True), expected):
            return note
    raise RuntimeError("qualification_concurrent_update_retry_exhausted")


def record(cfg: HarnessConfig, *, commitish: str, status: str, evidence: Path, summary: str, metadata: dict[str, Any] | None = None, kind: str = "review") -> dict[str, Any]:
    commit = resolve_commit(cfg.repo, commitish)
    return _append(cfg, commit=commit, kind=kind, status=status, evidence_paths=[evidence], summary=summary, metadata=metadata)


def deploy(
    cfg: HarnessConfig,
    *,
    commitish: str,
    status: str,
    environment: str,
    runtime_revisions: list[str],
    summary: str,
    evidence_paths: list[Path] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    commit = resolve_commit(cfg.repo, commitish)
    revisions = [resolve_commit(cfg.repo, x) for x in runtime_revisions]
    paths = list(evidence_paths or [])
    if status == "PASS":
        if not revisions or any(x != commit for x in revisions):
            raise ValueError("runtime revision must equal deployment commit for PASS")
        if not paths:
            raise ValueError("PASS deployment qualification requires evidence")
    return _append(
        cfg,
        commit=commit,
        kind=f"deployment:{environment}",
        status=status,
        evidence_paths=paths,
        summary=summary,
        metadata=metadata,
        environment=environment,
        runtime_revisions=revisions,
    )


def _integrity_errors(cfg: HarnessConfig, commit: str, note: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if note.get("commit") != commit:
        errors.append("qualification_note_commit_mismatch")
    previous: str | None = None; latest_kind_id: dict[str, str] = {}; ids: set[str] = set()
    for index, row in enumerate(note.get("records", [])):
        rid = str(row.get("record_id") or "")
        if rid in ids:
            errors.append(f"duplicate_record_id:{rid}")
        ids.add(rid)
        if row.get("previous_record_hash") != previous:
            errors.append(f"record_chain_mismatch:{index}")
        if _record_hash(row) != row.get("record_hash"):
            errors.append(f"record_hash_mismatch:{rid or index}")
        kind = str(row.get("kind") or "")
        if row.get("supersedes") is not None and row.get("supersedes") != latest_kind_id.get(kind):
            errors.append(f"invalid_supersedes:{rid or index}")
        latest_kind_id[kind] = rid
        previous = row.get("record_hash")
        for ev in row.get("evidence", []):
            try:
                p, _ = resolve_evidence_path(cfg, str(ev.get("path") or ""))
            except ValueError as exc:
                errors.append(f"qualification_evidence_invalid:{exc}")
                continue
            if sha256_file(p) != ev.get("sha256"):
                errors.append(f"qualification_evidence_hash_mismatch:{ev.get('path')}")
            if isinstance(ev.get("bytes"), int) and p.stat().st_size != ev.get("bytes"):
                errors.append(f"qualification_evidence_size_mismatch:{ev.get('path')}")
    return errors


def verify(cfg: HarnessConfig, *, commitish: str, require_qualified: bool = False, require_deployed: bool = False, environment: str | None = None, profile: str | None = None) -> dict[str, Any]:
    commit = resolve_commit(cfg.repo, commitish)
    note = read_note(cfg, commit)
    if note is None:
        return {"commit": commit, "notes_ref": cfg.notes_ref, "status": "FAIL", "integrity_status": "FAIL", "qualification_status": "FAIL", "failures": ["qualification_note_missing"], "note": None}
    failures = _integrity_errors(cfg, commit, note)
    integrity_status = "PASS" if not failures else "FAIL"
    current = _latest_by_kind(list(note.get("records", [])))
    qualification_failures: list[str] = []
    if profile:
        profiles = cfg.qualification.get("profiles", {})
        if profile == "current-records":
            required = sorted(current)
        else:
            prow = profiles.get(profile)
            if not isinstance(prow, dict):
                raise ValueError(f"unknown qualification profile: {profile}")
            required = [str(x) for x in prow.get("required", [])]
        for kind in required:
            row = current.get(kind)
            if row is None:
                qualification_failures.append(f"missing_required_kind:{kind}")
            elif row.get("status") != "PASS":
                qualification_failures.append(f"required_kind_not_pass:{kind}:{row.get('status')}")
    if require_qualified:
        candidates = [row for kind, row in current.items() if not kind.startswith("deployment:")]
        if not any(row.get("status") == "PASS" for row in candidates):
            qualification_failures.append("qualification_not_pass")
    if require_deployed:
        kind = f"deployment:{environment}" if environment else None
        candidates = [row for k, row in current.items() if k.startswith("deployment:") and (kind is None or k == kind)]
        good = [row for row in candidates if row.get("status") == "PASS" and row.get("runtime_revisions") and all(x == commit for x in row.get("runtime_revisions", []))]
        if not good:
            qualification_failures.append("exact_commit_deployment_missing")
    qualification_status = "PASS" if not qualification_failures else "FAIL"
    overall = "PASS" if integrity_status == "PASS" and qualification_status == "PASS" else "FAIL"
    return {
        "commit": commit,
        "notes_ref": cfg.notes_ref,
        "status": overall,
        "integrity_status": integrity_status,
        "qualification_status": qualification_status,
        "profile": profile,
        "current_statuses": {k: v.get("status") for k, v in sorted(current.items())},
        "failures": failures,
        "qualification_failures": qualification_failures,
        "note": note,
    }
