"""Source-bound, budgeted engineering observations, independent of any vendor.

Ranking is advisory. It cannot make an unbound/stale observation current, turn
a reported check into verifier success, grant permission or bypass host policy.
Callers provide an independently observed workspace file-hash snapshot.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any


SCHEMA = "contextcord-source-bound-continuity-v1"
KINDS = {"fact", "check", "hypothesis", "risk", "next_action"}
SHA = re.compile(r"[a-f0-9]{64}")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def relative_source_path(value: Any) -> str:
    """Fail closed on ambiguous names; no filesystem or credential access."""
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("continuity_relative_source_required")
    parts = PurePosixPath(value).parts
    if (not parts or value.startswith(("/", "\\")) or "\\" in value or ":" in value
            or ".." in parts or value != PurePosixPath(value).as_posix()):
        raise ValueError("continuity_unsafe_source_path")
    if any(p.casefold() in {".git", ".codex", ".aws", ".ssh", ".contextcord-eval", "auth.json", "hidden", "oracle", "solution", "secrets", "id_rsa", "id_ed25519", "credentials"}
           or p.casefold().startswith(".env") or p.casefold().endswith((".pem", ".key", ".p12", ".pfx"))
           for p in parts):
        raise ValueError("continuity_non_source_path")
    return value


def revalidate_observations(records: Sequence[Mapping[str, Any]], current_files: Mapping[str, str]) -> dict:
    if (not isinstance(records, Sequence) or isinstance(records, (str, bytes))
            or not 1 <= len(records) <= 200 or not isinstance(current_files, Mapping)):
        raise ValueError("continuity_bounded_records_and_file_snapshot_required")
    for name, digest in current_files.items():
        relative_source_path(name)
        if not isinstance(digest, str) or not SHA.fullmatch(digest):
            raise ValueError("continuity_file_snapshot_hash_invalid")
    checked, seen = [], set()
    for raw in records:
        if not isinstance(raw, Mapping):
            raise ValueError("continuity_record_object_required")
        ident, summary = raw.get("memory_id"), raw.get("summary")
        if (not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", ident)
                or ident in seen or not isinstance(summary, str) or not summary.strip() or len(summary) > 768):
            raise ValueError("continuity_unique_id_and_bounded_summary_required")
        seen.add(ident)
        kind = raw.get("kind", "fact")
        if kind not in KINDS:
            raise ValueError("continuity_kind_invalid")
        stated = raw.get("freshness")
        if stated not in {"CURRENT", "STALE"}:
            raise ValueError("continuity_stated_freshness_invalid")
        dependencies = raw.get("dependencies", [])
        if not isinstance(dependencies, list) or len(dependencies) > 16:
            raise ValueError("continuity_dependencies_invalid")
        bindings, dep_seen = [], set()
        for item in dependencies:
            if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
                raise ValueError("continuity_dependency_shape_invalid")
            path = relative_source_path(item["path"])
            digest = item["sha256"]
            if path in dep_seen or not isinstance(digest, str) or not SHA.fullmatch(digest):
                raise ValueError("continuity_dependency_duplicate_or_hash_invalid")
            dep_seen.add(path)
            actual = current_files.get(path)
            bindings.append({"path": path, "expected_sha256": digest,
                             "actual_sha256": actual,
                             "status": "UNCHANGED" if actual == digest else "MISSING" if actual is None else "CHANGED"})
        # Empty dependencies and an agent's CURRENT assertion are not proof.
        current = stated == "CURRENT" and bool(bindings) and all(d["status"] == "UNCHANGED" for d in bindings)
        next_action = raw.get("next_action", "")
        if not isinstance(next_action, str) or len(next_action) > 768:
            raise ValueError("continuity_next_action_invalid")
        checked.append({"memory_id": ident, "summary": summary, "kind": kind,
                        "next_action": next_action, "source": bindings[0]["path"] if bindings else "unbound",
                        "stated_freshness": stated, "freshness": "CURRENT" if current else "STALE",
                        "qualification": "SOURCE_UNCHANGED" if current else "REVALIDATE",
                        "dependencies": bindings,
                        "source_identity_sha256": hashlib.sha256(_canonical(bindings).encode()).hexdigest(),
                        "truth_boundary": "Source identity only; observation/check correctness not inferred."})
    return {"schema": SCHEMA, "records": checked,
            "current_count": sum(r["freshness"] == "CURRENT" for r in checked),
            "revalidate_count": sum(r["freshness"] != "CURRENT" for r in checked),
            "snapshot_sha256": hashlib.sha256(_canonical(dict(current_files)).encode()).hexdigest()}


def pack_continuity(validated: Mapping[str, Any], ranked_ids: Sequence[str], *, budget_tokens: int = 6000,
                    max_records: int = 12) -> dict:
    """Pack a common byte budget; rank cannot override source constraints."""
    if type(budget_tokens) is not int or not 64 <= budget_tokens <= 6000 or type(max_records) is not int or not 1 <= max_records <= 200:
        raise ValueError("continuity_budget_or_limit_invalid")
    if validated.get("schema") != SCHEMA or not isinstance(validated.get("records"), list):
        raise ValueError("continuity_validated_snapshot_required")
    if not isinstance(ranked_ids, Sequence) or isinstance(ranked_ids, (str, bytes)) or len(set(ranked_ids)) != len(ranked_ids):
        raise ValueError("continuity_rank_identity_ambiguous")
    rows = validated["records"]
    if any(not isinstance(r, Mapping) for r in rows) or len({r.get("memory_id") for r in rows}) != len(rows):
        raise ValueError("continuity_validated_record_identity_ambiguous")
    by_id = {r["memory_id"]: r for r in rows}
    if any(ident not in by_id for ident in ranked_ids):
        raise ValueError("continuity_rank_unknown_id")
    eligible = [by_id[ident] for ident in ranked_ids if by_id[ident].get("freshness") == "CURRENT"
                and by_id[ident].get("qualification") == "SOURCE_UNCHANGED"
                and by_id[ident].get("dependencies")
                and all(d.get("status") == "UNCHANGED" and d.get("actual_sha256") == d.get("expected_sha256") for d in by_id[ident]["dependencies"])]
    # Preserve one actionable step/risk when present, then relevance order.
    anchors = [next((r for r in eligible if r["kind"] == kind), None) for kind in ("next_action", "risk")]
    ordered = [r for r in anchors if r is not None]
    ordered += [r for r in eligible if r["memory_id"] not in {a["memory_id"] for a in ordered}]
    result = {"schema": SCHEMA, "snapshot_sha256": validated["snapshot_sha256"],
              "selected": [], "needs_revalidation_ids": [r["memory_id"] for r in rows if r.get("freshness") != "CURRENT"],
              "truth_boundary": "Advisory engineering continuity; not completion, execution permission or verifier evidence."}
    estimate = lambda v: (len(_canonical(v).encode("utf-8")) + 3) // 4
    if estimate(result) > budget_tokens:
        raise ValueError("continuity_fixed_metadata_exceeds_budget")
    for row in ordered:
        if len(result["selected"]) >= max_records:
            break
        candidate = dict(result, selected=result["selected"] + [dict(row)])
        if estimate(candidate) <= budget_tokens:
            result = candidate
    # No min(budget, actual): oversize cannot be disguised as an in-budget pack.
    result["estimated_tokens"] = estimate(result)
    # Include the estimate field itself in the measured serialized budget.
    result["estimated_tokens"] = estimate(result)
    if result["estimated_tokens"] > budget_tokens:
        raise ValueError("continuity_final_metadata_exceeds_budget")
    result["omitted_current_count"] = len(eligible) - len(result["selected"])
    if estimate(result) > budget_tokens:
        raise ValueError("continuity_final_metadata_exceeds_budget")
    result["estimated_tokens"] = estimate(result)
    return result
