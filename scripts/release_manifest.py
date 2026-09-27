#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

EXCLUDE_PARTS={'.git','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','.venv','dist','build','.work','reference','Source_code'}
EXCLUDE_SUFFIXES={'.pyc','.pyo'}

def digest(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
 return h.hexdigest()

def main()->int:
 ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--version',required=True); ap.add_argument('--output',default='RELEASE_MANIFEST.json'); ns=ap.parse_args()
 root=Path(ns.root).resolve(); out=(root/ns.output).resolve(); rows=[]
 for p in sorted(root.rglob('*')):
  if not p.is_file() or p==out: continue
  rel=p.relative_to(root)
  if any(part in EXCLUDE_PARTS or part.endswith('.egg-info') for part in rel.parts) or p.suffix in EXCLUDE_SUFFIXES: continue
  if p.is_symlink() or not p.resolve().is_relative_to(root): raise ValueError('release_symlink_or_escape:'+str(rel))
  rows.append({'path':rel.as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)})
 payload={'schema':'unified-project-harness-release-manifest-v1','version':ns.version,'generated_utc':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'files':rows}
 out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8'); print(json.dumps({'status':'PASS','files':len(rows),'output':str(out)},indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
