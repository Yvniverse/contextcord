from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

FORBIDDEN = [
    r"D:\\\\Project", r"/mnt/data", r"\.work/", r"artifacts/releases",
    r"TYPESAFE_API_KEY\s*=", r"github_pat_", r"ghp_[A-Za-z0-9]",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ns = ap.parse_args()
    root = ns.root.resolve()
    errors = []
    required = [root / "index.html", root / "docs/index.html", root / "site_content_manifest.json"]
    for p in required:
        if not p.is_file():
            errors.append(f"missing:{p.relative_to(root) if p.exists() else p.name}")
    maps = sorted((root / "architecture/maps").glob("*.html")) if (root / "architecture/maps").is_dir() else []
    if len(maps) != 12:
        errors.append(f"map_count:{len(maps)}")
    for p in maps:
        if "<svg" not in p.read_text(encoding="utf-8", errors="ignore"):
            errors.append(f"map_no_svg:{p.name}")
    if (root / "index.html").is_file():
        text = (root / "index.html").read_text(encoding="utf-8")
        if "const MAP_ROOT='./architecture/maps'" not in text:
            errors.append("deploy_map_root_not_rewritten")
        node = shutil.which("node")
        if node:
            scripts = []
            for m in re.finditer(r"<script(?P<a>[^>]*)>(?P<b>.*?)</script>", text, re.I | re.S):
                if "src=" in m.group("a").lower() or "application/json" in m.group("a").lower():
                    continue
                if m.group("b").strip():
                    scripts.append(m.group("b"))
            with tempfile.TemporaryDirectory() as td:
                for i, body in enumerate(scripts):
                    p = Path(td) / f"s{i}.js"
                    p.write_text(body, encoding="utf-8")
                    r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
                    if r.returncode:
                        errors.append(f"inline_js_syntax:{i}:{r.stderr.strip()}")
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        try:
            body = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pat in FORBIDDEN:
            if re.search(pat, body, re.I):
                errors.append(f"private_pattern:{p.relative_to(root)}:{pat}")
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "files": sum(1 for p in root.rglob('*') if p.is_file()), "maps": len(maps), "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
