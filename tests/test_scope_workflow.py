from __future__ import annotations
import io, json, os, subprocess, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from project_harness.cli import main
from project_harness.profiles import write_profile
from project_harness.store import StateStore
from project_harness.workflow import required_phases_for_scope, validate_workflow
from project_harness.config import discover
from project_harness.qualification import record as qualification_record

def git(repo,*args): return subprocess.check_output(["git","-C",str(repo),*args],text=True).strip()
def call(repo,*args):
    b=io.StringIO()
    with redirect_stdout(b): rc=main(["--repo",str(repo),*args])
    return rc, json.loads(b.getvalue()) if b.getvalue().strip() else {}

class ScopeWorkflowTests(unittest.TestCase):
    def test_generic_code_scope_can_close_after_tests_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); subprocess.check_call(["git","init","-q",str(repo)]); git(repo,"config","user.email","x@y"); git(repo,"config","user.name","x")
            (repo/"AGENTS.md").write_text("rules\n"); (repo/"src").mkdir(); (repo/"src/x.py").write_text("x=1\n"); write_profile(repo,"generic"); git(repo,"add","."); git(repo,"commit","-qm","init")
            rc,_=call(repo,"start","--task-id","code","--scope","code","--json"); self.assertEqual(rc,0)
            with StateStore(repo) as store: sid=store.open_sessions("code")[0]["session_id"]
            for phase in ["authority","implementation"]: self.assertEqual(call(repo,"state","advance","--task-id","code","--phase",phase,"--next-action","next","--session-id",sid)[0],0)
            ev=repo/".harness/generated/unit.txt"; ev.parent.mkdir(parents=True,exist_ok=True); ev.write_text("PASS\n")
            self.assertEqual(call(repo,"evidence","add","--session-id",sid,"--name","unit","--status","PASS","--path",ev.relative_to(repo).as_posix())[0],0)
            rc, state = call(repo,"state","advance","--task-id","code","--phase","tests","--next-action","finish","--session-id",sid); self.assertEqual(rc,0,state)
            self.assertEqual(state["status"], "READY_TO_FINISH"); self.assertIsNone(state["current_phase"])
            rc, blocked = call(repo,"state","advance","--task-id","code","--phase","qualification","--next-action","should-not-run","--session-id",sid); self.assertEqual(rc,2,blocked)
            self.assertTrue(any("phase_not_required_for_scope" in x for x in blocked.get("failures", [])))
            rc,value=call(repo,"finish","--session-id",sid,"--summary-text","code complete"); self.assertEqual(rc,0,value); self.assertEqual(value["closeout_status"],"PASS")
    def test_generic_release_requires_candidate_then_release_qualification(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); subprocess.check_call(["git","init","-q",str(repo)]); git(repo,"config","user.email","x@y"); git(repo,"config","user.name","x")
            (repo/"AGENTS.md").write_text("rules\n"); (repo/"src").mkdir(); (repo/"src/x.py").write_text("x=1\n"); write_profile(repo,"generic"); git(repo,"add","."); git(repo,"commit","-qm","init")
            rc,_=call(repo,"start","--task-id","rel","--scope","release","--json"); self.assertEqual(rc,0)
            with StateStore(repo) as store: sid=store.open_sessions("rel")[0]["session_id"]
            for phase in ["authority","implementation"]:
                self.assertEqual(call(repo,"state","advance","--task-id","rel","--phase",phase,"--next-action","next","--session-id",sid)[0],0)
            unit=repo/".harness/generated/unit.txt"; unit.parent.mkdir(parents=True,exist_ok=True); unit.write_text("PASS\n")
            self.assertEqual(call(repo,"evidence","add","--session-id",sid,"--name","unit","--status","PASS","--path",unit.relative_to(repo).as_posix())[0],0)
            self.assertEqual(call(repo,"state","advance","--task-id","rel","--phase","tests","--next-action","qualification","--session-id",sid)[0],0)
            rc, missing_candidate = call(repo,"state","advance","--task-id","rel","--phase","qualification","--next-action","delivery","--session-id",sid)
            self.assertEqual(rc,2,missing_candidate); self.assertTrue(any("phase_qualification_not_pass:qualification:candidate" in x for x in missing_candidate.get("failures", [])))
            cfg=discover(repo)
            ci=repo/".harness/generated/ci.txt"; ci.write_text("ci pass\n")
            qualification_record(cfg, commitish="HEAD", status="PASS", evidence=ci, summary="ci", kind="ci")
            self.assertEqual(call(repo,"state","advance","--task-id","rel","--phase","qualification","--next-action","delivery","--session-id",sid)[0],0)
            rc, missing_release = call(repo,"state","advance","--task-id","rel","--phase","delivery","--next-action","finish","--session-id",sid)
            self.assertEqual(rc,2,missing_release); self.assertTrue(any("phase_qualification_not_pass:delivery:release" in x for x in missing_release.get("failures", [])))
            review=repo/".harness/generated/review.txt"; review.write_text("review pass\n")
            qualification_record(cfg, commitish="HEAD", status="PASS", evidence=review, summary="review", kind="review")
            rc, state = call(repo,"state","advance","--task-id","rel","--phase","delivery","--next-action","finish","--session-id",sid)
            self.assertEqual(rc,0,state); self.assertEqual(state["status"],"READY_TO_FINISH"); self.assertIsNone(state["current_phase"])

    def test_materialbrain_scope_boundaries_are_dependency_closed(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"MATERIALBRAIN_BASE_URL":"http://127.0.0.1:9"}):
            repo=Path(td); subprocess.check_call(["git","init","-q",str(repo)])
            for rel in ["AGENTS.md","backend/AGENTS.md","frontend/AGENTS.md","docs/PROJECT_MEMORY.md","docs/DOCUMENTATION_MAP.md"]:
                p=repo/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text("x\n")
            write_profile(repo,"materialbrain"); cfg=discover(repo); self.assertFalse(validate_workflow(cfg.workflow))
            self.assertEqual(required_phases_for_scope(cfg.workflow,"code")[-1],"integration_tests")
            self.assertEqual(required_phases_for_scope(cfg.workflow,"uat")[-1],"browser_uat")
            self.assertEqual(required_phases_for_scope(cfg.workflow,"release")[-1],"deployment")
    def test_carbon_scope_boundaries_are_progressive(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,{"CARBON_DATA_ROOT":"D:/data","CARBON_STAGING_ROOT":"D:/data/staging"}):
            repo=Path(td); subprocess.check_call(["git","init","-q",str(repo)]); (repo/"AGENTS.md").write_text("x"); (repo/"PROJECT_RULES.md").write_text("x"); (repo/"docs/agent").mkdir(parents=True)
            for n in ["PROJECT_MEMORY.md","ENVIRONMENT_AUTHORITY.md","KNOWN_ISSUES.md"]: (repo/"docs/agent"/n).write_text("x")
            write_profile(repo,"carbon-bot"); cfg=discover(repo); self.assertFalse(validate_workflow(cfg.workflow))
            self.assertEqual(len(required_phases_for_scope(cfg.workflow,"code-only")),2)
            self.assertEqual(len(required_phases_for_scope(cfg.workflow,"data-readonly")),3)
            self.assertEqual(len(required_phases_for_scope(cfg.workflow,"staging")),4)
            self.assertEqual(len(required_phases_for_scope(cfg.workflow,"release")),10)
if __name__=="__main__": unittest.main()
