from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Any

from .config import HarnessConfig
from .util import ensure_repo_path
from .gitops import changed_paths, git, list_material_files

TRUTH_KINDS = {
    "source", "runtime_input", "durable_memory", "evidence",
    "generated", "session_state", "qualification", "ignore",
}
MATERIAL_TRUTH_KINDS = {"source", "runtime_input"}
CLOSEOUT_DIRTY_KINDS = {"source", "runtime_input", "durable_memory"}


@dataclass(frozen=True)
class ClassifiedPath:
    path: str
    kind: str


def classify_path(cfg: HarnessConfig, rel: str) -> str:
    rel = rel.replace("\\", "/")
    rules = cfg.truth.get("rules", [])
    for row in rules:
        pattern = str(row.get("pattern") or "")
        kind = str(row.get("kind") or "ignore")
        if pattern and kind in TRUTH_KINDS and fnmatch.fnmatchcase(rel, pattern):
            return kind
    default = str(cfg.truth.get("defaults", {}).get("kind") or "source")
    return default if default in TRUTH_KINDS else "source"


def classified_files(cfg: HarnessConfig) -> list[ClassifiedPath]:
    return [ClassifiedPath(path=rel, kind=classify_path(cfg, rel)) for rel in list_material_files(cfg.repo)]


def _object_hash(path: Path, executable_override: bool | None = None) -> tuple[str, str, bool | None, int]:
    if path.is_symlink():
        target = os.readlink(path)
        payload = b"symlink\0" + target.encode("utf-8", "surrogateescape")
        return hashlib.sha256(payload).hexdigest(), "symlink", None, len(payload)
    if not path.is_file():
        return "", "missing", None, 0
    data = path.read_bytes()
    executable = bool(path.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    if executable_override is not None:
        executable = executable_override
    payload = b"file\0exec=" + (b"1" if executable else b"0") + b"\0" + data
    return hashlib.sha256(payload).hexdigest(), "file", executable, len(data)


def content_fingerprint(cfg: HarnessConfig, *, kinds: Iterable[str] = ("source", "runtime_input"), include_files: bool = True) -> dict[str, Any]:
    selected = set(kinds)
    digest = hashlib.sha256()
    rows: list[dict[str, Any]] = []
    bytes_total = 0
    index_modes = {}
    if os.name == "nt":
        # NTFS does not have the POSIX executable bit; Git's index is authoritative.
        raw = git(cfg.repo, "ls-files", "--stage", "-z")
        for entry in raw.split("\0"):
            if "\t" in entry:
                header, rel = entry.split("\t", 1)
                index_modes[rel] = header.split()[0] == "100755"
    for item in classified_files(cfg):
        if item.kind not in selected:
            continue
        p = cfg.repo / item.path
        obj_hash, obj_type, executable, size = _object_hash(p, index_modes.get(item.path, False) if os.name == "nt" else None)
        if obj_type == "missing":
            continue
        digest.update(item.path.encode("utf-8", "surrogateescape")); digest.update(b"\0")
        digest.update(item.kind.encode("utf-8")); digest.update(b"\0")
        digest.update(obj_type.encode("ascii")); digest.update(b"\0")
        digest.update(obj_hash.encode("ascii")); digest.update(b"\0")
        row: dict[str, Any] = {"path": item.path, "kind": item.kind, "object_type": obj_type, "sha256": obj_hash, "bytes": size}
        if executable is not None:
            row["executable"] = executable
        rows.append(row)
        bytes_total += size
    value: dict[str, Any] = {
        "algorithm": "sha256-path-kind-object-v2",
        "kinds": sorted(selected),
        "sha256": digest.hexdigest(),
        "file_count": len(rows),
        "bytes": bytes_total,
    }
    if include_files:
        value["files"] = rows
    return value


def memory_fingerprint(cfg: HarnessConfig, *, include_files: bool = True) -> dict[str, Any]:
    for item in classified_files(cfg):
        if item.kind == "durable_memory":
            # Durable memory is repository-owned state, unlike ordinary source
            # symlinks whose link object is intentionally fingerprinted.
            ensure_repo_path(cfg.repo, Path(item.path), label="durable_memory", allow_external=False)
    return content_fingerprint(cfg, kinds=("durable_memory",), include_files=include_files)


def classification_counts(cfg: HarnessConfig) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in classified_files(cfg):
        counts[item.kind] = counts.get(item.kind, 0) + 1
    return dict(sorted(counts.items()))


def dirty_truth_paths(cfg: HarnessConfig, *, kinds: Iterable[str] = CLOSEOUT_DIRTY_KINDS) -> list[str]:
    selected = set(kinds)
    return [rel for rel in changed_paths(cfg.repo) if classify_path(cfg, rel) in selected]


def latest_commit_for_kinds(cfg: HarnessConfig, kinds: Iterable[str]) -> str | None:
    selected = set(kinds)
    paths = [x.path for x in classified_files(cfg) if x.kind in selected]
    if not paths:
        return None
    candidates: set[str] = set()
    for start in range(0, len(paths), 200):
        raw = git(cfg.repo, "log", "-1", "--format=%H", "--", *paths[start:start+200], check=False)
        if raw:
            candidates.add(raw.splitlines()[0].strip())
    if not candidates:
        return None
    ranked: list[tuple[int, str]] = []
    for commit in candidates:
        raw = git(cfg.repo, "rev-list", "--count", f"{commit}..HEAD", check=False)
        ranked.append((int(raw) if raw.isdigit() else 10**12, commit))
    return min(ranked)[1]
