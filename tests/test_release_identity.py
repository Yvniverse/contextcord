from __future__ import annotations
import subprocess,tempfile,unittest
from pathlib import Path
from project_harness.config import discover
from project_harness.profiles import write_profile
from project_harness.release_identity import collect
from project_harness.contracts import validate

def git(repo,*args): return subprocess.check_output(["git","-C",str(repo),*args],text=True).strip()
class ReleaseIdentityTests(unittest.TestCase):
    def test_release_identity_collects_source_policy_dependency_and_runtime_layers(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); subprocess.check_call(["git","init","-q",str(repo)]); git(repo,"config","user.email","r@i"); git(repo,"config","user.name","ri")
            (repo/"AGENTS.md").write_text("rules\n"); (repo/"pyproject.toml").write_text('[project]\nname="x"\nversion="1"\n'); write_profile(repo,"generic"); git(repo,"add","."); git(repo,"commit","-qm","init")
            value=collect(discover(repo),scope="code"); self.assertEqual(value["status"],"PASS"); self.assertEqual(value["schema"],"project-harness-release-identity-v1"); self.assertEqual(value["groups"]["dependencies"]["file_count"],1); self.assertEqual(value["runtime"]["status"],"PASS"); validate("release-identity",value)
    def test_required_release_identity_pattern_blocks_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); subprocess.check_call(["git","init","-q",str(repo)]); git(repo,"config","user.email","r@i"); git(repo,"config","user.name","ri"); (repo/"AGENTS.md").write_text("rules\n"); write_profile(repo,"generic")
            p=repo/".harness/project.toml"; p.write_text(p.read_text()+'\n[release_identity]\nrequired_patterns=["missing.lock"]\n'); git(repo,"add","."); git(repo,"commit","-qm","init")
            value=collect(discover(repo)); self.assertEqual(value["status"],"BLOCKED"); self.assertIn("required_release_identity_pattern_missing:missing.lock",value["blockers"])
if __name__=="__main__": unittest.main()
