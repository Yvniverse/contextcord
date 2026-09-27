from __future__ import annotations

import json
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from contextcord.capabilities import CapabilityConfigError, SPECS, product_module_projection, resolve_features, status
from contextcord.cli import main
from contextcord.config import discover
from contextcord.handoff import assist_resume
from contextcord.providers import inspect_jev
from contextcord.profiles import write_profile
from contextcord.service import HarnessService
from contextcord.store import StateStore
from contextcord.workflow import initial_task


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class ModularCapabilityTests(unittest.TestCase):
    def make_repo(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name)
        subprocess.check_call(["git", "init", "-q", str(repo)])
        _git(repo, "config", "user.email", "capabilities@example.com")
        _git(repo, "config", "user.name", "ContextCord Capabilities")
        (repo / "AGENTS.md").write_text("rules\n", encoding="utf-8")
        write_profile(repo, "generic", state_dir=".contextcord")
        subprocess.check_call(["git", "-C", str(repo), "add", "."])
        subprocess.check_call(["git", "-C", str(repo), "commit", "-qm", "initial"])
        return td, repo

    def test_profiles_and_explicit_dependency_conflict(self) -> None:
        resolved = resolve_features({"features": {"profile": "custom", "enable": ["router"], "disable": []}})
        self.assertEqual(resolved["effective"], ["core", "decision", "router"])
        with self.assertRaises(CapabilityConfigError) as ctx:
            resolve_features({"features": {"profile": "continuity", "enable": [], "disable": ["memory"]}})
        self.assertEqual(ctx.exception.code, "explicit_disable_dependency_conflict")

    def test_continuity_profile_has_no_decision_plane_dependency(self) -> None:
        resolved = resolve_features({"features": {"profile": "continuity", "enable": [], "disable": []}})
        self.assertEqual(SPECS["handoff"].requires, ("continuity", "memory"))
        self.assertNotIn("decision", resolved["effective"])
        self.assertNotIn("router", resolved["effective"])
        self.assertNotIn("jev", resolved["effective"])
        self.assertNotIn("model_intelligence", resolved["effective"])

    def test_product_modules_are_derived_from_the_single_registry(self) -> None:
        value = product_module_projection(resolve_features({"features": {"profile": "continuity"}}))
        self.assertEqual([row["name"] for row in value["modules"]], [
            "Continuum", "Context Engine", "Veritas", "Decision Plane", "MCP / Host Gateway", "Jev",
        ])
        mapping = {row["id"]: row["capabilities"] for row in value["modules"]}
        self.assertEqual(mapping["continuum"], ["continuity", "handoff", "closeout"])
        self.assertEqual(mapping["context_engine"], ["continuity", "memory"])
        self.assertEqual(mapping["decision_plane"], ["decision", "router", "model_intelligence"])
        self.assertEqual(value["state_store"], "single repository-local StateStore")
        self.assertTrue(all(row["state"] in {"disabled", "degraded", "ready"} for row in value["modules"]))

    def test_decision_profile_is_ready_without_default_jev(self) -> None:
        decision = resolve_features({"features": {"profile": "decision"}})
        self.assertNotIn("jev", decision["effective"])
        decision_status = status({"features": {"profile": "decision"}})
        jev_row = next(row for row in decision_status["capabilities"] if row["id"] == "jev")
        self.assertFalse(jev_row["effective"])
        self.assertTrue(next(row for row in decision_status["capabilities"] if row["id"] == "decision")["ready"])

    def test_explicit_jev_and_full_profile_keep_jev_optional(self) -> None:
        explicit = resolve_features({"features": {"profile": "decision", "enable": ["jev"]}})
        full = resolve_features({"features": {"profile": "full"}})
        self.assertIn("jev", explicit["effective"])
        self.assertIn("jev", full["effective"])
        projection = product_module_projection(full)
        jev = next(row for row in projection["modules"] if row["id"] == "jev")
        self.assertTrue(jev["active"])
        self.assertIn(jev["state"], {"degraded", "ready"})

    def test_continuity_handoff_and_mcp_surface_work_without_decision_plane(self) -> None:
        td, repo = self.make_repo()
        try:
            project = repo / ".contextcord" / "project.toml"
            project.write_text(
                project.read_text(encoding="utf-8")
                + '\n[features]\nprofile = "continuity"\nenable = []\ndisable = []\n',
                encoding="utf-8",
            )
            cfg = discover(repo)
            task = initial_task("continuity-task", "code", cfg.workflow)
            task["next_action"] = "continue the deterministic handoff test"
            with StateStore(repo) as store, store.transaction():
                store.upsert_task(task)
                store.create_note(task_id="continuity-task", text="Keep the local continuation bounded.")

            import contextcord.handoff as handoff_module
            self.assertNotIn("DecisionFabric", handoff_module.__dict__)
            preview = assist_resume(cfg, task_id="continuity-task", host="qoder")
            self.assertEqual(preview["status"], "AWAITING_CONFIRMATION")
            confirmed = assist_resume(cfg, task_id="continuity-task", host="qoder", confirm=True)
            self.assertEqual(confirmed["status"], "PASS")

            names = {row["name"] for row in HarnessService(repo, allow_mutations=True).tools()}
            self.assertIn("contextcord_resume", names)
            self.assertIn("contextcord_resume_confirm", names)
            self.assertNotIn("contextcord_decision_fabric", names)
            self.assertNotIn("contextcord_route_model", names)
        finally:
            td.cleanup()

    def test_decision_and_router_cli_remain_available_without_mcp(self) -> None:
        td, repo = self.make_repo()
        try:
            project = repo / ".contextcord" / "project.toml"
            project.write_text(
                project.read_text(encoding="utf-8")
                + '\n[features]\nprofile = "decision"\nenable = []\ndisable = []\n',
                encoding="utf-8",
            )
            self.assertEqual(HarnessService(repo).tools(), [])
            state_file = repo / "decision-state.json"
            state_file.write_text("{}\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--repo", str(repo), "decision", "fabric", "--state-file", str(state_file)]), 0)
            self.assertEqual(json.loads(output.getvalue())["schema"], "agent-nexus-jev-decision-receipt-v1")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--repo", str(repo), "router", "shadow", "--input", str(state_file)]), 0)
            self.assertEqual(json.loads(output.getvalue())["schema"], "contextcord-subagent-routing-shadow-v1")
        finally:
            td.cleanup()

    def test_jev_status_never_returns_dotenv_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = "tsf_secret_marker_must_not_escape"
            Path(directory, ".env").write_text(f"TYPESAFE_API_KEY={marker}\n", encoding="utf-8")
            value = inspect_jev(project_root=directory, feature_enabled=True, provider_config={})
            self.assertEqual(value["key_source"], "project_dotenv_present")
            self.assertFalse(value["secret_value_exposed"])
            self.assertNotIn(marker, json.dumps(value))

    def test_dynamic_mcp_surface_and_local_outcome_summary(self) -> None:
        td, repo = self.make_repo()
        try:
            project = repo / ".contextcord" / "project.toml"
            project.write_text(
                project.read_text(encoding="utf-8")
                + '\n[features]\nprofile = "decision"\nenable = []\ndisable = []\n',
                encoding="utf-8",
            )
            names = {row["name"] for row in HarnessService(repo).tools()}
            # The decision profile intentionally omits the MCP transport. A
            # direct HarnessService must therefore expose no active surface,
            # even though the router capability itself is enabled.
            self.assertEqual(names, set())
            with self.assertRaisesRegex(ValueError, "tool_not_available"):
                HarnessService(repo).call("contextcord_route_model", {"state": {}})
            with StateStore(repo) as store:
                store.record_model_outcome(
                    task_class="bugfix",
                    role="implementer",
                    model_id="gpt-5.6-luna",
                    reasoning_effort="medium",
                    verifier_pass=True,
                    elapsed_ms=42,
                )
                rows = store.model_outcome_summary()
            self.assertEqual(rows[0]["successes"], 1)
            self.assertEqual(rows[0]["failures"], 0)
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
