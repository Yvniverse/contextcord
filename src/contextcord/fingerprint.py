from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
from typing import Any

from .gitops import list_material_files


def _match_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def content_fingerprint(repo: Path, exclude: list[str] | None = None) -> dict[str, object]:
    """Legacy v0.2 fingerprint API kept for migration tooling/tests.

    New trust decisions use project_harness.truth.content_fingerprint through a
    HarnessConfig, which includes artifact kinds, symlink targets and exec bits.
    """
    exclude = exclude or []
    h = hashlib.sha256(); count = 0; bytes_total = 0; files: list[str] = []
    for rel in list_material_files(repo):
        if _match_any(rel, exclude):
            continue
        p = repo / rel
        if p.is_symlink():
            data = ("symlink:" + os.readlink(p)).encode("utf-8", "surrogateescape")
        elif p.is_file():
            data = p.read_bytes()
        else:
            continue
        h.update(rel.encode("utf-8", errors="surrogateescape")); h.update(b"\0")
        h.update(hashlib.sha256(data).digest()); h.update(b"\0")
        files.append(rel); count += 1; bytes_total += len(data)
    return {"sha256": h.hexdigest(), "file_count": count, "bytes": bytes_total, "files": files}


def policy_fingerprint(repo: Path, knowledge_entrypoints: list[str] | None = None) -> dict[str, object]:
    """Hash trusted policy and knowledge without following symlinks."""
    h = hashlib.sha256(); files: list[str] = []; candidates: list[str] = []
    harness = repo / ".harness"
    if harness.is_dir():
        for p in sorted(harness.glob("*.toml")):
            if p.is_symlink():
                raise ValueError(f"trusted policy must not be a symlink: {p}")
            if p.is_file():
                candidates.append(p.relative_to(repo).as_posix())
    for rel in knowledge_entrypoints or []:
        if rel not in candidates:
            candidates.append(rel)
    bytes_total = 0
    for rel in candidates:
        p = repo / rel
        if p.is_symlink():
            raise ValueError(f"knowledge entrypoint must not be a symlink: {rel}")
        if not p.is_file():
            continue
        data = p.read_bytes()
        h.update(rel.encode("utf-8", errors="surrogateescape")); h.update(b"\0")
        h.update(hashlib.sha256(data).digest()); h.update(b"\0")
        files.append(rel); bytes_total += len(data)
    return {"sha256": h.hexdigest(), "file_count": len(files), "bytes": bytes_total, "files": files}
