from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path


EVIDENCE_DIR = Path(__file__).resolve().parents[1] / "research" / "evidence" / "phase3"
REQUIRED_FILES = (
    "README.md",
    "PHASE3_CLOSEOUT.md",
    "PHASE3_SUMMARY.json",
    "PROVIDER_SUMMARY.json",
    "REGRESSION_SUMMARY.json",
    "RESOURCE_SUMMARY.json",
    "EVIDENCE_MANIFEST.json",
)
BANNED_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:\\(?:Users|Temp|Project|ProgramData|Windows|mnt)\\"),
    re.compile(r"(?i)(?:\\|/)\.codex(?:\\|/)"),
    re.compile(r"(?i)(?:^|[\\/])\.work[\\/]"),
    re.compile(r"(?i)file://"),
    re.compile(r"(?i)\b(?:localhost|127\.0\.0\.1)\b"),
    re.compile(r"(?i)(?:api[_-]?key|token|authorization)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{20,}"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class Phase3EvidencePortabilityTests(unittest.TestCase):
    def test_required_evidence_is_json_valid_sanitized_and_manifested(self) -> None:
        self.assertTrue(EVIDENCE_DIR.is_dir())
        for name in REQUIRED_FILES:
            self.assertTrue((EVIDENCE_DIR / name).is_file(), name)

        for path in EVIDENCE_DIR.iterdir():
            if path.suffix.lower() not in {".md", ".json", ".txt", ".yaml", ".yml", ".toml"}:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in BANNED_PATTERNS:
                self.assertIsNone(pattern.search(text), f"non-portable content in {path.name}")
            if path.suffix.lower() == ".json":
                json.loads(text)

        manifest = json.loads((EVIDENCE_DIR / "EVIDENCE_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "contextcord-evidence-manifest-v1")
        self.assertTrue(manifest["portable"])
        for item in manifest["files"]:
            path = EVIDENCE_DIR / item["path"]
            self.assertTrue(path.is_file(), item["path"])
            self.assertEqual(sha256(path), item["sha256"])

    def test_closeout_preserves_no_performance_claim(self) -> None:
        summary = json.loads((EVIDENCE_DIR / "PHASE3_SUMMARY.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["classification"], "MODEL_PROVIDER_UNAVAILABLE")
        self.assertEqual(summary["valid_s0_trials"], 0)
        self.assertIsNone(summary["performance_conclusion"])
        self.assertEqual(summary["formal_pilot"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
