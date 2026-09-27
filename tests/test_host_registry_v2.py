import unittest
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from contextcord.host_registry import (
    BUILTIN_HOST_IDS,
    LEGACY_BUILTIN_HOST_IDS,
    LEGACY_REGISTRY_SCHEMA,
    REGISTRY_SCHEMA,
    load_registry,
    normalize_registry,
    summary,
)


class HostRegistryV3Tests(unittest.TestCase):
    def test_exact_builtin_hosts_and_byoh(self):
        value = load_registry(".")
        self.assertEqual(list(BUILTIN_HOST_IDS), [row["host_id"] for row in value["built_in_hosts"]])
        self.assertEqual(REGISTRY_SCHEMA, value["schema"])
        self.assertEqual("BYOH", value["byoh"]["product_tier"])
        self.assertEqual([], summary(".")["qualified_current_hosts"])

    def test_v2_registry_is_normalized_without_legacy_schema_leaking_to_new_shape(self):
        legacy = {
            "schema": LEGACY_REGISTRY_SCHEMA,
            "registry_version": "A12.2",
            "built_in_hosts": [
                {
                    "host_id": host_id,
                    "display_name": host_id.title(),
                    "product_tier": "BUILT_IN",
                    "adapter_contract": {
                        "status": "PASS",
                        "manifest": f"support/adapters/{host_id}.adapter.json",
                        "manifest_schema": "contextcord-host-adapter-v1",
                    },
                    "config_contract": {"status": "PASS", "format": "stdio"},
                    "native_continuation": {"status": "NOT_RUN", "evidence_refs": []},
                    "benchmark": {
                        "generation": "A12.2-v3",
                        "status": "NOT_RUN",
                        "qualified": False,
                        "evidence": [],
                    },
                    "limitations": [],
                }
                for host_id in LEGACY_BUILTIN_HOST_IDS
            ],
            "byoh": {"product_tier": "BYOH", "manifest_schema": "contextcord-host-adapter-v1"},
            "truth_boundary": "legacy evidence remains historical",
        }
        value = normalize_registry(legacy)
        self.assertEqual(REGISTRY_SCHEMA, value["schema"])
        self.assertEqual(list(LEGACY_BUILTIN_HOST_IDS), [row["host_id"] for row in value["built_in_hosts"]])
        self.assertIn("integration", value["built_in_hosts"][0])
        self.assertNotIn("adapter_contract", value["built_in_hosts"][0])

    def test_qualified_v3_row_requires_protocol_and_evidence(self):
        value = load_registry(".")
        row = value["built_in_hosts"][0]
        row["qualification"] = {
            "status": "PASS",
            "qualified": True,
            "protocol_id": "context-sufficiency-v1",
            "evidence_refs": ["research/example.json"],
        }
        self.assertTrue(normalize_registry({**value, "built_in_hosts": [row] + value["built_in_hosts"][1:]})["built_in_hosts"][0]["qualification"]["qualified"])

    def test_v3_document_validates_against_contextcord_schema(self):
        value = load_registry(".")
        schema = json.loads(Path("schemas/host-evidence-registry.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(value)


if __name__ == "__main__":
    unittest.main()
