from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contextcord.adapter_lab import certify_manifest, discover_manifests, init_manifest, load_manifest, render_manifest, validate_manifest


class AdapterLabTests(unittest.TestCase):
    def test_built_in_manifests_validate_and_cover_five_core_hosts(self) -> None:
        rows = discover_manifests()
        self.assertTrue(all(row["status"] == "PASS" for row in rows), rows)
        ids = {row["manifest_id"] for row in rows}
        self.assertTrue({"codex", "qoder", "cursor", "opencode", "workbuddy"}.issubset(ids))

    def test_secret_like_manifest_field_is_rejected(self) -> None:
        value = {"schema": "contextcord-host-adapter-v1", "id": "x", "display_name": "x", "transports": ["stdio"], "required_agent_nexus_tools": ["contextcord_memory"], "api_key": "not allowed"}
        self.assertEqual(validate_manifest(value)["status"], "FAIL")

    def test_canonical_schema_is_emitted_and_retired_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            created = init_manifest("canonical-host", root / "canonical-host.adapter.json")
            self.assertEqual(created["manifest"]["schema"], "contextcord-host-adapter-v1")
            self.assertIn("required_contextcord_tools", created["manifest"])
            legacy = {
                "schema": "contextcord-host-adapter-v1",
                "id": "legacy-host",
                "display_name": "Legacy Host",
                "transports": ["stdio"],
                "required_agent_nexus_tools": ["contextcord_memory"],
            }
            self.assertEqual(validate_manifest(legacy)["status"], "FAIL")

    def test_init_render_and_certification_are_staged_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            created = init_manifest("my-host", root / "my-host.adapter.json")
            self.assertEqual(created["status"], "PASS")
            manifest = load_manifest(root / "my-host.adapter.json")
            rendered = render_manifest(manifest, output=root / "rendered.json", repo=root)
            self.assertEqual(rendered["status"], "PASS")
            self.assertEqual(certify_manifest(manifest)["status"], "PARTIAL")
            self.assertEqual(json.loads((root / "rendered.json").read_text(encoding="utf-8"))["manifest_id"], "my-host")


if __name__ == "__main__":
    unittest.main()
