"""Strict gate for canonical installed interfaces and newly emitted schema identities."""
from __future__ import annotations
import argparse
import json
import re
import tomllib
from pathlib import Path

TOKENS = re.compile(r"project_harness|project-harness|agent-nexus|\bpoh\b|project-operations-harness|Project Harness|ProjectHarness|Agent Nexus", re.I)

def audit(root: Path) -> dict:
    errors = []
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if metadata["project"]["scripts"] != {"contextcord": "contextcord.entrypoint:main"}:
        errors.append("console_scripts_must_be_canonical")
    if (root / "src/project_harness").exists():
        errors.append("retired_import_package_present")
    for directory in ("src/contextcord", "schemas", "support/adapters"):
        for item in (root / directory).rglob("*"):
            if not item.is_file() or item.suffix not in {".py", ".json", ".toml"}:
                continue
            # The explicit importer reads exactly two legacy storage identifiers;
            # it emits no old CLI, MCP, schema or automatic compatibility surface.
            for number, line in enumerate(item.read_text(encoding="utf-8").splitlines(), 1):
                if item.name == "migration.py" and line.strip() in {
                    '"refs/notes/project-harness", "refs/notes/contextcord"',
                    'candidate = git_dir(repo) / "project-harness" / "state.db"',
                }:
                    continue
                if TOKENS.search(line):
                    errors.append(f"{item.relative_to(root).as_posix()}:{number}")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "scope": "active_installed_interfaces"}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = audit(args.root.resolve())
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
