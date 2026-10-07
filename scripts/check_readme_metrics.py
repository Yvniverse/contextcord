"""Verify headline documentation against independently recomputed artifacts."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import json

HEADLINE_FILES = (
    "README.md",
    "README_CN.md",
    "docs/EVALUATION.md",
    "docs/EVALUATION_CN.md",
    "evaluation/continuity/README.md",
)


def load_script(path: Path):
    spec = importlib.util.spec_from_file_location(path.parent.name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_documents(root: Path, c: dict, t: dict) -> None:
    continuity_required = [
        f"{c['notes_recovered']:,}",
        f"{c['bounded_text_to_handoff_byte_reduction'] * 100:.1f}%",
        f"{c['handoff_json_utf8_bytes']:,}",
        f"{c['bounded_text_utf8_bytes']:,}",
        f"{c['task_fields_lossless']}/{c['replays']}",
        str(c['changed_dependency_notes_revalidated']),
    ]
    typed_required = [f"{t['correct_judgments']}/{t['planned_judgments']}",
                      f"{t['agreement'] * 100:.1f}%"]
    expected_percentages = {continuity_required[1], typed_required[1]}
    baseline_bytes = c['bounded_text_utf8_bytes'] // c['replays']
    expected_grouped_numbers = {f"{c['notes_recovered']:,}", f"{c['handoff_json_utf8_bytes']:,}",
                                f"{c['bounded_text_utf8_bytes']:,}", f"{baseline_bytes:,}"}
    for name in HEADLINE_FILES:
        text = (root / name).read_text(encoding="utf-8")
        required = continuity_required + ([] if name == "evaluation/continuity/README.md" else typed_required)
        missing = [value for value in required if value not in text]
        if missing:
            raise ValueError(f"headline_metric_missing_or_changed:{name}:{missing}")
        if name != "evaluation/continuity/README.md" and not re.search(rf"\b{t['latency_p95_ms']:.0f}\s+ms\b", text):
            raise ValueError(f"headline_latency_missing_or_changed:{name}")
        # Check every displayed percentage and grouped count, including prose.
        # Expected values come from rows, so obsolete figures need no literals.
        percentages = set(re.findall(r"(?<![\d.])\d+(?:\.\d+)?%", text))
        grouped_numbers = set(re.findall(r"(?<![\w.,])\d{1,3}(?:,\d{3})+(?![\w.,])", text))
        if percentages - expected_percentages or grouped_numbers - expected_grouped_numbers:
            raise ValueError(f"unexpected_headline_measurement:{name}")

    required = [f"{c['notes_recovered']:,}", f"{c['bounded_text_to_handoff_byte_reduction'] * 100:.1f}%",
                f"{t['correct_judgments']}/{t['planned_judgments']}", f"{t['agreement'] * 100:.1f}%",
                f"{c['handoff_json_utf8_bytes']:,} B", f"{c['bounded_text_utf8_bytes']:,} B",
                f"{c['task_fields_lossless']}/{c['replays']}", f"{c['tampered_objects_rejected']}/{c['replays']}",
                str(c["changed_dependency_notes_revalidated"]), f"P95 {t['latency_p95_ms']:.0f} ms",
                f"{t['hard_gate_bypasses_observed']}/{t['hard_gate_controls']}"]
    for name in ("README.md", "README_CN.md"):
        text = (root / name).read_text(encoding="utf-8")
        if any(value not in text for value in required):
            raise ValueError(f"readme_metric_missing_or_changed:{name}")
        lines = [line for line in text.splitlines() if line.startswith("|")]
        numeric_rows = [line for line in lines if re.search(r"(?<![A-Za-z0-9])\d", line)]
        all_numbers = {match.group() for line in numeric_rows for match in re.finditer(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?", line)}
        # The allowed values are generated from the observations, including
        # the decimal display precision and baseline size in decimal KB.
        expected_numbers = {f"{c['notes_recovered']:,}", f"{100*c['bounded_text_to_handoff_byte_reduction']:.1f}",
                            str(t['correct_judgments']), str(t['planned_judgments']), str(c['replays']),
                            f"{c['handoff_json_utf8_bytes']:,}", f"{c['bounded_text_utf8_bytes']:,}",
                            str(c['changed_dependency_notes_revalidated']), str(c['stale_notes_selected_after_drift']),
                            f"{100*t['agreement']:.1f}", str(t['live_requests']), "95", f"{t['latency_p95_ms']:.0f}",
                            str(c['bounded_text_utf8_bytes']//c['replays']//1000)}
        if all_numbers - expected_numbers:
            raise ValueError("unexpected_readme_table_measurement")


def check(root: Path) -> dict:
    croot, troot = root / "evaluation/continuity", root / "evaluation/typed_decisions"
    c = load_script(croot / "recompute.py").recompute(json.loads((croot / "results.json").read_text(encoding="utf-8")))
    tm = load_script(troot / "recompute.py")
    t = tm.recompute(*tm.load(troot))
    check_documents(root, c, t)
    return {"status": "PASS", "continuity": c, "typed_decisions": t}


if __name__ == "__main__":
    print(json.dumps(check(Path(__file__).resolve().parents[1]), indent=2))
