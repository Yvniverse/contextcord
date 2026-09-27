from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from contextcord.closeout import closeout
from contextcord.config import discover
from contextcord.migration import migrate_state
from contextcord.profiles import write_profile
from contextcord.router import build_eligible_set, shadow_route
from contextcord.store import StateStore


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class ContextCordMigrationCloseoutTests(unittest.TestCase):
    def _repo(self, *, state_dir: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        tmp = tempfile.TemporaryDirectory()
        repo = Path(tmp.name)
        subprocess.check_call(["git", "init", "-q", str(repo)])
        git(repo, "config", "user.email", "contextcord@example.com")
        git(repo, "config", "user.name", "ContextCord Tests")
        (repo / "AGENTS.md").write_text("local rules\n", encoding="utf-8")
        write_profile(repo, "generic", state_dir=state_dir)
        if state_dir == ".contextcord":
            git(repo, "add", "AGENTS.md", ".contextcord")
        else:
            git(repo, "add", "AGENTS.md", ".harness")
        git(repo, "commit", "-qm", "initial")
        return tmp, repo

    def test_canonical_state_store_is_local_and_legacy_import_remains_available(self) -> None:
        tmp, repo = self._repo(state_dir=".contextcord")
        try:
            cfg = discover(repo)
            self.assertEqual(cfg.root, repo / ".contextcord")
            self.assertEqual(cfg.notes_ref, "refs/notes/contextcord")
            with StateStore(repo) as store:
                store.event("CANONICAL_STATE_TEST", {"ok": True}, task_id="t")
            self.assertTrue((repo / ".contextcord" / "state.db").is_file())
            self.assertFalse((repo / ".git" / "project-harness" / "state.db").exists())
        finally:
            tmp.cleanup()

    def test_migration_is_dry_run_first_idempotent_and_preserves_legacy_bytes(self) -> None:
        tmp, repo = self._repo(state_dir=".harness")
        try:
            raw = repo / ".harness" / "receipts" / "historical.bin"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(b"historical receipt bytes\x00\xff")
            with StateStore(repo) as store:
                store.event("LEGACY_STATE_TEST", {"ok": True}, task_id="legacy")
            dry = migrate_state(repo)
            self.assertEqual(dry["status"], "DRY_RUN")
            applied = migrate_state(repo, apply=True)
            self.assertEqual(applied["status"], "RECORDED")
            self.assertEqual((repo / ".harness" / "receipts" / "historical.bin").read_bytes(), raw.read_bytes())
            self.assertIn("refs/notes/contextcord", (repo / ".contextcord" / "qualification.toml").read_text(encoding="utf-8"))
            backups = list((repo / ".contextcord" / "migrations").rglob("historical.bin"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), raw.read_bytes())
            self.assertEqual(migrate_state(repo, apply=True)["status"], "NOOP")
            with StateStore(repo) as store:
                self.assertEqual(store.path, repo / ".contextcord" / "state.db")
        finally:
            tmp.cleanup()

    def test_closeout_lock_and_idempotency_protect_memory_and_generated_docs(self) -> None:
        tmp, repo = self._repo(state_dir=".contextcord")
        try:
            cfg = discover(repo)
            head = git(repo, "rev-parse", "HEAD")
            with StateStore(repo) as store:
                store.upsert_task({"task_id": "closeout-task", "scope": "code", "status": "ACTIVE", "current_phase": "tests", "completed": [], "blockers": [], "next_action": "record closeout"})
                session_id = store.create_session(task_id="closeout-task", scope="code", head=head, fingerprint="fixture")
            first = closeout(cfg, task_id="closeout-task", session_id=session_id, summary_text="round one", update_memory=True, update_docs=True, architecture="never")
            self.assertEqual(first["status"], "RECORDED")
            second = closeout(cfg, task_id="closeout-task", session_id=session_id, summary_text="round one", update_memory=True, update_docs=True, architecture="never")
            self.assertEqual(second["status"], "NOOP")
            with StateStore(repo) as store:
                self.assertEqual(len(store.notes_for_task("closeout-task")), 1)
            self.assertEqual(len(list((repo / "docs" / "generated" / "contextcord-closeout").glob("*.md"))), 1)
            lock = cfg.root / "closeout" / "running.lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text("busy\n", encoding="utf-8")
            try:
                locked = closeout(cfg, task_id="closeout-task", session_id=session_id, summary_text="different round", architecture="never")
            finally:
                lock.unlink(missing_ok=True)
            self.assertEqual(locked["status"], "LOCKED")
        finally:
            tmp.cleanup()

    def test_router_closed_set_is_deterministic_and_shadow_never_executes(self) -> None:
        task = {
            "data_boundary": "local",
            "required_tools": ["contextcord_memory"],
            "requested_role": "reviewer",
            "hosts": [
                {"id": "offline", "available": False, "models": [{"id": "m0"}]},
                {"id": "local", "available": True, "logged_in": True, "tools": ["contextcord_memory"], "models": [{"id": "m1", "tier": "reasoning"}]},
            ],
        }
        eligible = build_eligible_set(task)
        self.assertEqual(eligible["eligible_ids"], ["local:m1:reviewer"])
        receipt = shadow_route(task)
        self.assertFalse(receipt["executed"])
        self.assertEqual(receipt["decision"], {"kind": "Choice", "value": "local:m1:reviewer"})
        self.assertEqual(receipt["effective_observed_route"], "unknown")


if __name__ == "__main__":
    unittest.main()
