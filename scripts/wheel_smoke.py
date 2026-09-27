"""Build-independent verification of an installed wheel in a fresh virtualenv."""
import argparse
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def run(wheelhouse=None):
    wheel_root = Path(wheelhouse).resolve() if wheelhouse else ROOT / 'dist'
    wheels=sorted(wheel_root.glob('contextcord-*.whl'),key=lambda p:p.stat().st_mtime)
    if not wheels: raise RuntimeError('Build the wheel first')
    workspace=ROOT/'.work'/'wheel-smoke'; workspace.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(dir=workspace))
    # Reuse only the host's already-installed runtime dependencies (not the
    # project itself); the package under test is still installed into this
    # fresh environment and its import path is asserted below.
    environment=temp/'venv'; venv.EnvBuilder(with_pip=True, system_site_packages=True).create(environment)
    python=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME'}}
    env['PYTHONUTF8']='1'
    # This is a package-isolation smoke, not a dependency-resolution gate.
    # Keep it offline and let the dedicated test environment own dependency
    # coverage separately.
    install=[str(python),'-m','pip','install','--no-deps']
    if wheelhouse: install+=['--no-index','--find-links',str(Path(wheelhouse).resolve())]
    subprocess.run([*install,str(wheels[-1])],cwd=temp,env=env,check=True)
    repo=temp/'repo';repo.mkdir()

    def cmd(args,cwd=repo):
        p=subprocess.run([str(x) for x in args],cwd=cwd,env=env,text=True,encoding='utf-8',capture_output=True)
        if p.returncode: raise RuntimeError(p.stdout+'\n'+p.stderr)
        return p.stdout

    def cli(*args, cwd=repo):
        return json.loads(cmd([python,'-m','contextcord',*args],cwd))

    cmd(['git','init','-q']); (repo/'AGENTS.md').write_text('Smoke fixture rules\n')
    cli('init');cmd(['git','add','.'])
    cmd(['git','-c','user.name=Smoke','-c','user.email=smoke@invalid.local','commit','-qm','fixture'])
    session=cli('start','--task-id','smoke','--scope','code','--json')['session_id']
    for phase in ['authority','implementation']:
        cli('state','advance','--task-id','smoke','--phase',phase,'--next-action','continue')
    cli('run','--session-id',session,'--name','python-runtime','--',str(python),'-c',"import json; assert json.loads('{\"ok\":true}')[\"ok\"]")
    cli('state','advance','--task-id','smoke','--phase','tests','--next-action','finish')
    cli('finish','--session-id',session,'--summary-text','installed-wheel smoke')
    local=cli('verify','--ci'); assert local['status']=='PASS'
    bundle=temp/'bundle.zip';cli('bundle','export','--path',str(bundle))
    clone=temp/'clone';cmd(['git','clone','-q',str(repo),str(clone)])
    portable=cli('bundle','verify','--path',str(bundle),cwd=clone);assert portable['status']=='PASS'
    messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{
        'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'wheel-smoke','version':'1'}}},
        {'jsonrpc':'2.0','method':'notifications/initialized'},
        {'jsonrpc':'2.0','id':2,'method':'tools/list'},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'contextcord_verify'}}]
    p=subprocess.run([str(python),'-m','contextcord','mcp'],cwd=repo,env=env,text=True,
                     input='\n'.join(json.dumps(m) for m in messages)+'\n',capture_output=True,timeout=30)
    assert p.returncode==0,p.stderr
    responses=[json.loads(line) for line in p.stdout.splitlines()]
    assert len(responses)==3 and not responses[-1]['result']['isError'],responses
    package=cmd([python,'-c','import contextcord; print(contextcord.__file__)']).strip()
    assert str(environment) in package,package
    result={'status':'PASS','wheel':wheels[-1].name,'installed_package':package,
            'local_verify':local['status'],'portable_verify':portable['status'],'mcp_responses':len(responses)}
    output=ROOT/'artifacts/audit/wheel-smoke.json';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--wheelhouse');run(parser.parse_args().wheelhouse)
