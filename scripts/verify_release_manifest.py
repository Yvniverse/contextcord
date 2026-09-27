#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path, PurePosixPath, PureWindowsPath
from release_manifest import digest, EXCLUDE_PARTS, EXCLUDE_SUFFIXES


def verify(root, manifest):
 root=Path(root).resolve(); manifest=Path(manifest).resolve()
 m=json.loads(manifest.read_text(encoding='utf-8')); errors=[]; expected=set()
 if not isinstance(m.get('files'),list) or not m['files']:
  raise ValueError('release_manifest_empty_or_invalid')
 for row in m['files']:
  name=row['path']; rel=PurePosixPath(name)
  if rel.is_absolute() or '..' in rel.parts or PureWindowsPath(name).drive or ':' in name or chr(92) in name or rel.as_posix()!=name:
   errors.append('unsafe:'+name); continue
  if name in expected: errors.append('duplicate:'+name)
  expected.add(name); f=root/name
  if not f.resolve().is_relative_to(root) or f.is_symlink():
   errors.append('symlink_or_escape:'+name); continue
  if not f.is_file(): errors.append('missing:'+name); continue
  if f.stat().st_size!=row['bytes']: errors.append('size:'+name)
  if digest(f)!=row['sha256']: errors.append('hash:'+name)
 actual=set()
 for f in root.rglob('*'):
  if not f.is_file() or f==manifest: continue
  rel=f.relative_to(root)
  if any(p in EXCLUDE_PARTS or p.endswith('.egg-info') for p in rel.parts) or f.suffix in EXCLUDE_SUFFIXES: continue
  actual.add(rel.as_posix())
 errors.extend('unexpected:'+name for name in sorted(actual-expected))
 return {'status':'FAIL' if errors else 'PASS','version':m.get('version'),'checked_files':len(expected),'errors':errors}


def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',default='.');ap.add_argument('--manifest',default='RELEASE_MANIFEST.json');ns=ap.parse_args()
 try: result=verify(Path(ns.root),Path(ns.root)/ns.manifest)
 except (ValueError,KeyError,TypeError,OSError) as exc: result={'status':'FAIL','errors':[str(exc)]}
 print(json.dumps(result,indent=2,sort_keys=True)); return 0 if result['status']=='PASS' else 2


if __name__=='__main__': raise SystemExit(main())
