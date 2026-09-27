import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import test_portable_bundle as fixture
from project_harness.adapters import render, capabilities
from project_harness.config import discover
from project_harness.mcp import Server, serve
from project_harness.portable import _safe_archive_path, inspect_bundle
from project_harness.process import capture
from project_harness.replay import replay
from project_harness.service import HarnessService
from project_harness.store import StateStore
from project_harness.truth import content_fingerprint
from project_harness.util import sha256_json


class OpenCoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.PortableBundleTests()
        self.tmp, self.repo = self.fixture.make()

    def tearDown(self):
        self.tmp.cleanup()

    def test_state_and_event_roll_back_together(self):
        with StateStore(self.repo) as store:
            with patch.object(store, 'event', side_effect=RuntimeError('injected event failure')):
                with self.assertRaises(RuntimeError):
                    store.create_session(task_id='atomic', scope='code', head='head', fingerprint='hash')
            self.assertEqual(store.open_sessions(), [])
            self.assertTrue(store.verify_event_chain()[0])

    def test_outer_transaction_rolls_back_nested_event(self):
        with StateStore(self.repo) as store:
            with self.assertRaises(RuntimeError):
                with store.transaction():
                    store.event('TEST', {})
                    raise RuntimeError('crash')
            self.assertIsNone(store.event_chain_head())

    def test_closed_session_cannot_close_twice_and_releases_lease(self):
        with StateStore(self.repo) as store:
            sid = store.create_session(task_id='t', scope='code', head='h', fingerprint='f')
            store.acquire_lease(lease_key='src/**', session_id=sid, task_id='t')
            store.close_session(sid, fingerprint='f', end_head='h', summary={})
            self.assertEqual(store.active_leases(), [])
            with self.assertRaises(RuntimeError):
                store.close_session(sid, fingerprint='f', end_head='h', summary={})

    def test_deleted_entire_database_fails_local_verification(self):
        self.fixture.close(self.repo)
        with StateStore(self.repo) as store:
            path = store.path
        path.unlink()
        rc, value = fixture.call(self.repo, 'verify', '--ci')
        self.assertEqual(rc, 2, value)

    def test_build_drift_blocks_finish(self):
        fixture.call(self.repo, 'start', '--task-id', 't', '--scope', 'code', '--json')
        with StateStore(self.repo) as store:
            sid = store.open_sessions()[0]['session_id']
            store.conn.execute('UPDATE sessions SET start_build_sha256=?', ('0'*64,))
        rc, value = fixture.call(self.repo, 'finish', '--session-id', sid, '--mode', 'handoff', '--summary-text', 'pause')
        self.assertEqual(rc, 2)
        self.assertIn('core_build_drift_since_session_start', value['failures'])

    def test_replay_rejects_corrupt_json_without_executing(self):
        with StateStore(self.repo) as store:
            store.event('TEST', {'command': 'never execute'})
            store.conn.execute("UPDATE events SET payload_json='invalid'")
        self.assertEqual(replay(self.repo)['status'], 'FAIL')

    def test_replay_pagination_has_no_duplicate_events(self):
        with StateStore(self.repo) as store:
            for i in range(5):
                store.event('TEST', {'n': i}, task_id='t')
        first = replay(self.repo, task_id='t', limit=2)
        second = replay(self.repo, task_id='t', after=first['next_after'], limit=3)
        self.assertEqual([e['payload']['n'] for e in first['events']+second['events']], list(range(5)))

    def test_archive_paths_reject_windows_and_posix_escape(self):
        for name in ['../escape', '/escape', 'C:/escape', 'a\\..\\escape', 'a:b', 'a//b', 'a/./b', 'NUL.txt', 'a./b']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                _safe_archive_path(name)

    def test_portable_verifier_rejects_resealed_manifest_with_bad_receipt(self):
        self.fixture.close(self.repo)
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)/'bundle.zip'
            self.assertEqual(fixture.call(self.repo,'bundle','export','--path',str(bundle))[0],0)
            manifest, data = inspect_bundle(bundle)
            entry = next(e for e in manifest['files'] if e['kind']=='receipt')
            value = json.loads(data[entry['path']]); value['closeout_status']='FAIL'
            raw = json.dumps(value).encode(); data[entry['path']]=raw
            entry.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            manifest['bundle_sha256']=sha256_json(manifest,exclude_keys=('bundle_sha256',))
            with zipfile.ZipFile(bundle,'w') as z:
                z.writestr('manifest.json',json.dumps(manifest))
                for path, raw in data.items(): z.writestr(path,raw)
            rc,value=fixture.call(self.repo,'bundle','verify','--path',str(bundle))
            self.assertEqual(rc,2,value)
            self.assertIn('portable_receipt_hash_mismatch',value['errors'])

    def test_runner_capture_bounds_output_and_timeout(self):
        code,out,err,timed_out,overflow,incomplete=capture(
            [sys.executable,'-c',"print('s'*2000000)"],cwd=self.repo,timeout=5,max_bytes=4096)
        self.assertEqual(code,0); self.assertTrue(overflow[0]); self.assertLess(len(out),4096)
        code,out,err,timed_out,overflow,incomplete=capture(
            [sys.executable,'-c','import time; time.sleep(20)'],cwd=self.repo,timeout=.1,max_bytes=4096)
        self.assertTrue(timed_out)

    def test_mcp_lifecycle_and_default_mutation_boundary(self):
        server=Server(HarnessService(self.repo))
        self.assertIn('error',server.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'}))
        init=server.handle({'jsonrpc':'2.0','id':2,'method':'initialize','params':{
            'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
        self.assertEqual(init['result']['protocolVersion'],'2025-11-25')
        self.assertIsNone(server.handle({'jsonrpc':'2.0','method':'notifications/initialized'}))
        listed=server.handle({'jsonrpc':'2.0','id':3,'method':'tools/list'})
        names={t['name'] for t in listed['result']['tools']}
        self.assertNotIn('harness_start',names); self.assertIn('harness_authorize',names)
        value=server.handle({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'harness_identity'}})
        self.assertFalse(value['result']['isError'])
        bad=server.handle({'jsonrpc':'2.0','id':5,'method':'tools/call','params':{
            'name':'harness_identity','arguments':{'repo':'../other'}}})
        self.assertTrue(bad['result']['isError'])

    def test_mcp_framing_recovers_parse_error(self):
        output=io.StringIO()
        serve(self.repo,input_stream=io.BytesIO(b'not-json\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n'),output_stream=output)
        rows=[json.loads(s) for s in output.getvalue().splitlines()]
        self.assertEqual(rows[0]['error']['code'],-32700); self.assertEqual(rows[1]['result'],{})

    def test_mcp_mutations_use_core_and_cannot_complete_without_evidence(self):
        service=HarnessService(self.repo,allow_mutations=True)
        started=service.call('harness_start',{'task_id':'mcp','scope':'code'})
        result=service.call('harness_finish',{'session_id':started['session_id'],'mode':'complete','summary':'done'})
        self.assertEqual(result['status'],'BLOCKED')

    def test_adapters_are_staged_and_do_not_overwrite(self):
        for host in ('claude','cursor'):
            destination=self.repo/host
            files=render(host,destination)
            self.assertTrue(files)
            with self.assertRaises(ValueError): render(host,destination)
        self.assertFalse(capabilities('cursor')['pretool_policy'])

    @unittest.skipUnless(os.name=='nt','Windows uses Git executable modes')
    def test_windows_git_index_executable_bit_changes_identity(self):
        cfg=discover(self.repo); before=content_fingerprint(cfg)['sha256']
        fixture.git(self.repo,'update-index','--chmod=+x','src/x.py')
        self.assertNotEqual(before,content_fingerprint(cfg)['sha256'])

    def test_changed_paths_preserves_unicode_and_spaces(self):
        from project_harness.gitops import changed_paths
        name='测试 space.txt'; (self.repo/name).write_text('x',encoding='utf-8')
        self.assertIn(name,changed_paths(self.repo))

    def test_phase_rechecks_evidence_after_source_changes(self):
        started=fixture.call(self.repo,'start','--task-id','t','--scope','code','--json')[1]
        sid=started['session_id']
        for phase in ('authority','implementation'):
            self.assertEqual(fixture.call(self.repo,'state','advance','--task-id','t','--phase',phase,'--next-action','next')[0],0)
        self.assertEqual(fixture.call(self.repo,'run','--session-id',sid,'--name','tests','--',sys.executable,'-c',"print('ok')")[0],0)
        (self.repo/'src/x.py').write_text('changed=1\n')
        rc,value=fixture.call(self.repo,'state','advance','--task-id','t','--phase','tests','--next-action','finish')
        self.assertEqual(rc,2,value)
        self.assertTrue(any('source_truth_mismatch' in s for s in value['failures']))

    def test_parallel_qualification_appends_do_not_lose_records(self):
        from concurrent.futures import ThreadPoolExecutor
        from project_harness.qualification import record, read_note, verify
        cfg=discover(self.repo)
        evidence=self.repo/'.harness/generated/ci.txt';evidence.parent.mkdir(parents=True,exist_ok=True);evidence.write_text('ci pass')
        def append(index):
            return record(cfg,commitish='HEAD',status='PASS',evidence=evidence,summary=str(index),kind='ci')
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(append,range(6)))
        note=read_note(cfg,fixture.git(self.repo,'rev-parse','HEAD'))
        self.assertEqual(len(note['records']),6)
        self.assertEqual(verify(cfg,commitish='HEAD')['status'],'PASS')

    def test_profile_init_preflights_all_files(self):
        from project_harness.profiles import write_profile
        (self.repo/'.harness/project.toml').unlink()
        with self.assertRaises(FileExistsError): write_profile(self.repo,'generic')
        self.assertFalse((self.repo/'.harness/project.toml').exists())


if __name__=='__main__': unittest.main()
