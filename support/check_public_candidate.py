#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path

FORBIDDEN_PATH_SNIPPETS=(
    'web/integrations/','web/research/','web/workbench/','site/',
    'support/host_registry_v2.example.json','research/host_evidence_registry.json',
    'benchmarks/context_sufficiency_test_trials.jsonl','benchmarks/live_benchmark_v3_trials.jsonl',
    'docs/RELEASE_READINESS.md',
)
CURRENT_TEXT_FILES=('README.md','README_CN.md','NOTICE','pyproject.toml','CITATION.cff')


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path.cwd())
    ap.add_argument('--staging',type=Path,required=True)
    ap.add_argument('--expect-apache',action='store_true')
    args=ap.parse_args()
    root=args.root.resolve(); stage=args.staging.resolve(); errors=[]; notes=[]
    staged=[p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()]
    for rel in staged:
        for bad in FORBIDDEN_PATH_SNIPPETS:
            if bad in rel: errors.append(f'forbidden_staged_path:{rel}')
    # Current docs should not actively link Router v2 or internal phase names.
    for rel in ('README.md','README_CN.md'):
        p=stage/rel
        if p.exists():
            txt=p.read_text(encoding='utf-8',errors='replace')
            if 'ROUTER_V2' in txt: errors.append(f'active_router_v2_link:{rel}')
            if re.search(r'\bA(?:9|10|11|12)(?:\b|[._ -])',txt): errors.append(f'phase_marker_in_readme:{rel}')
    web=stage/'web/index.html'
    if web.exists() and web.stat().st_size>1_500_000:
        errors.append(f'homepage_too_large:{web.stat().st_size}')
    if args.expect_apache:
        checks={
            'LICENSE':'Apache License',
            'pyproject.toml':'Apache-2.0',
            'CITATION.cff':'Apache-2.0',
            'README.md':'Apache-2.0',
            'README_CN.md':'Apache-2.0',
        }
        for rel,needle in checks.items():
            p=stage/rel
            if not p.exists(): errors.append(f'apache_file_missing:{rel}'); continue
            if needle not in p.read_text(encoding='utf-8',errors='replace'):
                errors.append(f'apache_marker_missing:{rel}:{needle}')
        notice=(stage/'NOTICE')
        if notice.exists():
            t=notice.read_text(encoding='utf-8',errors='replace')
            for old in ('Project Harness','Agent-Nexus','ProjectTrust'):
                if old in t: errors.append(f'internal_history_in_notice:{old}')
    print(json.dumps({'status':'PASS' if not errors else 'FAIL','staged_files':len(staged),'errors':sorted(set(errors)),'notes':notes},indent=2,ensure_ascii=False))
    return 1 if errors else 0

if __name__=='__main__': raise SystemExit(main())
