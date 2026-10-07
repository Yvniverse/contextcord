from __future__ import annotations
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from contextcord.config import ConfigError, discover
from contextcord.host_configs import HOSTS, generate_host_config
from contextcord.profiles import write_profile
from contextcord.service import HarnessService
from contextcord.identity import source_identity

class CompatibilityCleanupTests(unittest.TestCase):
    def test_retired_import_and_tool_names_are_unavailable(self):
        self.assertIsNone(importlib.util.find_spec("project_harness"))
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            write_profile(repo, "generic")
            service = HarnessService(repo, allow_mutations=True)
            names = [row["name"] for row in service.tools()]
            self.assertEqual(len(names), len(set(names)))
            self.assertTrue(all(name.startswith("contextcord_") for name in names))
            self.assertIn("contextcord_memory", names)
            with self.assertRaisesRegex(ValueError, "tool_not_available"):
                service.call("harness_memory", {})
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=ContextCord Tests", "-c", "user.email=tests@example.invalid", "commit", "-qm", "fixture"], check=True)
            self.assertEqual(source_identity(discover(repo))["schema"], "contextcord-source-identity-v1")

    def test_host_configs_emit_one_server_and_canonical_commands(self):
        for host in HOSTS:
            with self.subTest(host=host):
                config = generate_host_config(host)
                self.assertNotIn("agent-nexus", config["content"])
                self.assertNotIn("poh", config["content"])
                if config["format"] == "json":
                    value = json.loads(config["content"])
                    servers = value.get("mcpServers") or value["mcp"]["servers"]
                    self.assertEqual(list(servers), ["contextcord"])

    def test_old_state_requires_explicit_import(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td).resolve()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            write_profile(repo, "generic", state_dir=".harness")
            with self.assertRaises(ConfigError):
                discover(repo)

if __name__ == "__main__":
    unittest.main()
