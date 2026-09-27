from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
from typing import Any

from .config import HarnessConfig
from .contracts import validate
from .identity import source_identity
from .runtime import run_probes
from .util import sha256_bytes, sha256_json

COMMON_DEPENDENCY_FILES = [
    "pyproject.toml", "requirements.txt", "requirements.lock", "uv.lock", "poetry.lock",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "Cargo.lock", "go.sum",
]


def _object_hash(path: Path) -> tuple[str, str, int]:
    if path.is_symlink():
        target = os.readlink(path)
        raw = b"symlink\0" + target.encode("utf-8", "surrogateescape")
        return sha256_bytes(raw), "symlink", len(raw)
    data = path.read_bytes()
    return sha256_bytes(data), "file", len(data)


def _expand_patterns(repo: Path, patterns: list[str]) -> tuple[list[Path], list[str]]:
    files: dict[str, Path] = {}
    missing: list[str] = []
    for raw in patterns:
        pattern = str(raw).replace("\\", "/")
        p = Path(pattern)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError(f"release_identity_pattern_outside_repository:{pattern}")
        matches: list[Path]
        if any(token in pattern for token in ("*", "?", "[")):
            matches = [x for x in repo.glob(pattern) if x.is_file() or x.is_symlink()]
        else:
            candidate = repo / pattern
            matches = [candidate] if candidate.is_file() or candidate.is_symlink() else []
        if not matches:
            missing.append(pattern)
        for path in matches:
            try:
                rel = path.relative_to(repo).as_posix()
            except ValueError as exc:
                raise ValueError(f"release_identity_match_outside_repository:{path}") from exc
            files[rel] = path
    return [files[k] for k in sorted(files)], missing


def _group(repo: Path, patterns: list[str]) -> dict[str, Any]:
    paths, missing = _expand_patterns(repo, patterns)
    h = hashlib.sha256(); rows: list[dict[str, Any]] = []
    for path in paths:
        rel = path.relative_to(repo).as_posix(); digest, object_type, size = _object_hash(path)
        h.update(rel.encode("utf-8", "surrogateescape")); h.update(b"\0"); h.update(object_type.encode()); h.update(b"\0"); h.update(digest.encode()); h.update(b"\0")
        rows.append({"path": rel, "object_type": object_type, "sha256": digest, "bytes": size})
    return {"algorithm": "sha256-path-object-v1", "patterns": patterns, "sha256": h.hexdigest(), "file_count": len(rows), "files": rows, "missing_patterns": missing}


def collect(cfg: HarnessConfig, *, scope: str | None = None) -> dict[str, Any]:
    section = cfg.project.get("release_identity", {})
    dependency_patterns = [str(x) for x in section.get("dependency_files", [])]
    if not dependency_patterns:
        dependency_patterns = [name for name in COMMON_DEPENDENCY_FILES if (cfg.repo / name).exists()]
    config_patterns = [str(x) for x in section.get("config_files", [f"{cfg.root.name}/*.toml"])]
    migration_patterns = [str(x) for x in section.get("migration_files", [])]
    required_patterns = [str(x) for x in section.get("required_patterns", [])]

    groups = {
        "dependencies": _group(cfg.repo, dependency_patterns),
        "configuration": _group(cfg.repo, config_patterns),
        "migrations": _group(cfg.repo, migration_patterns),
    }
    required_group = _group(cfg.repo, required_patterns)
    runtime = run_probes(cfg.repo, cfg.runtime, scope=scope)
    blockers: list[str] = []
    if required_group["missing_patterns"]:
        blockers.extend(f"required_release_identity_pattern_missing:{x}" for x in required_group["missing_patterns"])
    if runtime.get("required_by_scope") and runtime.get("status") != "PASS":
        blockers.append(f"required_runtime_not_pass:{runtime.get('status')}")
    value: dict[str, Any] = {
        "schema": "project-harness-release-identity-v1",
        "source_identity": source_identity(cfg),
        "groups": {**groups, "required": required_group},
        "runtime": runtime,
        "status": "BLOCKED" if blockers else "PASS",
        "blockers": blockers,
    }
    value["release_sha256"] = sha256_json(value, exclude_keys=("release_sha256",))
    validate("release-identity", value)
    return value
