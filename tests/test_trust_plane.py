from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from project_harness.cli import main
from project_harness.config import ConfigError, discover
from project_harness.dualrun import ledger_path, read_ledger, record as dual_record, summary as dual_summary
from project_harness.evidence import prepare_records
from project_harness.identity import memory_commit_errors, source_identity
from project_harness.policy import authorize
from project_harness.profiles import write_profile
from project_harness.qualification import record as qualification_record
from project_harness.qualification import verify as qualification_verify
from project_harness.receipt import verify_receipt_chain
from project_harness.store import StateStore
from project_harness.truth import content_fingerprint


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def invoke(repo: Path, *args: str) -> tuple[int, dict]:
    out = io.StringIO(); err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(["--repo", str(repo), *args])
    text = out.getvalue().strip()
    value = json.loads(text) if text else {"stderr": err.getvalue().strip()}
    return rc, value


class RepoCase(unittest.TestCase):
    def make_repo(self, *, exact: bool = False) -> tuple[tempfile.TemporaryDirectory, Path]:
        td = tempfile.TemporaryDirectory(); repo = Path(td.name)
        subprocess.check_call(["git", "init", "-q", str(repo)])
        git(repo, "config", "user.email", "trust@example.com"); git(repo, "config", "user.name", "Trust Test")
        (repo / "AGENTS.md").write_text("# policy\n", encoding="utf-8")
        (repo / "src").mkdir(); (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        write_profile(repo, "generic")
        if exact:
            p = repo / ".harness" / "project.toml"
            p.write_text(p.read_text(encoding="utf-8").replace('mode = "content_equivalent"', 'mode = "exact_commit"'), encoding="utf-8")
        git(repo, "add", "."); git(repo, "commit", "-qm", "initial")
        return td, repo

    def start(self, repo: Path, task: str = "t", scope: str = "code") -> str:
        rc, _ = invoke(repo, "start", "--task-id", task, "--scope", scope, "--json")
        self.assertEqual(rc, 0)
        with StateStore(repo) as store:
            return store.open_sessions(task)[0]["session_id"]

    def add_pass(self, repo: Path, sid: str, *, name: str = "unit") -> Path:
        p = repo / ".harness" / "generated" / "manual" / f"{name}.txt"
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text("PASS\n", encoding="utf-8")
        rc, value = invoke(repo, "evidence", "add", "--session-id", sid, "--name", name, "--status", "PASS", "--path", p.relative_to(repo).as_posix())
        self.assertEqual(rc, 0, value)
        return p

    def complete_workflow(self, repo: Path, sid: str, task: str = "t", *, add_evidence: bool = True) -> None:
        for phase in ("authority", "implementation"):
            rc, value = invoke(repo, "state", "advance", "--task-id", task, "--phase", phase, "--next-action", "next", "--session-id", sid)
            self.assertEqual(rc, 0, value)
        if add_evidence:
            self.add_pass(repo, sid)
        rc, value = invoke(repo, "state", "advance", "--task-id", task, "--phase", "tests", "--next-action", "finish", "--session-id", sid)
        self.assertEqual(rc, 0, value)


def symlinks_available():
    with tempfile.TemporaryDirectory() as td:
        try:
            p = Path(td) / "link"
            p.symlink_to(Path(td) / "target")
            p.unlink()
            return True
        except OSError:
            return False


SYMLINKS_AVAILABLE = symlinks_available()


class TrustPlaneTests(RepoCase):
    def test_premature_finish_is_blocked_and_does_not_close_session(self):
        td, repo = self.make_repo()
        try:
            sid = self.start(repo)
            rc, value = invoke(repo, "finish", "--session-id", sid, "--summary-text", "premature")
            self.assertEqual(rc, 2); self.assertEqual(value["status"], "BLOCKED")
            self.assertTrue(any("workflow_phases_incomplete" in x for x in value["failures"]))
            with StateStore(repo) as store:
                self.assertEqual(store.session(sid)["status"], "OPEN")
                self.assertEqual(store.evidence_for_session(sid), [])
        finally: td.cleanup()

    def test_failed_finish_does_not_partially_persist_summary_evidence(self):
        td, repo = self.make_repo()
        try:
            sid = self.start(repo)
            ev = repo / ".harness" / "generated" / "manual" / "summary.txt"; ev.parent.mkdir(parents=True, exist_ok=True); ev.write_text("PASS\n")
            summary = repo / ".harness" / "generated" / "summary.json"
            summary.write_text(json.dumps({"summary":"x","tests":[{"name":"summary-check","status":"PASS","evidence":ev.relative_to(repo).as_posix()}],"evidence_paths":[ev.relative_to(repo).as_posix()]}), encoding="utf-8")
            rc, value = invoke(repo, "finish", "--session-id", sid, "--summary-file", str(summary))
            self.assertEqual(rc, 2); self.assertEqual(value["status"], "BLOCKED")
            with StateStore(repo) as store:
                self.assertEqual(store.evidence_for_session(sid), [])
        finally: td.cleanup()

    def test_zero_evidence_complete_closeout_is_impossible_even_without_phase_evidence_contract(self):
        td, repo = self.make_repo()
        try:
            wf = repo / ".harness" / "workflow.toml"
            text = wf.read_text(); text = text.replace('[phase_contracts.tests]\nminimum_pass_evidence = 1\n', '')
            wf.write_text(text); git(repo, "add", ".harness/workflow.toml"); git(repo, "commit", "-qm", "allow no phase evidence")
            sid = self.start(repo)
            self.complete_workflow(repo, sid, add_evidence=False)
            rc, value = invoke(repo, "finish", "--session-id", sid, "--summary-text", "no evidence")
            self.assertEqual(rc, 2); self.assertIn("complete_closeout_requires_evidence", value["failures"])
        finally: td.cleanup()

    def test_policy_drift_blocks_manual_finish_in_core(self):
        td, repo = self.make_repo()
        try:
            sid = self.start(repo); self.complete_workflow(repo, sid)
            (repo / "AGENTS.md").write_text("# changed policy\n", encoding="utf-8")
            rc, value = invoke(repo, "finish", "--session-id", sid, "--summary-text", "should block")
            self.assertEqual(rc, 2); self.assertIn("policy_drift_since_session_start", value["failures"])
            with StateStore(repo) as store: self.assertEqual(store.session(sid)["status"], "OPEN")
        finally: td.cleanup()

    def test_content_equivalent_receipt_survives_empty_commit(self):
        td, repo = self.make_repo(exact=False)
        try:
            sid = self.start(repo); self.complete_workflow(repo, sid)
            self.assertEqual(invoke(repo, "finish", "--session-id", sid, "--summary-text", "sealed")[0], 0)
            git(repo, "commit", "--allow-empty", "-qm", "identity-only")
            rc, value = invoke(repo, "verify", "--ci")
            self.assertEqual(rc, 0, value); self.assertEqual(value["status"], "PASS")
        finally: td.cleanup()

    def test_exact_commit_receipt_does_not_survive_same_tree_new_commit(self):
        td, repo = self.make_repo(exact=True)
        try:
            sid = self.start(repo); self.complete_workflow(repo, sid)
            self.assertEqual(invoke(repo, "finish", "--session-id", sid, "--summary-text", "sealed")[0], 0)
            git(repo, "commit", "--allow-empty", "-qm", "same tree new commit")
            rc, value = invoke(repo, "verify", "--ci")
            self.assertEqual(rc, 2); self.assertIn("no_complete_closeout_receipt_matches_current_source_identity", value["failures"])
        finally: td.cleanup()

    def test_exact_commit_pass_evidence_requires_clean_truth(self):
        td, repo = self.make_repo(exact=True)
        try:
            sid = self.start(repo)
            (repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
            ev = repo / ".harness" / "generated" / "manual" / "unit.txt"; ev.parent.mkdir(parents=True, exist_ok=True); ev.write_text("PASS\n")
            rc, value = invoke(repo, "evidence", "add", "--session-id", sid, "--name", "unit", "--status", "PASS", "--path", ev.relative_to(repo).as_posix())
            self.assertEqual(rc, 2); self.assertIn("exact_identity_evidence_requires_clean_truth", value["error"])
        finally: td.cleanup()

    def test_exact_commit_dirty_truth_blocks_finish(self):
        td, repo = self.make_repo(exact=True)
        try:
            sid = self.start(repo); self.complete_workflow(repo, sid)
            (repo / "src" / "app.py").write_text("VALUE = 9\n", encoding="utf-8")
            rc, value = invoke(repo, "finish", "--session-id", sid, "--summary-text", "dirty")
            self.assertEqual(rc, 2); self.assertTrue(any(x.startswith("exact_commit_requires_clean_truth") for x in value["failures"]))
        finally: td.cleanup()

    def test_receipt_tamper_is_detected(self):
        td, repo = self.make_repo()
        try:
            sid = self.start(repo); self.complete_workflow(repo, sid); self.assertEqual(invoke(repo, "finish", "--session-id", sid, "--summary-text", "sealed")[0], 0)
            path = next((repo / ".harness" / "receipts").glob("*.json")); payload = json.loads(path.read_text()); payload["summary"]["summary"] = "tampered"; path.write_text(json.dumps(payload), encoding="utf-8")
            rc, value = invoke(repo, "verify", "--ci")
            self.assertEqual(rc, 2); self.assertTrue(any("receipt_hash_mismatch" in x for x in value["failures"]))
        finally: td.cleanup()

    def test_deleting_receipt_chain_root_is_detected(self):
        td, repo = self.make_repo()
        try:
            for task in ("a", "b"):
                sid = self.start(repo, task); self.complete_workflow(repo, sid, task); self.assertEqual(invoke(repo, "finish", "--session-id", sid, "--summary-text", task)[0], 0)
            receipts = sorted((repo / ".harness" / "receipts").glob("*.json")); self.assertEqual(len(receipts), 2)
            # Find the root explicitly rather than relying on filename order.
            root = next(p for p in receipts if json.loads(p.read_text()).get("previous_receipt_hash") is None); root.unlink()
            rc, value = invoke(repo, "receipt", "--verify-chain")
            self.assertEqual(rc, 2); self.assertTrue(any("missing_parent" in x or "root_count" in x for x in value["errors"]))
        finally: td.cleanup()

    @unittest.skipUnless(SYMLINKS_AVAILABLE, "OS account cannot create symlinks; covered by Linux CI")
    def test_source_symlink_hashes_literal_target_and_executable_bit(self):
        td, repo = self.make_repo()
        outside_td = tempfile.TemporaryDirectory()
        try:
            cfg = discover(repo); outside = Path(outside_td.name) / "data.txt"; outside.write_text("v1\n")
            link = repo / "src" / "external"; link.symlink_to(outside)
            first = content_fingerprint(cfg); row = next(x for x in first["files"] if x["path"] == "src/external"); self.assertEqual(row["object_type"], "symlink")
            outside.write_text("v2\n"); second = content_fingerprint(cfg); self.assertEqual(first["sha256"], second["sha256"])
            link.unlink(); link.symlink_to(repo / "src" / "app.py"); third = content_fingerprint(cfg); self.assertNotEqual(first["sha256"], third["sha256"])
            link.unlink(); before = content_fingerprint(cfg)["sha256"]; app = repo / "src" / "app.py"; git(repo,"update-index","--chmod=+x","src/app.py") if os.name == "nt" else app.chmod(app.stat().st_mode | stat.S_IXUSR); after = content_fingerprint(cfg)["sha256"]; self.assertNotEqual(before, after)
        finally:
            outside_td.cleanup(); td.cleanup()

    @unittest.skipUnless(SYMLINKS_AVAILABLE, "OS account cannot create symlinks; covered by Linux CI")
    def test_trusted_policy_symlink_is_rejected(self):
        td, repo = self.make_repo()
        try:
            target = repo / "policy-real.md"; target.write_text("real\n")
            agents = repo / "AGENTS.md"; agents.unlink(); agents.symlink_to(target)
            with self.assertRaises(ConfigError): discover(repo)
        finally: td.cleanup()

    @unittest.skipUnless(SYMLINKS_AVAILABLE, "OS account cannot create symlinks; covered by Linux CI")
    def test_authority_symlink_escape_is_denied(self):
        td, repo = self.make_repo(); outside_td = tempfile.TemporaryDirectory()
        try:
            (repo / "escape").symlink_to(Path(outside_td.name), target_is_directory=True)
            decision = authorize(repo, discover(repo).authority, scope="code", operation="write", target="escape/secret.txt")
            self.assertFalse(decision.allowed); self.assertIn("symlink", decision.reason)
        finally: outside_td.cleanup(); td.cleanup()

    @unittest.skipUnless(SYMLINKS_AVAILABLE, "OS account cannot create symlinks; covered by Linux CI")
    def test_evidence_symlink_and_external_escape_are_rejected(self):
        td, repo = self.make_repo(); outside_td = tempfile.TemporaryDirectory()
        try:
            cfg = discover(repo); sid = self.start(repo)
            target = repo / ".harness" / "generated" / "real.txt"; target.parent.mkdir(parents=True, exist_ok=True); target.write_text("PASS\n")
            link = repo / ".harness" / "generated" / "link.txt"; link.symlink_to(target)
            rc, _ = invoke(repo, "evidence", "add", "--session-id", sid, "--name", "link", "--status", "PASS", "--path", link.relative_to(repo).as_posix()); self.assertEqual(rc, 2)
            outside = Path(outside_td.name) / "outside.txt"; outside.write_text("PASS\n")
            with self.assertRaises(ValueError): prepare_records(cfg, tests=[{"name":"outside","status":"PASS","evidence":str(outside)}], evidence_paths=[str(outside)])
        finally: outside_td.cleanup(); td.cleanup()

    def test_sealed_durable_memory_change_invalidates_receipt(self):
        td, repo = self.make_repo()
        try:
            docs = repo / "docs"; docs.mkdir(); mem = docs / "PROJECT_MEMORY.md"; mem.write_text("# memory v1\n")
            truth = repo / ".harness" / "truth.toml"; truth.write_text(truth.read_text() + '\n[[rules]]\npattern = "docs/PROJECT_MEMORY.md"\nkind = "durable_memory"\n')
            proj = repo / ".harness" / "project.toml"; proj.write_text(proj.read_text().replace('[knowledge]\nentrypoints = ["AGENTS.md"]', '[knowledge]\nentrypoints = ["AGENTS.md", "docs/PROJECT_MEMORY.md"]'))
            git(repo, "add", "."); git(repo, "commit", "-qm", "add memory")
            sid = self.start(repo); self.complete_workflow(repo, sid); self.assertEqual(invoke(repo, "finish", "--session-id", sid, "--summary-text", "sealed memory")[0], 0)
            mem.write_text("# memory v2\n")
            rc, value = invoke(repo, "verify", "--ci"); self.assertEqual(rc, 2); self.assertTrue(any("durable_memory_changed" in x or "no_complete_closeout" in x for x in value["failures"]))
        finally: td.cleanup()

    def test_materialbrain_code_memory_atomicity_detects_separate_commits(self):
        td = tempfile.TemporaryDirectory(); repo = Path(td.name)
        try:
            subprocess.check_call(["git", "init", "-q", str(repo)]); git(repo,"config","user.email","m@b"); git(repo,"config","user.name","mb")
            for rel in ["AGENTS.md","backend/AGENTS.md","frontend/AGENTS.md","docs/PROJECT_MEMORY.md","docs/DOCUMENTATION_MAP.md","backend/app.py"]:
                p=repo/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text("v1\n")
            write_profile(repo,"materialbrain"); git(repo,"add","."); git(repo,"commit","-qm","initial")
            (repo/"backend/app.py").write_text("v2\n"); git(repo,"add","backend/app.py"); git(repo,"commit","-qm","code only")
            errs=memory_commit_errors(discover(repo)); self.assertTrue(any("code_memory_commit_mismatch" in x for x in errs))
        finally: td.cleanup()

    def test_qualification_rehash_and_append_only_history(self):
        td, repo = self.make_repo()
        try:
            cfg=discover(repo); ev1=repo/".harness/generated/q1.txt"; ev1.parent.mkdir(parents=True,exist_ok=True); ev1.write_text("first\n")
            n1=qualification_record(cfg,commitish="HEAD",status="FAIL",evidence=ev1,summary="bad",kind="ci")
            ev2=repo/".harness/generated/q2.txt"; ev2.write_text("second\n"); n2=qualification_record(cfg,commitish="HEAD",status="PASS",evidence=ev2,summary="good",kind="ci")
            self.assertEqual(len(n2["records"]),2); self.assertEqual(n2["records"][1]["supersedes"],n2["records"][0]["record_id"])
            self.assertEqual(qualification_verify(cfg,commitish="HEAD",profile="candidate")["status"],"PASS")
            ev2.write_text("tampered\n"); result=qualification_verify(cfg,commitish="HEAD",profile="candidate"); self.assertEqual(result["integrity_status"],"FAIL"); self.assertEqual(result["status"],"FAIL")
        finally: td.cleanup()

    def test_dual_run_false_pass_false_block_unresolved_and_tamper_block_gate(self):
        td, repo = self.make_repo()
        try:
            cfg=discover(repo)
            dual_record(cfg,task_id="a",task_class="backend",legacy_status="FAIL",harness_status="PASS",expected_status="FAIL",adjudication="LEGACY_CORRECT")
            s=dual_summary(cfg); self.assertEqual(s["cutover_gate"],"BLOCKED"); self.assertEqual(s["harness_false_pass"],1)
            path=ledger_path(cfg); payload=json.loads(path.read_text()); payload["records"][0]["expected_status"]="PASS"; path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError): read_ledger(cfg)
        finally: td.cleanup()

    def test_runner_denies_force_push_external_cwd_and_redacts_bounded_output(self):
        td, repo = self.make_repo()
        outside_td = tempfile.TemporaryDirectory()
        try:
            evcfg=repo/".harness/evidence.toml"; text=evcfg.read_text(); text=text.replace('runner_max_output_bytes = 1048576','runner_max_output_bytes = 1024').replace('runner_redact_patterns = []','runner_redact_patterns = ["SECRET=[^ ]+"]'); evcfg.write_text(text); git(repo,"add",".harness/evidence.toml"); git(repo,"commit","-qm","runner policy")
            sid=self.start(repo,scope="release")
            rc,val=invoke(repo,"run","--session-id",sid,"--name","deny","--","git","push","--force","origin","HEAD"); self.assertEqual(rc,2); self.assertIn("runner_command_denied",val["error"])
            rc,val=invoke(repo,"run","--session-id",sid,"--name","cwd","--cwd",outside_td.name,"--","python","-c","print('x')"); self.assertEqual(rc,2); self.assertIn("runner_cwd_outside_repository",val["error"])
            rc,val=invoke(repo,"run","--session-id",sid,"--name","output","--","python","-c","print('SECRET=abc ' + 'x'*3000)"); self.assertEqual(rc,0,val)
            log=repo/val["runner"]["log_path"]; content=log.read_text(); self.assertNotIn("SECRET=abc",content);  self.assertIn("TRUNCATED",content); self.assertTrue(val["runner"]["output_control"]["stdout_truncated"])
        finally: outside_td.cleanup(); td.cleanup()

    def test_fresh_ci_requires_explicit_portable_bundle_verification(self):
        td, repo = self.make_repo()
        clone_td = tempfile.TemporaryDirectory()
        try:
            sid=self.start(repo); self.complete_workflow(repo,sid); self.assertEqual(invoke(repo,"finish","--session-id",sid,"--summary-text","sealed")[0],0)
            # Receipts are ignored by default; explicitly add one as a CI-carried artifact for this contract test.
            receipt=next((repo/".harness/receipts").glob("*.json")); evidence=repo/".harness/generated/manual/unit.txt"
            git(repo,"add","-f",str(receipt.relative_to(repo)),str(evidence.relative_to(repo))); git(repo,"commit","-qm","carry sealed receipt and evidence")
            clone=Path(clone_td.name)/"clone"; subprocess.check_call(["git","clone","-q",str(repo),str(clone)])
            rc,value=invoke(clone,"verify","--ci")
            # Content-equivalent generic mode allows the receipt commit itself only if material truth is unchanged.
            self.assertEqual(rc,2,value)
        finally: clone_td.cleanup(); td.cleanup()

    def test_live_state_db_event_history_deletion_is_not_mistaken_for_fresh_ci(self):
        td, repo = self.make_repo()
        try:
            sid=self.start(repo); self.complete_workflow(repo,sid); self.assertEqual(invoke(repo,"finish","--session-id",sid,"--summary-text","sealed")[0],0)
            with StateStore(repo) as store:
                self.assertIsNotNone(store.receipt_head()); self.assertIsNotNone(store.event_chain_head())
                store.conn.execute("DELETE FROM events")
            rc,value=invoke(repo,"verify","--ci"); self.assertEqual(rc,2); self.assertTrue(any("receipt_event_chain_head_missing" in x for x in value["failures"]))
        finally: td.cleanup()

    @unittest.skipUnless(SYMLINKS_AVAILABLE, "OS account cannot create symlinks; covered by Linux CI")
    def test_durable_memory_symlink_escape_is_rejected(self):
        td,repo=self.make_repo(); outside_td=tempfile.TemporaryDirectory()
        try:
            outside=Path(outside_td.name)/"memory.md"; outside.write_text("outside\n")
            docs=repo/"docs"; docs.mkdir(); mem=docs/"PROJECT_MEMORY.md"; mem.symlink_to(outside)
            truth=repo/".harness/truth.toml"; truth.write_text(truth.read_text()+'\n[[rules]]\npattern="docs/PROJECT_MEMORY.md"\nkind="durable_memory"\n')
            with self.assertRaises(ValueError): source_identity(discover(repo))
        finally: outside_td.cleanup(); td.cleanup()

    def test_receipt_and_runner_directories_cannot_escape_repository(self):
        td,repo=self.make_repo()
        try:
            p=repo/".harness/evidence.toml"; p.write_text(p.read_text().replace('receipt_dir = ".harness/receipts"','receipt_dir = "../outside"'))
            with self.assertRaises(ConfigError): discover(repo)
        finally: td.cleanup()

    def test_runner_blocks_validation_command_that_mutates_trusted_source(self):
        td,repo=self.make_repo()
        try:
            sid=self.start(repo)
            rc,value=invoke(repo,"run","--session-id",sid,"--name","mutator","--","python","-c","from pathlib import Path; Path('src/app.py').write_text('VALUE = 99\\n')")
            self.assertEqual(rc,2,value); self.assertEqual(value["status"],"BLOCKED"); self.assertEqual(value["runner"]["reason"],"runner_changed_trusted_identity")
        finally: td.cleanup()


if __name__ == "__main__":
    unittest.main()
