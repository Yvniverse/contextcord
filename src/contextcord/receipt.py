from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .build_identity import build_identity
from .config import HarnessConfig
from .contracts import validate
from .evidence import verify_evidence_records
from .identity import compare_identity, memory_commit_errors, source_identity
from .store import StateStore
from .util import atomic_write_json, ensure_repo_path, read_json, sha256_json, safe_id

SCHEMA = "contextcord-session-receipt-v2"


def receipt_dir(cfg: HarnessConfig) -> Path:
    value = str(cfg.evidence.get("rules", {}).get("receipt_dir") or f"{cfg.root.name}/receipts")
    path, _ = ensure_repo_path(cfg.repo, Path(value), label="receipt_dir", allow_external=False)
    path.mkdir(parents=True, exist_ok=True)
    return path


def receipt_hash(payload: dict[str, Any]) -> str:
    return sha256_json(payload, exclude_keys=("receipt_hash", "receipt_path"))


def load_receipt(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("receipt_path_symlink")
    value = read_json(path)
    validate("session-receipt", value)
    actual = receipt_hash(value)
    if actual != value.get("receipt_hash"):
        raise ValueError(f"receipt_hash_mismatch:{path}")
    return value


def all_receipts(cfg: HarnessConfig) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    directory = receipt_dir(cfg)
    for path in sorted(directory.glob("*.json")):
        out.append((path, load_receipt(path)))
    return out


def verify_receipt_chain(cfg: HarnessConfig, *, store: StateStore | None = None) -> dict[str, Any]:
    errors: list[str] = []
    try:
        rows = all_receipts(cfg)
    except Exception as exc:
        return {"status": "FAIL", "errors": [str(exc)], "leaf": None, "count": 0}
    if not rows and store is not None and store.receipt_head():
        return {"status": "FAIL", "errors": ["receipt_files_missing_from_live_store"], "leaf": None, "count": 0}
    if not rows:
        return {"status": "PASS", "errors": [], "leaf": None, "count": 0}
    by_hash = {str(value["receipt_hash"]): (path, value) for path, value in rows}
    referenced: set[str] = set()
    roots = []
    for path, value in rows:
        prev = value.get("previous_receipt_hash")
        if prev is None:
            roots.append(str(value["receipt_hash"]))
        else:
            referenced.add(str(prev))
            if str(prev) not in by_hash:
                errors.append(f"receipt_chain_missing_parent:{path.name}:{prev}")
    leaves = [digest for digest in by_hash if digest not in referenced]
    if len(roots) != 1:
        errors.append(f"receipt_chain_root_count:{len(roots)}")
    if len(leaves) != 1:
        errors.append(f"receipt_chain_leaf_count:{len(leaves)}")
    if len(leaves) == 1:
        seen: set[str] = set(); current = leaves[0]
        while current:
            if current in seen:
                errors.append(f"receipt_chain_cycle:{current}"); break
            seen.add(current)
            row = by_hash.get(current)
            if row is None:
                break
            current = str(row[1].get("previous_receipt_hash") or "")
        if len(seen) != len(rows):
            errors.append(f"receipt_chain_disconnected:{len(seen)}of{len(rows)}")
    if store is not None:
        db_head = store.receipt_head()
        if len(leaves) == 1 and db_head != leaves[0]:
            errors.append(f"receipt_db_head_mismatch:{db_head}!={leaves[0]}")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "leaf": leaves[0] if len(leaves) == 1 else None, "count": len(rows)}


def write_sealed_receipt(cfg: HarnessConfig, store: StateStore, payload: dict[str, Any], *, max_retries: int = 4) -> tuple[Path, dict[str, Any]]:
    directory = receipt_dir(cfg)
    path = directory / f"{safe_id(str(payload['task_id']))}-{safe_id(str(payload['session_id']))}.json"
    if path.exists():
        raise ValueError("receipt_already_exists")
    for _ in range(max_retries):
        previous = store.receipt_head()
        value = dict(payload)
        value["previous_receipt_hash"] = previous
        value["receipt_hash"] = receipt_hash(value)
        validate("session-receipt", value)
        atomic_write_json(path, value)
        if store.append_receipt_index(
            receipt_hash=value["receipt_hash"], previous_hash=previous,
            path=path.relative_to(cfg.repo).as_posix(), session_id=str(value["session_id"]), task_id=str(value["task_id"]),
        ):
            return path, value
        # Another closeout won the CAS; reseal against the new parent.
        path.unlink(missing_ok=True)
    raise RuntimeError("receipt_chain_concurrent_append_retry_exhausted")


def chain_order_newest_first(cfg: HarnessConfig) -> list[tuple[Path, dict[str, Any]]]:
    rows = all_receipts(cfg)
    if not rows:
        return []
    by_hash = {str(v["receipt_hash"]): (p, v) for p, v in rows}
    referenced = {str(v.get("previous_receipt_hash")) for _, v in rows if v.get("previous_receipt_hash")}
    leaves = [h for h in by_hash if h not in referenced]
    if len(leaves) != 1:
        raise ValueError(f"receipt_chain_leaf_count:{len(leaves)}")
    out = []; current: str | None = leaves[0]; seen: set[str] = set()
    while current:
        if current in seen:
            raise ValueError("receipt_chain_cycle")
        seen.add(current); row = by_hash.get(current)
        if row is None:
            raise ValueError(f"receipt_chain_missing_parent:{current}")
        out.append(row); current = row[1].get("previous_receipt_hash")
    if len(out) != len(rows):
        raise ValueError("receipt_chain_disconnected")
    return out


def matching_complete_receipt(cfg: HarnessConfig, current_identity: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    return matching_receipt(cfg, current_identity, receipt_type="COMPLETE")


def matching_receipt(
    cfg: HarnessConfig,
    current_identity: dict[str, Any],
    *,
    receipt_type: str,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Return the newest receipt of a type that matches current source identity."""

    wanted = str(receipt_type).upper()
    for path, value in chain_order_newest_first(cfg):
        if str(value.get("receipt_type") or "").upper() != wanted:
            continue
        sealed = value.get("source_identity", {})
        if not isinstance(sealed, Mapping):
            continue
        if sealed.get("truth_fingerprint", {}).get("sha256") != current_identity.get("truth_fingerprint", {}).get("sha256"):
            continue
        if sealed.get("mode") == "exact_commit" and sealed.get("git_commit") != current_identity.get("git_commit"):
            continue
        return path, value
    return None, None


def matching_handoff_receipt(cfg: HarnessConfig, current_identity: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    return matching_receipt(cfg, current_identity, receipt_type="HANDOFF")


def _handoff_packet_errors(receipt: Mapping[str, Any], session: Mapping[str, Any] | None) -> list[str]:
    failures: list[str] = []
    packet = receipt.get("handoff_packet")
    if not isinstance(packet, Mapping):
        failures.append("handoff_continuation_packet_missing")
        return failures
    if packet.get("schema") != "contextcord-handoff-continuation-v1":
        failures.append("handoff_continuation_packet_schema_invalid")
    if str(packet.get("task_id")) != str(receipt.get("task_id")):
        failures.append("handoff_continuation_packet_task_mismatch")
    if str(packet.get("session_id")) != str(receipt.get("session_id")):
        failures.append("handoff_continuation_packet_session_mismatch")
    if not isinstance(packet.get("summary"), str) or not packet.get("summary", "").strip() or len(packet.get("summary", "")) > 2048:
        failures.append("handoff_continuation_packet_summary_invalid")
    for name in ("next_steps", "risks"):
        value = packet.get(name)
        if not isinstance(value, list) or any(not isinstance(item, str) or len(item) > 512 for item in value):
            failures.append(f"handoff_continuation_packet_{name}_invalid")
    source_identity = packet.get("source_identity_sha256")
    sealed_identity = receipt.get("source_identity", {}).get("identity_sha256") if isinstance(receipt.get("source_identity"), Mapping) else None
    if source_identity != sealed_identity:
        failures.append("handoff_continuation_packet_identity_mismatch")
    if session is None:
        failures.append("handoff_session_missing")
    else:
        if str(session.get("task_id")) != str(receipt.get("task_id")):
            failures.append("handoff_session_task_mismatch")
        if str(session.get("status")) not in {"CLOSED", "CLOSED_FAILED"}:
            failures.append("handoff_session_not_terminal")
    return failures


def verify_handoff_receipt(cfg: HarnessConfig, store: StateStore, receipt: dict[str, Any]) -> dict[str, Any]:
    """Verify a HANDOFF receipt without upgrading it to engineering completion."""

    result = verify_receipt(cfg, store, receipt, require_complete=False)
    failures = list(result["failures"])
    if receipt.get("receipt_type") != "HANDOFF":
        failures.append(f"handoff_receipt_type_invalid:{receipt.get('receipt_type')}")
    if receipt.get("closeout_status") != "HANDOFF":
        failures.append(f"handoff_closeout_status_invalid:{receipt.get('closeout_status')}")
    failures.extend(_handoff_packet_errors(receipt, store.session(str(receipt.get("session_id")))))
    return {"status": "PASS" if not failures else "FAIL", "failures": failures, "current_identity": result["current_identity"]}


def verify_receipt(cfg: HarnessConfig, store: StateStore, receipt: dict[str, Any], *, require_complete: bool = True) -> dict[str, Any]:
    failures: list[str] = []
    current = source_identity(cfg)
    failures.extend(compare_identity(current, receipt.get("source_identity", {}), sealed_memory=cfg.sealed_memory_on_verify))
    failures.extend(memory_commit_errors(cfg))
    failures.extend(verify_evidence_records(cfg, list(receipt.get("evidence_records", [])), current_identity=current))
    if receipt_hash(receipt) != receipt.get("receipt_hash"):
        failures.append("receipt_hash_mismatch")
    if receipt.get("store_id") != store.store_id:
        failures.append("receipt_store_identity_mismatch_use_explicit_bundle_verification")
    if receipt.get("build_identity", {}).get("sha256") != build_identity()["sha256"]:
        failures.append("receipt_build_identity_mismatch")
    if not receipt.get("event_chain_head") or not store.event_hash_exists(receipt["event_chain_head"]):
        failures.append("receipt_event_chain_head_missing_from_state_store")
    chain_ok, bad = store.verify_event_chain()
    if not chain_ok:
        failures.append(f"event_chain_invalid:{bad}")
    if require_complete:
        if receipt.get("receipt_type") != "COMPLETE":
            failures.append("latest_matching_receipt_not_complete")
        if receipt.get("closeout_status") != "PASS":
            failures.append(f"closeout_status_not_pass:{receipt.get('closeout_status')}")
    if receipt.get("integrity_status") != "PASS":
        failures.append("receipt_integrity_status_not_pass")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures, "current_identity": current}
