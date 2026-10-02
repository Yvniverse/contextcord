from __future__ import annotations
import io,json,subprocess,tempfile,unittest
from contextlib import redirect_stdout
from pathlib import Path
from contextcord.cli import main
from contextcord.profiles import write_profile
from contextcord.store import StateStore

def git(repo,*args): return subprocess.check_output(["git","-C",str(repo),*args],text=True).strip()
def call(repo,*args):
 b=io.StringIO();
 with redirect_stdout(b): rc=main(["--repo",str(repo),*args])
 return rc,json.loads(b.getvalue()) if b.getvalue().strip() else {}
class PortableBundleTests(unittest.TestCase):
 def make(self):
  td=tempfile.TemporaryDirectory(); repo=Path(td.name); subprocess.check_call(["git","init","-q",str(repo)]); git(repo,"config","user.email","p@b"); git(repo,"config","user.name","pb"); (repo/"AGENTS.md").write_text("rules\n"); (repo/"src").mkdir(); (repo/"src/x.py").write_text("x=1\n"); write_profile(repo,"generic"); git(repo,"add","."); git(repo,"commit","-qm","init"); return td,repo
 def close(self,repo):
  self.assertEqual(call(repo,"start","--task-id","t","--scope","code","--json")[0],0)
  with StateStore(repo) as st: sid=st.open_sessions("t")[0]["session_id"]
  for ph in ["authority","implementation"]: self.assertEqual(call(repo,"state","advance","--task-id","t","--phase",ph,"--next-action","next","--session-id",sid)[0],0)
  # Runner output lives under generated/ and is portable by construction.
  self.assertEqual(call(repo,"run","--session-id",sid,"--name","unit","--","python","-c","print('ok')")[0],0)
  self.assertEqual(call(repo,"state","advance","--task-id","t","--phase","tests","--next-action","finish","--session-id",sid)[0],0)
  self.assertEqual(call(repo,"finish","--session-id",sid,"--summary-text","portable")[0],0)
 def test_bundle_round_trip_enables_fresh_ci_without_sqlite_history(self):
  td,repo=self.make(); clone_td=tempfile.TemporaryDirectory(); bundle=Path(clone_td.name)/"closeout.zip"
  try:
   self.close(repo); self.assertEqual(call(repo,"bundle","export","--path",str(bundle))[0],0)
   clone=Path(clone_td.name)/"clone"; subprocess.check_call(["git","clone","-q",str(repo),str(clone)])
   rc,verified=call(clone,"bundle","verify","--path",str(bundle)); self.assertEqual(rc,0,verified)
   rc,imported=call(clone,"bundle","import","--path",str(bundle)); self.assertEqual(rc,0,imported)
   rc,result=call(clone,"verify","--ci"); self.assertEqual(rc,2,result)
  finally: clone_td.cleanup(); td.cleanup()
 def test_bundle_import_rejects_source_classified_evidence_path(self):
  td,repo=self.make(); out=tempfile.TemporaryDirectory()
  try:
   # Manual PASS evidence in a source-classified path is valid locally but deliberately non-portable.
   self.assertEqual(call(repo,"start","--task-id","t","--scope","code","--json")[0],0)
   with StateStore(repo) as st: sid=st.open_sessions("t")[0]["session_id"]
   for ph in ["authority","implementation"]: self.assertEqual(call(repo,"state","advance","--task-id","t","--phase",ph,"--next-action","next","--session-id",sid)[0],0)
   ev=repo/"manual-evidence.txt"; ev.write_text("PASS\n"); self.assertEqual(call(repo,"evidence","add","--session-id",sid,"--name","unit","--status","PASS","--path","manual-evidence.txt")[0],0)
   self.assertEqual(call(repo,"state","advance","--task-id","t","--phase","tests","--next-action","finish","--session-id",sid)[0],0); self.assertEqual(call(repo,"finish","--session-id",sid,"--summary-text","x")[0],0)
   rc,value=call(repo,"bundle","export","--path",str(Path(out.name)/"bad.zip")); self.assertEqual(rc,2); self.assertIn("portable_evidence_path_not_non_source",value["error"])
  finally: out.cleanup(); td.cleanup()
if __name__=="__main__": unittest.main()
