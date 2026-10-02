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

if __name__ == "__main__":
    unittest.main()
