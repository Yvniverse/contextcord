from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .config import HarnessConfig
from .contracts import validate
from .util import atomic_write_json, sha256_json, utc_now

SCHEMA = "project-harness-dual-run-ledger-v1"
STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}
ADJUDICATIONS = {"BOTH_CORRECT", "LEGACY_CORRECT", "HARNESS_CORRECT", "BOTH_WRONG", "UNRESOLVED"}


def ledger_path(cfg: HarnessConfig) -> Path:
    raw = str(cfg.project.get("dogfood", {}).get("ledger_path") or f"{cfg.root.name}/dual-run/adjudications.json")
    path = (cfg.repo / raw).resolve(strict=False)
    try:
        path.relative_to(cfg.repo)
    except ValueError as exc:
        raise ValueError(f"dual_run_ledger_outside_repository:{raw}") from exc
    if path.is_symlink():
        raise ValueError("dual_run_ledger_symlink_forbidden")
    return path


def read_ledger(cfg: HarnessConfig) -> dict[str, Any]:
    path = ledger_path(cfg)
    if not path.is_file():
        return {"schema": SCHEMA, "records": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    validate("dual-run-ledger", value)
    previous = None; ids: set[str] = set()
    for index, row in enumerate(value.get("records", [])):
        rid = str(row.get("record_id") or "")
        if rid in ids:
            raise ValueError(f"dual_run_duplicate_record_id:{rid}")
        ids.add(rid)
        if row.get("previous_record_hash") != previous:
            raise ValueError(f"dual_run_chain_mismatch:{index}")
        actual = sha256_json(row, exclude_keys=("record_hash",))
        if actual != row.get("record_hash"):
            raise ValueError(f"dual_run_hash_mismatch:{rid or index}")
        previous = row.get("record_hash")
    return value


def record(
    cfg: HarnessConfig, *, task_id: str, task_class: str,
    legacy_status: str, harness_status: str, expected_status: str,
    adjudication: str, notes: str = "", legacy_evidence: str | None = None,
    harness_receipt: str | None = None,
) -> dict[str, Any]:
    statuses = [legacy_status.upper(), harness_status.upper(), expected_status.upper()]
    if any(x not in STATUSES for x in statuses):
        raise ValueError(f"dual_run_status_must_be_one_of:{sorted(STATUSES)}")
    adjudication = adjudication.upper()
    if adjudication not in ADJUDICATIONS:
        raise ValueError(f"invalid_dual_run_adjudication:{adjudication}")
    if adjudication != "UNRESOLVED":
        lc, hc = statuses[0] == statuses[2], statuses[1] == statuses[2]
        inferred = "BOTH_CORRECT" if lc and hc else "LEGACY_CORRECT" if lc else "HARNESS_CORRECT" if hc else "BOTH_WRONG"
        if inferred != adjudication:
            raise ValueError(f"dual_run_adjudication_conflicts_with_expected:{adjudication}!={inferred}")
    ledger = read_ledger(cfg); rows = list(ledger["records"]); previous = rows[-1].get("record_hash") if rows else None
    row = {
        "record_id": uuid.uuid4().hex,
        "task_id": task_id,
        "task_class": task_class,
        "legacy_status": statuses[0],
        "harness_status": statuses[1],
        "expected_status": statuses[2],
        "adjudication": adjudication,
        "notes": notes,
        "legacy_evidence": legacy_evidence,
        "harness_receipt": harness_receipt,
        "recorded_at": utc_now(),
        "previous_record_hash": previous,
    }
    row["record_hash"] = sha256_json(row, exclude_keys=("record_hash",))
    value = {"schema": SCHEMA, "records": [*rows, row]}; validate("dual-run-ledger", value)
    path = ledger_path(cfg); path.parent.mkdir(parents=True, exist_ok=True); atomic_write_json(path, value)
    return row


def summary(cfg: HarnessConfig) -> dict[str, Any]:
    rows = list(read_ledger(cfg).get("records", []))
    mismatches = [x for x in rows if x.get("harness_status") != x.get("expected_status")]
    false_pass = [x for x in mismatches if x.get("harness_status") == "PASS" and x.get("expected_status") != "PASS"]
    false_block = [x for x in mismatches if x.get("harness_status") != "PASS" and x.get("expected_status") == "PASS"]
    unresolved = [x for x in rows if x.get("adjudication") == "UNRESOLVED"]
    legacy_mismatch = [x for x in rows if x.get("legacy_status") != x.get("expected_status")]
    classes = sorted({str(x.get("task_class")) for x in rows})
    required = [str(x) for x in cfg.project.get("dogfood", {}).get("required_task_classes", [])]
    missing = sorted(set(required) - set(classes))
    gate = bool(rows) and not mismatches and not unresolved and not missing
    return {
        "status": "PASS" if gate else "FAIL",
        "cutover_gate": "PASS" if gate else "BLOCKED",
        "total": len(rows),
        "task_classes": classes,
        "required_task_classes": required,
        "missing_task_classes": missing,
        "harness_mismatch": len(mismatches),
        "harness_false_pass": len(false_pass),
        "harness_false_block": len(false_block),
        "legacy_mismatch": len(legacy_mismatch),
        "unresolved": len(unresolved),
        "records": rows,
    }
