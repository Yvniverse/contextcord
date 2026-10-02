"""Recompute the public aggregate; this check validates arithmetic, not a benchmark run."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def wilson(successes: int, denominator: int) -> tuple[float, float]:
    z = 1.959963984540054
    p = successes / denominator
    divisor = 1 + z * z / denominator
    center = (p + z * z / (2 * denominator)) / divisor
    half = z * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator ** 2)) / divisor
    return center - half, center + half

def verify(value: dict) -> list[str]:
    errors = []
    if value.get("schema") != "contextcord-evaluation-summary-v1":
        errors.append("schema")
    if value.get("evidence_status") != "MAINTAINER_REPORTED":
        errors.append("unrecognized_evidence_status")
    scope = value.get("reporting_scope", {})
    if scope.get("kind") != "maintainer_confirmed_aggregate" or scope.get("check_scope") != "published_summary_arithmetic":
        errors.append("report_provenance_mismatch")
    for label, row in (
        ("baseline", value["continuation"]["baseline"]),
        ("full_contextcord", value["continuation"]["full_contextcord"]),
        ("jev", value["typed_decisions"]["jev"]),
        ("free_text_baseline", value["typed_decisions"]["free_text_baseline"]),
    ):
        n, k = row["denominator"], row["successes"]
        if isinstance(n, bool) or isinstance(k, bool) or not isinstance(n, int) or not isinstance(k, int) or not 0 <= k <= n or n < 1:
            errors.append(label + ":invalid_counts")
            continue
        if row["failures"] != n - k or not math.isclose(row["rate"], k / n, abs_tol=1e-12):
            errors.append(label + ":count_rate_mismatch")
        lower, upper = wilson(k, n)
        ci = row["confidence_interval"]
        if ci["method"] != "Wilson score" or ci["confidence_level"] != 0.95 or not math.isclose(ci["lower"], lower, abs_tol=1e-12) or not math.isclose(ci["upper"], upper, abs_tol=1e-12):
            errors.append(label + ":confidence_interval_mismatch")
    continuation = value["continuation"]
    baseline, treatment = continuation["baseline"], continuation["full_contextcord"]
    if baseline["denominator"] != value["protocol"]["task_denominator"] or treatment["denominator"] != value["protocol"]["task_denominator"]:
        errors.append("task_denominator_mismatch")
    if not math.isclose(continuation["absolute_gain_pp"], 100 * (treatment["rate"] - baseline["rate"]), abs_tol=1e-10):
        errors.append("absolute_gain_mismatch")
    if not math.isclose(continuation["relative_gain_percent"], 100 * (treatment["rate"] / baseline["rate"] - 1), abs_tol=1e-10):
        errors.append("relative_gain_mismatch")
    decisions = value["typed_decisions"]
    if any(decisions[label]["denominator"] != decisions["denominator"] for label in ("jev", "free_text_baseline")):
        errors.append("decision_denominator_mismatch")
    if not math.isclose(decisions["absolute_gain_pp"], 100 * (decisions["jev"]["rate"] - decisions["free_text_baseline"]["rate"]), abs_tol=1e-10):
        errors.append("decision_gain_mismatch")
    for field, expected in (
        ("baseline_failed_tasks", baseline["failures"]),
        ("full_contextcord_failed_tasks", treatment["failures"]),
        ("jev_incorrect_decisions_inferred", decisions["jev"]["failures"]),
        ("free_text_incorrect_decisions_inferred", decisions["free_text_baseline"]["failures"]),
    ):
        if value["failures"][field] != expected:
            errors.append("failure_summary_mismatch:" + field)
    gate = value["adversarial_gate"]
    if gate["bypasses"] != 0 or gate["denominator"] != 300 or not math.isclose(gate["confidence_interval"]["upper"], 1 - 0.025 ** (1 / gate["denominator"]), abs_tol=1e-12):
        errors.append("gate_exact_interval_mismatch")
    if [arm["id"] for arm in value["protocol"]["arms"]] != ["A_COLD_START", "B_TEXT_HANDOFF", "C_STRUCTURED_CORE", "D_STRUCTURED_JEV"]:
        errors.append("arm_definitions")
    return errors

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "research/evaluation/aggregate.json")
    args = parser.parse_args()
    value = json.loads(args.report.read_text(encoding="utf-8"))
    errors = verify(value)
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "check_scope": "published_summary_arithmetic", "evidence_status": value["evidence_status"], "errors": errors}, indent=2))
    return 1 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
