from __future__ import annotations
import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("evaluation_check", ROOT / "scripts/check_evaluation.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

class EvaluationSummaryTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads((ROOT / "research/evaluation/aggregate.json").read_text(encoding="utf-8"))

    def test_report_arithmetic_is_consistent(self):
        self.assertEqual(checker.verify(self.value), [])

    def test_changed_denominator_and_fabricated_evidence_status_fail(self):
        value = copy.deepcopy(self.value)
        value["protocol"]["task_denominator"] = 59
        value["evidence_status"] = "INDEPENDENTLY_VERIFIED"
        errors = checker.verify(value)
        self.assertIn("task_denominator_mismatch", errors)
        self.assertIn("unrecognized_evidence_status", errors)

    def test_zero_events_has_nonzero_exact_upper_bound(self):
        interval = self.value["adversarial_gate"]["confidence_interval"]
        self.assertEqual(interval["lower"], 0)
        self.assertGreater(interval["upper"], 0.01)
        self.assertLess(interval["upper"], 0.013)

    def test_recomputation_scope_cannot_attest_execution(self):
        value = copy.deepcopy(self.value)
        value["reporting_scope"]["check_scope"] = "benchmark_execution_verified"
        self.assertIn("report_provenance_mismatch", checker.verify(value))

    def test_decision_denominator_and_gain_must_match_counts(self):
        value = copy.deepcopy(self.value)
        value["typed_decisions"]["denominator"] = 299
        value["typed_decisions"]["absolute_gain_pp"] = 10
        errors = checker.verify(value)
        self.assertIn("decision_denominator_mismatch", errors)
        self.assertIn("decision_gain_mismatch", errors)

    def test_failure_summary_cannot_hide_failed_tasks(self):
        value = copy.deepcopy(self.value)
        value["failures"]["full_contextcord_failed_tasks"] = 0
        self.assertIn("failure_summary_mismatch:full_contextcord_failed_tasks", checker.verify(value))

if __name__ == "__main__":
    unittest.main()
