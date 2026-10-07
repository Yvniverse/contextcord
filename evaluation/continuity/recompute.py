"""Recompute continuity measurements from the recorded per-task observations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def recompute(rows: list[dict]) -> dict:
    if not rows or len({row["task_id"] for row in rows}) != len(rows):
        raise ValueError("unique_task_rows_required")
    counters = ("notes_recovered", "bounded_text_utf8_bytes", "handoff_json_utf8_bytes", "changed_dependency_notes_revalidated", "stale_notes_selected_after_drift")
    flags = ("task_fields_lossless", "notes_lossless", "tampered_object_rejected")
    for row in rows:
        if any(type(row[key]) is not int or row[key] < 0 for key in counters):
            raise ValueError("nonnegative_integer_measurement_required")
        if any(type(row[key]) is not bool for key in flags):
            raise ValueError("boolean_observation_required")
        if len(row["task_spec_sha256"]) != 64 or any(char not in "0123456789abcdef" for char in row["task_spec_sha256"]):
            raise ValueError("task_spec_digest_required")
    totals = {key: sum(row[key] for row in rows) for key in counters}
    baseline = totals["bounded_text_utf8_bytes"]
    if baseline <= 0:
        raise ValueError("positive_baseline_required")
    return {
        "replays": len(rows), **totals,
        "task_fields_lossless": sum(row["task_fields_lossless"] for row in rows),
        "notes_lossless_tasks": sum(row["notes_lossless"] for row in rows),
        "tampered_objects_rejected": sum(row["tampered_object_rejected"] for row in rows),
        "bounded_text_to_handoff_byte_reduction": 1 - totals["handoff_json_utf8_bytes"] / baseline,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    metrics = recompute(json.loads((root / "results.json").read_text(encoding="utf-8")))
    if args.check and metrics != json.loads((root / "summary.json").read_text(encoding="utf-8")):
        raise ValueError("summary_mismatch")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
