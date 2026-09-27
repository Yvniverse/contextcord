"""Strict Public Surface Brand Gate v2.

The whole-repository residue gate intentionally allows historical and
compatibility material.  This gate scans active public-facing files and only
allows legacy tokens when the surrounding line explicitly labels migration,
compatibility, history or provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


LEGACY_PATTERN = re.compile(
    r"Agent[-_ ]?Nexus|Project[-_ ]?Harness|project[-_]operations[-_]harness|"
    r"project[-_]harness|\bpoh\b|\.harness|harness_",
    re.IGNORECASE,
)
TEXT_EXTENSIONS = {".md", ".html", ".js", ".css", ".json", ".toml", ".yml", ".yaml", ".txt"}
ALLOW_MARKERS = (
    "legacy",
    "deprecated",
    "compatibility",
    "historical",
    "history",
    "migration",
    "provenance",
    "preserved",
    "兼容",
    "弃用",
    "历史",
    "迁移",
)


def _active_paths(root: Path) -> list[Path]:
    paths: set[Path] = set()
    root_files = (
        "README.md",
        "README_CN.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "NOTICE",
        "SECURITY.md",
    )
    for relative in root_files:
        path = root / relative
        if path.is_file() and not path.is_symlink():
            paths.add(path)
    for directory in ("web", "examples"):
        base = root / directory
        if base.is_dir():
            paths.update(
                path
                for path in base.rglob("*")
                if path.is_file() and not path.is_symlink() and path.suffix.lower() in TEXT_EXTENSIONS
            )
    docs = root / "docs"
    if docs.is_dir():
        for pattern in (
            "QUICKSTART*",
            "ARCHITECTURE*",
            "INTEGRATIONS*",
            "JEV_DECISION_FABRIC*",
        ):
            paths.update(path for path in docs.glob(pattern) if path.is_file() and not path.is_symlink())
    adapters = root / "support" / "adapters"
    if adapters.is_dir():
        paths.update(path for path in adapters.glob("*.adapter.json") if path.is_file() and not path.is_symlink())
    for relative in (
        "research/host_evidence_registry_v3.json",
        "schemas/host-evidence-registry.schema.json",
        "src/contextcord/schemas/host-evidence-registry.schema.json",
        "support/schemas/host-evidence-registry-v3.schema.json",
    ):
        path = root / relative
        if path.is_file() and not path.is_symlink():
            paths.add(path)
    return sorted(paths)


def _allowed(relative: str, line: str) -> bool:
    lowered = line.casefold()
    if relative == "LICENSE":
        return any(marker in lowered for marker in ("copyright", "legacy", "provenance"))
    return any(marker in lowered for marker in ALLOW_MARKERS)


def audit(root: Path) -> dict[str, object]:
    root = root.resolve()
    matches: list[dict[str, object]] = []
    for path in _active_paths(root):
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        compatibility_fixture = (
            relative.startswith("examples/generic/")
            and "legacy compatibility" in "\n".join(text.splitlines()[:4]).casefold()
        )
        for line_number, line in enumerate(text.splitlines(), 1):
            tokens = [match.group(0) for match in LEGACY_PATTERN.finditer(line)]
            if not tokens:
                continue
            matches.append(
                {
                    "path": relative,
                    "line": line_number,
                    "tokens": tokens,
                    "allowlisted": compatibility_fixture or _allowed(relative, line),
                }
            )
    unallowlisted = [row for row in matches if not row["allowlisted"]]
    return {
        "schema": "contextcord-public-surface-brand-gate-v2",
        "status": "PASS" if not unallowlisted else "FAIL",
        "scanned_files": len(_active_paths(root)),
        "matched_lines": len(matches),
        "unallowlisted_lines": len(unallowlisted),
        "files_sha256": hashlib.sha256(json.dumps(matches, sort_keys=True).encode("utf-8")).hexdigest(),
        "matches": matches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.repo)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "matches"}, ensure_ascii=False))
    for row in result["matches"]:
        if not row["allowlisted"]:
            print(f"ERROR: {row['path']}:{row['line']}: {', '.join(row['tokens'])}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
