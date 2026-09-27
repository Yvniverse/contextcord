#!/usr/bin/env python3
"""Static/runtime hard gate for ContextCord Home before Cloudflare deploy."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("html", type=Path)
    ap.add_argument("--max-bytes", type=int, default=1_500_000)
    ns = ap.parse_args()
    p = ns.html.resolve()
    text = p.read_text(encoding="utf-8")
    errors: list[str] = []

    if p.stat().st_size > ns.max_bytes:
        errors.append(f"homepage_too_large:{p.stat().st_size}>{ns.max_bytes}")
    if "const MAP_ROOT=" not in text:
        errors.append("map_root_missing")
    if "DecompressionStream" in text:
        errors.append("decompression_stream_forbidden")

    m = re.search(r"const\s+DIAGRAMS\s*=\s*\[(.*?)\];", text, re.S)
    if not m:
        errors.append("diagram_registry_missing")
    else:
        count = len(re.findall(r"\[\s*['\"](?:system|router|workflow|sequence|dataflow|lifecycle)['\"]", m.group(1)))
        if count != 6:
            errors.append(f"visible_diagram_type_count:{count}")

    node = shutil.which("node")
    scripts: list[str] = []
    for sm in re.finditer(r"<script(?P<a>[^>]*)>(?P<b>.*?)</script>", text, re.I | re.S):
        attrs = sm.group("a")
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        tm = re.search(r"\btype\s*=\s*['\"]([^'\"]+)", attrs, re.I)
        if tm and tm.group(1).lower() not in {"text/javascript", "application/javascript", "module"}:
            continue
        body = sm.group("b")
        if body.strip():
            scripts.append(body)
    if not scripts:
        errors.append("no_executable_inline_scripts")
    elif node:
        with tempfile.TemporaryDirectory(prefix="contextcord-web-") as td:
            for i, body in enumerate(scripts, 1):
                js = Path(td) / f"inline-{i}.js"
                js.write_text(body, encoding="utf-8")
                r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
                if r.returncode:
                    errors.append(f"inline_script_syntax:{i}:{r.stderr.strip()}")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "bytes": p.stat().st_size,
        "node_checked": bool(node),
        "inline_scripts": len(scripts),
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
