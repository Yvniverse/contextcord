import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_readme_metrics import HEADLINE_FILES, check, check_documents, load_script
from check_product_surface import derive, check_docs


class PublicEvaluationTests(unittest.TestCase):
    def test_every_headline_document_rejects_changed_continuity_values(self):
        metrics = check(ROOT)
        c, t = metrics["continuity"], metrics["typed_decisions"]
        changes = (
            (f"{c['handoff_json_utf8_bytes']:,}", f"{c['handoff_json_utf8_bytes'] - 1:,}"),
            (f"{c['bounded_text_to_handoff_byte_reduction'] * 100:.1f}%",
             f"{c['bounded_text_to_handoff_byte_reduction'] * 100 + 1:.1f}%"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in HEADLINE_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
            check_documents(root, c, t)
            for name in HEADLINE_FILES:
                path = root / name
                original = path.read_text(encoding="utf-8")
                for before, after in changes:
                    with self.subTest(document=name, measurement=before):
                        self.assertIn(before, original)
                        path.write_text(original.replace(before, after), encoding="utf-8")
                        with self.assertRaisesRegex(ValueError, "headline_metric_missing_or_changed"):
                            check_documents(root, c, t)
                path.write_text(original, encoding="utf-8")

    def test_extra_inconsistent_measurements_are_rejected_in_prose(self):
        metrics = check(ROOT)
        c, t = metrics["continuity"], metrics["typed_decisions"]
        extras = (f"{c['handoff_json_utf8_bytes'] - 1:,} B",
                  f"{c['bounded_text_to_handoff_byte_reduction'] * 100 + 1:.1f}%")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in HEADLINE_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
            for name in HEADLINE_FILES:
                path = root / name
                original = path.read_text(encoding="utf-8")
                for extra in extras:
                    with self.subTest(document=name, extra=extra):
                        path.write_text(original + "\nRecorded measurement: " + extra, encoding="utf-8")
                        with self.assertRaisesRegex(ValueError, "unexpected_headline_measurement"):
                            check_documents(root, c, t)
                path.write_text(original, encoding="utf-8")

    def test_recorded_metrics_and_documentation_recompute(self):
        value = check(ROOT)
        self.assertEqual(value["status"], "PASS")
        for area, metrics in (("continuity", value["continuity"]), ("typed_decisions", value["typed_decisions"])):
            self.assertEqual(metrics, json.loads((ROOT / "evaluation" / area / "summary.json").read_text()))

    def test_all_recorded_gate_cases_execute_current_policy(self):
        root = ROOT / "evaluation/typed_decisions"
        module = load_script(root / "recompute.py")
        rows, requests, gates, rubric = module.load(root)
        module.replay(gates)
        altered = copy.deepcopy(gates)
        altered[0]["actions"] = ["ALLOW_EXECUTION"]
        self.assertEqual(module.recompute(rows, requests, altered, rubric)["hard_gate_bypasses_observed"], 1)
        with self.assertRaisesRegex(ValueError, "recorded_gate_result_mismatch"):
            module.replay(altered)

    def test_duplicate_judgments_and_invalid_measurements_are_rejected(self):
        root = ROOT / "evaluation/typed_decisions"
        module = load_script(root / "recompute.py")
        rows, requests, gates, rubric = module.load(root)
        with self.assertRaisesRegex(ValueError, "unique_request"):
            module.recompute(rows + [rows[0]], requests, gates, rubric)
        altered = copy.deepcopy(requests)
        altered[0]["latency_ms"] = float("nan")
        with self.assertRaises(ValueError):
            module.recompute(rows, altered, gates, rubric)

    def test_product_surface_is_derived_from_runtime(self):
        surface = derive()
        self.assertEqual(surface, json.loads((ROOT / "docs/runtime_surface.json").read_text()))
        check_docs(ROOT, surface)


if __name__ == "__main__":
    unittest.main()
