"""Recompute typed agreement, request latency and deterministic gate results."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

BLOCKERS = {
    "integrity_status": ("FAIL", "BLOCK_INTEGRITY"),
    "secret_blocker": (True, "BLOCK_SECRET"),
    "permission_allowed": (False, "BLOCK_PERMISSION"),
    "qualification_pass": (False, "BLOCK_QUALIFICATION"),
    "frozen_tests_pass": (False, "BLOCK_FROZEN_ORACLE"),
    "release_gate_pass": (False, "BLOCK_RELEASE_GATE"),
    "destructive_side_effects_approved": (False, "BLOCK_DESTRUCTIVE_SIDE_EFFECT"),
}


def load(root: Path) -> tuple:
    return tuple(json.loads((root / name).read_text(encoding="utf-8")) for name in ("scored_rows.json", "requests.json", "gate_cases.json", "rubric.json"))


def recompute(rows: list[dict], requests: list[dict], gates: list[dict], rubric: dict) -> dict:
    specs = {spec["id"]: spec for spec in rubric["decision_types"]}
    request_ids = {row["request_id"] for row in requests}
    if len(request_ids) != len(requests) or len({(row["request_id"], row["question"]) for row in rows}) != len(rows):
        raise ValueError("unique_request_and_judgment_rows_required")
    if len({row["case_id"] for row in gates}) != len(gates):
        raise ValueError("unique_gate_rows_required")
    for row in rows:
        if row["request_id"] not in request_ids or row["question"] not in specs or type(row["valid"]) is not bool:
            raise ValueError("judgment_reference_or_validity_invalid")
        spec = specs[row["question"]]
        for key in ("expected", "actual"):
            if key == "actual" and not row["valid"]:
                continue
            value = row[key]
            if (spec["type"] == "noul" and type(value) is not bool
                    or spec["type"] == "score" and (type(value) is not int or not 0 <= value <= 3)
                    or spec["type"] == "choice" and (not isinstance(value, str) or value not in spec["options"])):
                raise ValueError("typed_value_out_of_domain")
    for row in requests:
        if type(row["completed"]) is not bool or type(row["latency_ms"]) not in (int, float) or not math.isfinite(row["latency_ms"]) or row["latency_ms"] < 0:
            raise ValueError("request_measurement_invalid")
        if sum(item["request_id"] == row["request_id"] for item in rows) != row["judgments"]:
            raise ValueError("request_judgment_count_mismatch")
    latencies = sorted(row["latency_ms"] for row in requests if row["completed"])
    valid = [row for row in rows if row["valid"]]
    blocked = 0
    for row in gates:
        if row["request_id"] not in request_ids:
            raise ValueError("gate_request_reference_invalid")
        expected = [code for key, (value, code) in BLOCKERS.items() if key in row["state"] and row["state"][key] == value]
        if not expected or row["expected_overrides"] != expected:
            raise ValueError("gate_fixture_without_matching_blocker")
        blocked += int(row["overrides"] == expected and row["actions"] == expected + ["NO_SEMANTIC_OVERRIDE"])
    correct = sum(row["actual"] == row["expected"] for row in valid)
    return {
        "planned_judgments": len(rows), "valid_judgments": len(valid), "correct_judgments": correct,
        "agreement": correct / len(valid) if valid else 0,
        "decision_types": len(specs), "live_requests": len(latencies),
        "latency_p95_ms": float(latencies[math.ceil(len(latencies) * 0.95) - 1]) if latencies else None,
        "hard_gate_controls": len(gates), "hard_gate_blocked": blocked,
        "hard_gate_bypasses_observed": len(gates) - blocked,
    }


def replay(gates: list[dict]) -> None:
    from contextcord.decision_fabric import _code_actions
    for row in gates:
        actions, overrides = _code_actions(row["state"], row["advice"])
        if overrides != row["expected_overrides"] or actions != row["expected_overrides"] + ["NO_SEMANTIC_OVERRIDE"]:
            raise ValueError(f"gate_replay_failed:{row['case_id']}")
        if actions != row["actions"] or overrides != row["overrides"]:
            raise ValueError("recorded_gate_result_mismatch")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    rows, requests, gates, rubric = load(root)
    metrics = recompute(rows, requests, gates, rubric)
    if args.check and metrics != json.loads((root / "summary.json").read_text(encoding="utf-8")):
        raise ValueError("summary_mismatch")
    if args.replay:
        replay(gates)
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
