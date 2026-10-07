from __future__ import annotations

import json
import unittest
from pathlib import Path

from contextcord.host_configs import generate_host_config


class HostConfigTests(unittest.TestCase):
    def test_all_requested_hosts_have_explicit_template_boundary(self) -> None:
        for host in ("codex", "claude", "cursor", "opencode", "qoder", "generic"):
            with self.subTest(host=host):
                value = generate_host_config(host, repo_path=Path.cwd() / "demo")
                self.assertEqual(value["status"], "CONFIG_TEMPLATE_ONLY")
                self.assertIn("contextcord_memory", value["verify"])
                self.assertNotIn("TYPESAFE_API_KEY", value["content"])

    def test_codex_template_is_toml_and_uses_real_stdio_entrypoint(self) -> None:
        value = generate_host_config("codex", repo_path=str(Path.cwd() / "demo"))
        self.assertIn("[mcp_servers.contextcord]", value["content"])
        self.assertNotIn("agent_nexus", value["content"])
        self.assertNotIn('command = "poh"', value["content"])
        self.assertIn('"mcp"', value["content"])

    def test_cursor_and_opencode_templates_are_parseable_json(self) -> None:
        cursor = json.loads(generate_host_config("cursor")["content"])
        self.assertEqual(cursor["mcpServers"]["contextcord"]["args"], ["mcp"])
        opencode = json.loads(generate_host_config("opencode")["content"])
        self.assertEqual(opencode["mcp"]["servers"]["contextcord"]["command"], ["contextcord", "mcp"])

    def test_unknown_host_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            generate_host_config("unknown")


if __name__ == "__main__":
    unittest.main()
