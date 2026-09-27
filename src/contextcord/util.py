from __future__ import annotations

import hashlib
import json
import os
import re
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
        except ValueError as exc:
            raise ValueError(f"{label}_path_outside_repository:{path}") from exc
        current = repo
        for part in lexical.parts:
            current = current / part
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise ValueError(f"{label}_path_traverses_symlink:{current}")
    elif candidate.is_symlink():
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
