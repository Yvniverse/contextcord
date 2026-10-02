from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from contextcord.cli import main
from contextcord.profiles import write_profile
from contextcord.service import HarnessService
from contextcord.store import StateStore
from contextcord.util import sha256_json


def call(repo: Path, *args: str):
    output = io.StringIO()
    with redirect_stdout(output):
        rc = main(["--repo", str(repo), *args])
    return rc, json.loads(output.getvalue()) if output.getvalue().strip() else {}


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class PortableMemoryTests(unittest.TestCase):
    def make_repo(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        td = tempfile.TemporaryDirectory(); repo = Path(td.name)
        subprocess.check_call(["git", "init", "-q", str(repo)])
        git(repo, "config", "user.email", "memory@example.com")
        git(repo, "config", "user.name", "Portable Memory")
        (repo / "AGENTS.md").write_text("rules\n", encoding="utf-8")
        (repo / "README.md").write_text("readme\n", encoding="utf-8")
        (repo / "src").mkdir(); (repo / "src" / "app.py").write_text("print('v1')\n", encoding="utf-8")
        write_profile(repo, "generic")
        git(repo, "add", "."); git(repo, "commit", "-qm", "initial")
        return td, repo

    def seed_live_memory(self, repo: Path) -> tuple[str, str, Path]:
        self.assertEqual(call(repo, "start", "--task-id", "task-migrate", "--scope", "code", "--json")[0], 0)
        with StateStore(repo) as store:
            sid = store.open_sessions("task-migrate")[0]["session_id"]
        self.assertEqual(call(repo, "memory", "note", "add", "--task-id", "task-migrate", "--session-id", sid,
                              "--note-id", "note-1", "--text", "Keep retry bounded", "--depends-on", "src/app.py")[0], 0)
        self.assertEqual(call(repo, "memory", "note", "add", "--task-id", "task-migrate", "--session-id", sid,
                              "--note-id", "note-2", "--text", "README is unrelated", "--depends-on", "README.md")[0], 0)
        self.assertEqual(call(repo, "memory", "job", "record", "--task-id", "task-migrate", "--session-id", sid,
                              "--job-id", "job-1", "--provider", "deterministic-fallback", "--packet", '{"facts":["retry"]}',
                              "--archive-ref", "trace-1")[0], 0)
        evidence = repo / ".contextcord" / "generated" / "evidence" / "history.txt"
        evidence.parent.mkdir(parents=True, exist_ok=True); evidence.write_text("historical evidence\n", encoding="utf-8")
        self.assertEqual(call(repo, "evidence", "add", "--session-id", sid, "--name", "historical-pass", "--status", "PASS", "--path", ".contextcord/generated/evidence/history.txt")[0], 0)
        self.assertEqual(call(repo, "evidence", "add", "--session-id", sid, "--name", "historical-fail", "--status", "FAIL", "--path", ".contextcord/generated/evidence/history.txt", "--reason", "known regression")[0], 0)
        return "task-migrate", sid, evidence

    def test_live_memory_fresh_root_mcp_resume_recheck_and_idempotence(self) -> None:
        source_td, source = self.make_repo(); clone_td = tempfile.TemporaryDirectory(); third_td = tempfile.TemporaryDirectory()
        try:
            task_id, source_sid, _ = self.seed_live_memory(source)
            bundle = Path(source_td.name) / "memory-a9.zip"
            self.assertEqual(call(source, "memory", "export", "--task-id", task_id, "--out", str(bundle))[0], 0)
            raw_bundle = bundle.read_bytes()
            self.assertNotIn(b".env", raw_bundle); self.assertNotIn(str(source).encode(), raw_bundle)

            clone = Path(clone_td.name) / "fresh-root"; subprocess.check_call(["git", "clone", "-q", str(source), str(clone)])
            rc, dry = call(clone, "memory", "import", "--bundle", str(bundle), "--dry-run"); self.assertEqual(rc, 0, dry); self.assertEqual(dry["action"], "IMPORT")
            rc, imported = call(clone, "memory", "import", "--bundle", str(bundle)); self.assertEqual(rc, 0, imported); self.assertEqual(imported["action"], "IMPORTED")
            rc, shown = call(clone, "memory", "show", "--task-id", task_id); self.assertEqual(rc, 0, shown)
            self.assertEqual({row["note_id"] for row in shown["notes"]}, {"note-1", "note-2"})
            self.assertEqual({row["classification"] for row in shown["evidence"]}, {"HISTORICAL"})
            self.assertEqual(shown["current_qualification"], "NOT_EVALUATED")
            self.assertEqual({row["job_id"] for row in shown["context_jobs"]}, {"job-1"})

            server = HarnessService(clone)
            value = server.call("contextcord_memory", {"task_id": task_id})
            self.assertEqual(value["task"]["task_id"], task_id)
            self.assertIn("note-1", {row["note_id"] for row in value["notes"]})

            rc, resumed = call(clone, "memory", "resume", "--task-id", task_id, "--scope", "code"); self.assertEqual(rc, 0, resumed)
            target_sid = resumed["session_id"]
            self.assertNotEqual(target_sid, source_sid)
            self.assertTrue(any(row["session_id"] == target_sid for row in resumed["sessions"]))
            self.assertEqual(call(clone, "memory", "note", "add", "--task-id", task_id, "--session-id", target_sid,
                                  "--note-id", "note-3", "--text", "Continue from the imported session")[0], 0)

            (clone / "src" / "app.py").write_text("print('v2')\n", encoding="utf-8")
            rc, rechecked = call(clone, "memory", "show", "--task-id", task_id); self.assertEqual(rc, 0, rechecked)
            statuses = {item["path"]: item["status"] for note in rechecked["notes"] for item in note["dependency_status"]}
            self.assertEqual(statuses["src/app.py"], "STALE")
            self.assertEqual(statuses["README.md"], "UNCHANGED")
            self.assertEqual(rechecked["current_qualification"], "NOT_EVALUATED")

            rc, noop = call(clone, "memory", "import", "--bundle", str(bundle)); self.assertEqual(rc, 0, noop); self.assertEqual(noop["action"], "NOOP")
            with StateStore(clone) as store:
                self.assertEqual(len(store.notes_for_task(task_id)), 3)

            bundle2 = Path(clone_td.name) / "memory-a9-b2.zip"
            self.assertEqual(call(clone, "memory", "export", "--task-id", task_id, "--out", str(bundle2))[0], 0)
            third = Path(third_td.name) / "third-root"; subprocess.check_call(["git", "clone", "-q", str(source), str(third)])
            rc, imported2 = call(third, "memory", "import", "--bundle", str(bundle2)); self.assertEqual(rc, 0, imported2)
            with StateStore(third) as store:
                self.assertEqual(len(store.notes_for_task(task_id)), 3)
                self.assertEqual(len(store.sessions_for_task(task_id)), 2)
        finally:
            source_td.cleanup(); clone_td.cleanup(); third_td.cleanup()

    def test_tamper_path_traversal_and_conflicting_event_are_rejected_without_mutation(self) -> None:
        source_td, source = self.make_repo(); target_td = tempfile.TemporaryDirectory(); out_td = tempfile.TemporaryDirectory()
        try:
            task_id, _, _ = self.seed_live_memory(source)
            bundle = Path(out_td.name) / "memory.zip"
            self.assertEqual(call(source, "memory", "export", "--task-id", task_id, "--out", str(bundle))[0], 0)
            target = Path(target_td.name) / "target"; subprocess.check_call(["git", "clone", "-q", str(source), str(target)])

            traversal = Path(out_td.name) / "traversal.zip"
            with zipfile.ZipFile(bundle) as source_zip:
                manifest = json.loads(source_zip.read("manifest.json"))
                manifest["dependency_refs"] = [{"path": "../escape", "expected_sha256": None}]
                manifest["bundle_sha256"] = sha256_json(manifest, exclude_keys=("bundle_sha256",))
                with zipfile.ZipFile(traversal, "w", compression=zipfile.ZIP_DEFLATED) as dest:
                    for name in source_zip.namelist():
                        dest.writestr(name, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if name == "manifest.json" else source_zip.read(name))
            rc, value = call(target, "memory", "import", "--bundle", str(traversal)); self.assertNotEqual(rc, 0); self.assertIn("portable_memory_dependency", value["error"])
            with StateStore(target) as store:
                self.assertIsNone(store.get_task(task_id))

            conflict = Path(out_td.name) / "conflict.zip"
            with zipfile.ZipFile(bundle) as source_zip:
                manifest = json.loads(source_zip.read("manifest.json")); members = {name: source_zip.read(name) for name in source_zip.namelist()}
            event_entry = next(row for row in manifest["objects"] if row["kind"] == "event")
            old_path = event_entry["path"]; event = json.loads(members[old_path].decode("utf-8")); event["payload"] = {"conflict": True}
            body = {key: event.get(key) for key in ("event_id", "session_id", "task_id", "event_type", "ts", "payload", "prev_hash")}
            event["event_hash"] = sha256_json(body); raw = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            digest = __import__("hashlib").sha256(raw).hexdigest(); new_path = f"objects/{digest}.json"; members.pop(old_path); members[new_path] = raw
            event_entry["path"] = new_path; event_entry["sha256"] = digest; event_entry["bytes"] = len(raw)
            manifest["bundle_sha256"] = sha256_json(manifest, exclude_keys=("bundle_sha256",))
            with zipfile.ZipFile(conflict, "w", compression=zipfile.ZIP_DEFLATED) as dest:
                for name, raw_member in members.items():
                    dest.writestr(name if name != "manifest.json" else name, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n" if name == "manifest.json" else raw_member)
            # First import the clean bundle, then the valid-but-conflicting copy.
            self.assertEqual(call(target, "memory", "import", "--bundle", str(bundle))[0], 0)
            with StateStore(target) as store:
                before = len(store.notes_for_task(task_id))
            rc, value = call(target, "memory", "import", "--bundle", str(conflict)); self.assertNotEqual(rc, 0); self.assertIn("portable_memory_event_conflict", json.dumps(value))
            with StateStore(target) as store:
                self.assertEqual(len(store.notes_for_task(task_id)), before)
        finally:
            source_td.cleanup(); target_td.cleanup(); out_td.cleanup()


if __name__ == "__main__":
    unittest.main()
