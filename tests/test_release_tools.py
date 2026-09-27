import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class ReleaseToolTests(unittest.TestCase):
    def fixture(self):
        temp=tempfile.TemporaryDirectory();root=Path(temp.name)
        (root/'source.txt').write_text('reviewed source')
        subprocess.run([sys.executable,str(ROOT/'scripts/release_manifest.py'),'--root',str(root),'--version','test'],check=True,capture_output=True)
        return temp,root

    def verify(self,root):
        p=subprocess.run([sys.executable,str(ROOT/'scripts/verify_release_manifest.py'),'--root',str(root)],capture_output=True,text=True)
        return p.returncode,json.loads(p.stdout)

    def test_exact_inventory_rejects_added_payload(self):
        temp,root=self.fixture()
        try:
            self.assertEqual(self.verify(root)[0],0)
            (root/'unexpected.py').write_text('added payload')
            rc,value=self.verify(root);self.assertEqual(rc,2)
            self.assertIn('unexpected:unexpected.py',value['errors'])
        finally: temp.cleanup()

    def test_manifest_traversal_is_rejected(self):
        temp,root=self.fixture()
        try:
            path=root/'RELEASE_MANIFEST.json';value=json.loads(path.read_text())
            value['files'][0]['path']='../outside'
            path.write_text(json.dumps(value))
            rc,result=self.verify(root);self.assertEqual(rc,2)
            self.assertIn('unsafe:../outside',result['errors'])
        finally: temp.cleanup()
