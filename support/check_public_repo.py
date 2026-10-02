"""Allowlist and secret-safety gate for a local public repository staging tree."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


REQUIRED = [
    "README.md", "README_CN.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
    "ACKNOWLEDGEMENTS.md", "SECURITY.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "CITATION.cff", "pyproject.toml",
    "docs/QUICKSTART.md", "docs/QUICKSTART_CN.md", "docs/INTEGRATIONS.md",
    "docs/INTEGRATIONS_CN.md", "docs/ARCHITECTURE.md", "docs/ARCHITECTURE_CN.md",
    "docs/ROUTER.md", "docs/ROUTER_CN.md", "research/host_evidence_registry_v3.json",
    ".github/PULL_REQUEST_TEMPLATE.md", ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/config.yml", ".github/ISSUE_TEMPLATE/feature_request.yml",
]
PRIVATE_PARTS = {"reference", "Source_code", ".work", ".git", "oracle"}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA)? ?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:bearer|authorization)\s*[:=]\s*[A-Za-z0-9._=-]{20,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token)\s*[:=]\s*['\"][^'\"]{16,}['\"]"),
]
FORBIDDEN_ACTIVE_PATHS = (
    "web/integrations/",
    "web/research/",
    "web/workbench/",
    "docs/RELEASE_READINESS.md",
    "support/host_registry_v2.example.json",
    "research/host_evidence_registry.json",
    "context_sufficiency_test_trials.jsonl",
    "live_benchmark_v3_trials.jsonl",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors: list[str] = []
    required = REQUIRED + (["web/index.html", "web/docs/index.html"] if (root / "web").exists() else [])
    for rel in required:
        if not (root / rel).is_file():
            errors.append(f"required file missing: {rel}")
    staged_paths = {item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file()}
    for rel in sorted(staged_paths):
        if any(bad in rel for bad in FORBIDDEN_ACTIVE_PATHS):
            errors.append(f"forbidden active path: {rel}")
    for rel in ("README.md", "README_CN.md", "web/index.html", "web/docs/index.html"):
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "ROUTER_V2" in text:
            errors.append(f"active Router v2 reference: {rel}")
        if rel in {"README.md", "README_CN.md", "web/index.html", "web/docs/index.html"} and re.search(r"Agent[-_ ]?Nexus|Project[-_ ]?Harness|ProjectTrust", text, re.I):
            errors.append(f"legacy brand in current surface: {rel}")
    for rel in ("docs/HOST_ADAPTER_MATRIX.json", "docs/HOST_TIER_MATRIX.md", "support/host_tiers.json"):
        path = root / rel
        if path.is_file() and "0.6.1a2" in path.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"stale release marker: {rel}")
    maps = list((root / "docs/architecture/maps").glob("*.html")) if (root / "docs/architecture/maps").is_dir() else []
    specs = list((root / "docs/architecture/specs").glob("*.json")) if (root / "docs/architecture/specs").is_dir() else []
    if len(maps) != 12:
        errors.append(f"active Archify map count: {len(maps)}")
    if len(specs) != 12:
        errors.append(f"active Archify spec count: {len(specs)}")
    for item in root.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        relative = item.relative_to(root)
        if any(part in PRIVATE_PARTS for part in relative.parts):
            errors.append(f"private path included: {relative.as_posix()}")
            continue
        if item.suffix.lower() in {".zip", ".7z", ".tar", ".gz", ".pem", ".key"}:
            errors.append(f"archive or key included: {relative.as_posix()}")
            continue
        try:
            text = item.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"secret-like content: {relative.as_posix()}")
                break
    print(f"errors={len(errors)}")
    for item in errors:
        print(f"ERROR: {item}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
