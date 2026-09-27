#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT_WEB_FILES = ("index.html", "public.css", "public.js", "i18n.js")
PRIVATE_PATTERNS = (
    r"D:\\\\Project",
    r"/mnt/data",
    r"\.work/",
    r"artifacts/releases",
    r"TYPESAFE_API_KEY\s*=",
    r"github_pat_",
    r"ghp_[A-Za-z0-9]",
)


def copy_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def manifest(dest: Path) -> dict[str, object]:
    rows = []
    for p in sorted(x for x in dest.rglob("*") if x.is_file() and x.name != "site_content_manifest.json"):
        data = p.read_bytes()
        rows.append({
            "path": p.relative_to(dest).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return {
        "schema": "contextcord-site-bundle-v1",
        "source": "private-canonical-explicit-site-allowlist",
        "files": rows,
    }


def build(root: Path, destination: Path) -> Path:
    root = root.resolve()
    destination = destination.resolve()
    if destination == root:
        raise ValueError("destination_must_not_be_repo_root")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    web = root / "web"
    maps = root / "docs" / "architecture" / "maps"
    if not web.is_dir() or not maps.is_dir():
        raise FileNotFoundError("missing_web_or_architecture_maps")

    for name in ROOT_WEB_FILES:
        copy_file(web / name, destination / name)
    copy_file(web / "docs" / "index.html", destination / "docs" / "index.html")

    map_files = sorted(maps.glob("*.html"))
    if len(map_files) != 12:
        raise RuntimeError(f"expected_12_archify_maps_got_{len(map_files)}")
    for p in map_files:
        copy_file(p, destination / "architecture" / "maps" / p.name)

    # Repo-relative map path -> deploy-bundle-relative map path.
    home = destination / "index.html"
    text = home.read_text(encoding="utf-8")
    old = "const MAP_ROOT='../docs/architecture/maps'"
    new = "const MAP_ROOT='./architecture/maps'"
    if old not in text and new not in text:
        raise RuntimeError("homepage_map_root_contract_not_found")
    text = text.replace(old, new)
    home.write_text(text, encoding="utf-8")

    (destination / "_headers").write_text(
        "/*\n"
        "  X-Content-Type-Options: nosniff\n"
        "  Referrer-Policy: strict-origin-when-cross-origin\n"
        "  Permissions-Policy: camera=(), microphone=(), geolocation=()\n",
        encoding="utf-8",
    )

    violations: list[dict[str, str]] = []
    for p in sorted(x for x in destination.rglob("*") if x.is_file()):
        try:
            body = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in PRIVATE_PATTERNS:
            if re.search(pattern, body, re.I):
                violations.append({"path": p.relative_to(destination).as_posix(), "pattern": pattern})
    if violations:
        raise RuntimeError("site_bundle_private_content:" + json.dumps(violations, ensure_ascii=False))

    (destination / "site_content_manifest.json").write_text(
        json.dumps(manifest(destination), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--destination", type=Path, default=Path(".work/site-dist/contextcord"))
    args = ap.parse_args()
    root = args.root.resolve()
    dest = args.destination if args.destination.is_absolute() else root / args.destination
    out = build(root, dest)
    print(out)
    print(f"files={sum(1 for p in out.rglob('*') if p.is_file())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
