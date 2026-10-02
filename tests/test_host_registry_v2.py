import unittest
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from contextcord.host_registry import (
    BUILTIN_HOST_IDS,
    REGISTRY_SCHEMA,
    RegistryError,
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

    def test_retired_registry_schema_is_rejected(self):
        with self.assertRaisesRegex(RegistryError, "registry_schema_invalid"):
            normalize_registry({"schema": "agent-nexus-host-evidence-registry-v2"})

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
