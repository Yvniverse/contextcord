"""Explicit, recoverable migration from the legacy ``.harness`` namespace."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import LEGACY_STATE_DIR, PRIMARY_STATE_DIR
from .gitops import git_dir
from .util import absolute_path


SCHEMA = "contextcord-state-migration-v1"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return rows
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        rows[rel] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
    return rows


def _mapped_bytes(path: Path, data: bytes) -> bytes:
    # Configuration paths and the notes ref are compatibility data, not
    # schema IDs or historical evidence.  Preserve every other byte.
    if path.suffix.lower() not in {".toml", ".json", ".gitignore", ".gitattributes"}:
        return data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return text.replace(LEGACY_STATE_DIR, PRIMARY_STATE_DIR).replace(
        "refs/notes/project-harness", "refs/notes/contextcord"
    ).encode("utf-8")


def _expected_manifest(legacy: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for rel, row in _manifest(legacy).items():
        data = _mapped_bytes(legacy / rel, (legacy / rel).read_bytes())
        rows[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return rows


def _state_db(repo: Path) -> Path | None:
    try:
        candidate = git_dir(repo) / "project-harness" / "state.db"
    except Exception:
        return None
    return candidate if candidate.is_file() else None


def _now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def migrate_state(repo: Path, *, apply: bool = False) -> dict[str, Any]:
    repo = absolute_path(repo)
    legacy = repo / LEGACY_STATE_DIR
    target = repo / PRIMARY_STATE_DIR
    marker = target / "migration.json"
    if marker.is_file():
        return json.loads(marker.read_text(encoding="utf-8")) | {"status": "NOOP", "idempotent": True}
    if target.exists():
        return {"schema": SCHEMA, "status": "BLOCKED", "reason": "target_exists_without_migration_marker", "target": str(target)}
    if not (legacy / "project.toml").is_file():
        return {"schema": SCHEMA, "status": "NOT_APPLICABLE", "reason": "legacy_state_not_found", "source": str(legacy)}

    expected = _expected_manifest(legacy)
    old_db = _state_db(repo)
    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "DRY_RUN" if not apply else "PLANNED",
        "source": str(legacy.relative_to(repo)).replace("\\", "/"),
        "target": str(target.relative_to(repo)).replace("\\", "/"),
        "file_count": len(expected),
        "source_manifest": _manifest(legacy),
        "expected_target_manifest": expected,
        "state_db_source": str(old_db) if old_db else None,
        "backup": None,
        "equality_check": "NOT_RUN",
    }
    if not apply:
        return plan

    lock = repo / ".contextcord-migration.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError as exc:
        raise RuntimeError("migration_lock_exists_do_not_force_remove") from exc
    staging: Path | None = None
    try:
        if target.exists():
            return {"schema": SCHEMA, "status": "NOOP", "reason": "target_created_by_concurrent_migration", "idempotent": True}
        stamp = _now_slug()
        staging = Path(tempfile.mkdtemp(prefix="contextcord-migrate-", dir=str(repo)))
        staged_target = staging / PRIMARY_STATE_DIR
        staged_target.mkdir(parents=True, exist_ok=True)
        for rel in expected:
            source = legacy / rel
            dest = staged_target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_mapped_bytes(source, source.read_bytes()))
        if old_db:
            shutil.copy2(old_db, staged_target / "state.db")

        backup_root = staged_target / "migrations" / stamp / "legacy-harness"
        shutil.copytree(legacy, backup_root, symlinks=True)
        receipt = {
            "schema": SCHEMA,
            "status": "RECORDED",
            "source": plan["source"],
            "target": plan["target"],
            "backup": (PRIMARY_STATE_DIR + "/migrations/" + stamp + "/legacy-harness"),
            "source_manifest": plan["source_manifest"],
            "expected_target_manifest": expected,
            "state_db_source": str(old_db) if old_db else None,
        }
        (staged_target / "migration.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staged_target.rename(target)

        actual = _manifest(target)
        equality = all(actual.get(rel) == row for rel, row in expected.items())
        if old_db:
            equality = equality and (target / "state.db").is_file() and _sha(target / "state.db") == _sha(old_db)
        if not equality:
            raise RuntimeError("migration_equality_check_failed")
        receipt["equality_check"] = "PASS"
        (target / "migration.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt
    finally:
        if staging and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        lock.unlink(missing_ok=True)
