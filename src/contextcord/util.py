from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any, *, exclude_keys: Iterable[str] = ()) -> str:
    if isinstance(value, dict) and exclude_keys:
        blocked = set(exclude_keys)
        value = {k: v for k, v in value.items() if k not in blocked}
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def expand_string(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value))


def safe_id(value: str, *, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    return cleaned or fallback


def _link_or_reparse_point(path: Path) -> bool:
    """Reject junctions on Python 3.11 too, without following their target."""
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _repository_alias_candidate(repo: Path, candidate: Path, *, label: str) -> Path:
    """Accept an alternate spelling only with an OS same-directory witness.

    Windows TEMP may contain a genuine 8.3 name even though repo.resolve()
    expanded it. Resolution alone is insufficient: every lexical ancestor
    must be non-link/non-junction, and one must physically be the repo root.
    No permission or outside-repository policy is granted by this operation.
    """
    ancestors = (candidate, *candidate.parents)
    for ancestor in ancestors:
        if _link_or_reparse_point(ancestor):
            raise ValueError(f"{label}_path_traverses_symlink:{ancestor}")
    for ancestor in ancestors:
        try:
            same_root = ancestor.samefile(repo)
        except (FileNotFoundError, NotADirectoryError):
            continue
        if same_root:
            return repo / candidate.relative_to(ancestor)
    raise ValueError(f"{label}_path_outside_repository:{candidate}")


def ensure_repo_path(repo: Path, path: Path, *, label: str, allow_external: bool = False) -> tuple[Path, str]:
    """Resolve a path without silently following a symlink outside the repository.

    The final path itself may not be a symlink. Any existing parent component inside
    the repository also may not be a symlink. External paths are allowed only when
    explicitly requested by policy.
    """
    repo = repo.resolve()
    candidate = path if path.is_absolute() else repo / path
    if not allow_external:
        try:
            lexical = candidate.relative_to(repo)
        except ValueError:
            candidate = _repository_alias_candidate(repo, candidate, label=label)
            lexical = candidate.relative_to(repo)
        current = repo
        for part in lexical.parts:
            current = current / part
            if _link_or_reparse_point(current):
                raise ValueError(f"{label}_path_traverses_symlink:{current}")
    elif _link_or_reparse_point(candidate):
        raise ValueError(f"{label}_path_must_not_be_symlink:{path}")
    resolved = candidate.resolve(strict=False)
    if not allow_external:
        try:
            rel = resolved.relative_to(repo).as_posix()
        except ValueError as exc:
            raise ValueError(f"{label}_path_resolves_outside_repository:{path}") from exc
    else:
        try:
            rel = resolved.relative_to(repo).as_posix()
        except ValueError:
            rel = str(resolved)
    return resolved, rel
