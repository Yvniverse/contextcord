from __future__ import annotations

import fnmatch
import ntpath
import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


MUTATING = {"write", "delete", "move", "deploy", "release", "push", "tag", "force-push"}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    operation: str
    target: str | None
    scope: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "operation": self.operation,
            "target": self.target,
            "scope": self.scope,
        }


def canonical_host_path(value: str) -> str:
    raw = os.path.expandvars(os.path.expanduser(value.strip())).replace("\\", "/")
    if ".." in PurePosixPath(raw).parts:
        raise ValueError("parent traversal is forbidden")
    m = re.match(r"^/mnt/([A-Za-z])/(.*)$", raw)
    if m:
        raw = f"{m.group(1).lower()}:/{m.group(2)}"
    m = re.match(r"^/run/desktop/mnt/host/([A-Za-z])/(.*)$", raw)
    if m:
        raw = f"{m.group(1).lower()}:/{m.group(2)}"
    if re.match(r"^[A-Za-z]:/", raw):
        drive, rest = raw[0].lower(), raw[2:]
        norm = posixpath.normpath("/" + rest).lstrip("/")
        return f"{drive}:/{norm}".rstrip("/")
    return posixpath.normpath(raw)


def normalize_target(repo: Path, target: str | None) -> tuple[str | None, bool]:
    if target is None:
        return None, False
    value = target.strip()
    if not value:
        return "", False
    windows_abs = bool(re.match(r"^[A-Za-z]:[\\/]", value))
    posix_abs = value.startswith("/")
    if windows_abs or posix_abs:
        return canonical_host_path(value), True
    if ".." in PurePosixPath(value.replace("\\", "/")).parts:
        raise ValueError("parent traversal is forbidden")
    normalized = posixpath.normpath(value.replace("\\", "/"))
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized, False


def _match(value: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(value, p) for p in patterns)


def _normalize_pattern(value: str) -> str:
    raw = os.path.expandvars(os.path.expanduser(value.strip())).replace("\\", "/")
    m = re.match(r"^/mnt/([A-Za-z])/(.*)$", raw)
    if m:
        return f"{m.group(1).lower()}:/{m.group(2)}"
    m = re.match(r"^/run/desktop/mnt/host/([A-Za-z])/(.*)$", raw)
    if m:
        return f"{m.group(1).lower()}:/{m.group(2)}"
    if re.match(r"^[A-Za-z]:/", raw):
        return raw[0].lower() + raw[1:]
    return raw


def _patterns(scope_cfg: dict[str, Any], key: str) -> list[str]:
    return [_normalize_pattern(str(x)) for x in scope_cfg.get(key, [])]


def authorize(repo: Path, authority: dict[str, Any], *, scope: str, operation: str, target: str | None = None) -> Decision:
    scopes = authority.get("scopes", {})
    if scope not in scopes:
        return Decision(False, "unknown_scope", operation, target, scope)
    cfg = scopes[scope]
    allowed_ops = {str(x) for x in cfg.get("allow_operations", [])}
    if operation not in allowed_ops:
        return Decision(False, "operation_not_allowed_in_scope", operation, target, scope)
    try:
        normalized, absolute = normalize_target(repo, target)
    except ValueError as exc:
        return Decision(False, str(exc), operation, target, scope)
    if normalized is None:
        return Decision(True, "operation_allowed_no_target", operation, target, scope)

    if not absolute and operation in {"read", "write", "delete", "move"}:
        try:
            reject_symlink_target(repo, normalized)
        except ValueError as exc:
            return Decision(False, str(exc), operation, normalized, scope)

    for row in authority.get("protected", []):
        pattern = _normalize_pattern(str(row.get("path", "")))
        operations = {str(x) for x in row.get("operations", list(MUTATING))}
        if pattern and operation in operations and _match(normalized, [pattern]):
            return Decision(False, str(row.get("reason", "protected_target")), operation, normalized, scope)

    forbidden = _patterns(cfg, "forbidden_patterns")
    if forbidden and _match(normalized, forbidden):
        return Decision(False, "target_matches_forbidden_pattern", operation, normalized, scope)

    if absolute:
        if not bool(cfg.get("allow_external", False)):
            return Decision(False, "external_path_not_allowed", operation, normalized, scope)
        if operation in MUTATING:
            pats = _patterns(cfg, "external_write_patterns")
        else:
            pats = _patterns(cfg, "external_read_patterns")
        if pats and not _match(normalized, pats):
            return Decision(False, "external_target_not_allowlisted", operation, normalized, scope)
        if operation in MUTATING and not pats:
            return Decision(False, "external_mutation_requires_explicit_allowlist", operation, normalized, scope)
        return Decision(True, "external_target_allowed", operation, normalized, scope)

    if operation in {"write", "delete", "move"}:
        pats = _patterns(cfg, "write_patterns")
        if pats and not _match(normalized, pats):
            return Decision(False, "repo_write_target_not_allowlisted", operation, normalized, scope)
    read_pats = _patterns(cfg, "read_patterns")
    if operation == "read" and read_pats and not _match(normalized, read_pats):
        return Decision(False, "repo_read_target_not_allowlisted", operation, normalized, scope)
    return Decision(True, "allowed", operation, normalized, scope)


def reject_symlink_target(repo: Path, target: str) -> None:
    normalized, absolute = normalize_target(repo, target)
    if absolute or normalized is None:
        return
    p = repo / normalized
    current = repo
    for part in Path(normalized).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError(f"symlink target forbidden: {current}")
