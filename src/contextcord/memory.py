"""Portable live engineering memory on top of the existing StateStore.

This module deliberately keeps the transfer format logical and repository
relative.  The ordinary ``events`` table remains the local append-only audit
chain; imported source events are retained in ``memory_events`` so importing a
task cannot splice an unrelated machine's hash chain into the target chain.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .config import HarnessConfig
from .contracts import validate
from .identity import source_identity
from .store import StateStore
from .truth import classify_path
from .util import canonical_json, ensure_repo_path, sha256_bytes, sha256_file, sha256_json, utc_now


SCHEMA = "contextcord-portable-memory-v1"
MAX_MEMBERS = 20_000
MAX_UNCOMPRESSED = 256 * 1024 * 1024
SECRET_NAMES = {".env", ".env.local", ".env.production", "id_ed25519", "id_rsa"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _safe_relative(value: str, *, label: str = "portable_memory_path") -> str:
    raw = str(value)
    p = PurePosixPath(raw)
    if (
        not raw
        or p.is_absolute()
        or "\\" in raw
        or ".." in p.parts
        or "." in p.parts
        or PureWindowsPath(raw).drive
        or ":" in raw
        or p.as_posix() != raw
        or any(part.endswith((".", " ")) for part in p.parts)
    ):
        raise ValueError(f"{label}_unsafe:{value}")
    return raw


def _secret_like(value: str) -> bool:
    path = PurePosixPath(value)
    name = path.name.casefold()
    return name in SECRET_NAMES or name.endswith(tuple(SECRET_SUFFIXES)) or name.startswith(".env.")


def _safe_member(value: str) -> str:
    if value == "manifest.json":
        return value
    p = PurePosixPath(value)
    if (
        not value
        or p.is_absolute()
        or "\\" in value
        or ".." in p.parts
        or "." in p.parts
        or PureWindowsPath(value).drive
        or ":" in value
        or p.as_posix() != value
        or _secret_like(value)
    ):
        raise ValueError(f"portable_memory_unsafe_archive_member:{value}")
    if p.parts[0] not in {"objects", "payloads"}:
        raise ValueError(f"portable_memory_unexpected_archive_member:{value}")
    return value


def _json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _object(objects: dict[str, bytes], entries: list[dict[str, Any]], *, kind: str,
            value: dict[str, Any], task_id: str, session_id: str | None = None) -> str:
    raw = _json_bytes(value)
    digest = sha256_bytes(raw)
    path = f"objects/{digest}.json"
    objects[path] = raw
    entry: dict[str, Any] = {
        "kind": kind,
        "sha256": digest,
        "bytes": len(raw),
        "path": path,
        "task_id": task_id,
    }
    if session_id is not None:
        entry["session_id"] = session_id
    entries.append(entry)
    return digest


def _payload(objects: dict[str, bytes], entries: list[dict[str, Any]], *, raw: bytes,
             path: str, task_id: str, source_path: str) -> str:
    digest = sha256_bytes(raw)
    member = f"payloads/{digest}.bin"
    if member not in objects:
        objects[member] = raw
        entries.append({
            "kind": "evidence_payload",
            "sha256": digest,
            "bytes": len(raw),
            "path": member,
            "source_path": source_path,
            "task_id": task_id,
        })
    return digest


def _row_json(row: dict[str, Any], *, json_columns: tuple[str, ...] = ()) -> dict[str, Any]:
    value = dict(row)
    for column in json_columns:
        if column in value and isinstance(value[column], str):
            value[column] = json.loads(value[column])
    return value


def _dependency_snapshot(repo: Path, note: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    stored = note.get("dependency_fingerprints") or {}
    for raw_path in note.get("depends_on") or []:
        rel = _safe_relative(str(raw_path), label="portable_memory_dependency")
        if _secret_like(rel):
            raise ValueError(f"portable_memory_secret_dependency_forbidden:{rel}")
        target = repo / rel
        exists = target.is_file() and not target.is_symlink()
        current_hash = sha256_file(target) if exists else None
        expected = stored.get(rel, current_hash)
        refs.append({
            "path": rel,
            "expected_sha256": expected,
            "export_sha256": current_hash,
            "bytes": target.stat().st_size if exists else None,
            "status_at_export": "UNCHANGED" if exists and expected == current_hash else "MISSING" if not exists else "STALE",
        })
    return refs


def _dependency_status(repo: Path, rel: str, expected: str | None) -> dict[str, Any]:
    rel = _safe_relative(rel, label="portable_memory_dependency")
    path = repo / rel
    if not path.is_file() or path.is_symlink():
        return {"path": rel, "expected_sha256": expected, "current_sha256": None,
                "status": "MISSING", "qualification": "REVALIDATE"}
    current = sha256_file(path)
    if expected and current == expected:
        status = "UNCHANGED"; qualification = "UNCHANGED"
    else:
        status = "STALE"; qualification = "REVALIDATE"
    return {"path": rel, "expected_sha256": expected, "current_sha256": current,
            "status": status, "qualification": qualification}


def _portable_identity(value: dict[str, Any]) -> dict[str, Any]:
    """Keep identity useful for transfer while excluding machine paths."""
    out = json.loads(json.dumps(value, ensure_ascii=False))
    out.pop("repo", None)
    return out


def _manifest_hash(value: dict[str, Any]) -> str:
    return sha256_json(value, exclude_keys=("bundle_sha256",))


def export_memory(cfg: HarnessConfig, *, task_id: str, output: Path) -> dict[str, Any]:
    output = output.resolve()
    objects: dict[str, bytes] = {}
    entries: list[dict[str, Any]] = []
    payload_entries: list[dict[str, Any]] = []
    with StateStore(cfg.repo) as store:
        task = store.get_task(task_id)
        if task is None:
            raise ValueError(f"unknown task: {task_id}")
        sessions = [_row_json(row, json_columns=("summary_json",)) for row in store.sessions_for_task(task_id)]
        session_ids = {str(row["session_id"]) for row in sessions}
        notes = store.notes_for_task(task_id)
        jobs = store.context_jobs_for_task(task_id)
        evidence_rows = store.evidence_for_task(task_id)
        events = [row for row in store.recent_events(1_000_000)
                  if row.get("task_id") == task_id or row.get("session_id") in session_ids]
        memory_events = store.memory_events_for_task(task_id)
        for row in events:
            if row.get("task_id") not in {None, task_id} and row.get("session_id") not in session_ids:
                raise ValueError("portable_memory_cross_task_event")

        task_record = _row_json(task, json_columns=())
        task_record["current_qualification"] = "NOT_EVALUATED"
        _object(objects, entries, kind="task", value=task_record, task_id=task_id)

        for row in sessions:
            row["historical"] = True
            _object(objects, entries, kind="session", value=row, task_id=task_id, session_id=row["session_id"])

        dependency_refs: dict[str, dict[str, Any]] = {}
        for row in notes:
            row = dict(row)
            row["dependency_snapshot"] = _dependency_snapshot(cfg.repo, row)
            for ref in row["dependency_snapshot"]:
                dependency_refs[ref["path"]] = ref
            _object(objects, entries, kind="note", value=row, task_id=task_id, session_id=row.get("session_id"))

        for row in jobs:
            row = dict(row)
            row["historical"] = True
            _object(objects, entries, kind="context_job", value=row, task_id=task_id, session_id=row.get("session_id"))

        evidence_manifest: list[dict[str, Any]] = []
        for row in evidence_rows:
            row = dict(row)
            evidence_id = row.get("portable_id") or f"evidence-{task_id}-{row['id']}"
            row["evidence_id"] = evidence_id
            row["historical_classification"] = "HISTORICAL"
            row["historical_status"] = row.get("status")
            row["current_qualification"] = "NOT_EVALUATED"
            row["metadata"] = row.pop("metadata", {})
            raw_path = row.get("path")
            if raw_path:
                rel = _safe_relative(str(raw_path), label="portable_memory_evidence")
                row["path"] = rel
                if _secret_like(rel):
                    raise ValueError(f"portable_memory_secret_evidence_forbidden:{rel}")
                try:
                    candidate, rel_resolved = ensure_repo_path(cfg.repo, Path(rel), label="portable_memory_evidence")
                except ValueError:
                    candidate = None; rel_resolved = rel
                if candidate and candidate.is_file() and not candidate.is_symlink() and classify_path(cfg, rel) in {"evidence", "generated", "qualification"}:
                    payload_ref = _payload(objects, payload_entries, raw=candidate.read_bytes(), path=rel, task_id=task_id, source_path=rel)
                    row["payload_ref"] = payload_ref
                    row["payload_status"] = "INCLUDED"
                else:
                    row["payload_ref"] = None
                    row["payload_status"] = "REFERENCE_ONLY"
            else:
                row["payload_ref"] = None
                row["payload_status"] = "REFERENCE_ONLY"
            evidence_manifest.append(row)
            _object(objects, entries, kind="evidence", value=row, task_id=task_id, session_id=row.get("session_id"))

        for row in events:
            _object(objects, entries, kind="event", value=row, task_id=task_id, session_id=row.get("session_id"))
        for row in memory_events:
            _object(objects, entries, kind="memory_event", value=row, task_id=task_id, session_id=row.get("session_id"))

        source = _portable_identity(source_identity(cfg))

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "schema_version": 1,
        "task_id": task_id,
        "task_ids": [task_id],
        "source_repo_relative": ".",
        "source_identity": source,
        "exported_at": utc_now(),
        "current_qualification": "NOT_EVALUATED",
        "historical_evidence_classification": "HISTORICAL",
        "dependency_refs": sorted(dependency_refs.values(), key=lambda row: row["path"]),
        "redactions": {
            "secrets_excluded": True,
            "excluded_patterns": [".env", ".env.*", "*.pem", "*.key", "id_ed25519", "id_rsa"],
        },
        "objects": sorted(entries, key=lambda row: (row["kind"], row["path"])),
        "payloads": sorted(payload_entries, key=lambda row: row["path"]),
    }
    manifest["object_count"] = len(manifest["objects"])
    manifest["bundle_sha256"] = _manifest_hash(manifest)
    validate("portable-memory", manifest)

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            for member in sorted(objects):
                archive.writestr(member, objects[member])
        os.replace(tmp, output)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {"status": "PASS", "output": str(output), "bundle_sha256": manifest["bundle_sha256"],
            "task_id": task_id, "object_count": manifest["object_count"],
            "dependency_count": len(manifest["dependency_refs"]), "manifest": manifest}


def inspect_memory_bundle(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    path = path.resolve()
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) > MAX_MEMBERS or sum(info.file_size for info in infos) > MAX_UNCOMPRESSED:
            raise ValueError("portable_memory_bundle_size_limit")
        if len({name.casefold() for name in names}) != len(names) or len(set(names)) != len(names):
            raise ValueError("portable_memory_duplicate_archive_path")
        for name in names:
            _safe_member(name)
        if "manifest.json" not in names:
            raise ValueError("portable_memory_manifest_missing")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        validate("portable-memory", manifest)
        if _manifest_hash(manifest) != manifest.get("bundle_sha256"):
            raise ValueError("portable_memory_manifest_hash_mismatch")
        expected = {str(row["path"]): row for row in [*manifest.get("objects", []), *manifest.get("payloads", [])]}
        if len(expected) != len(manifest.get("objects", [])) + len(manifest.get("payloads", [])):
            raise ValueError("portable_memory_duplicate_manifest_member")
        actual = {name for name in names if name != "manifest.json"}
        if actual != set(expected):
            raise ValueError("portable_memory_member_set_mismatch")
        data: dict[str, bytes] = {}
        for member, row in expected.items():
            raw = archive.read(member)
            digest = str(row.get("sha256"))
            if not SHA_RE.fullmatch(digest) or sha256_bytes(raw) != digest or len(raw) != row.get("bytes"):
                raise ValueError(f"portable_memory_member_hash_mismatch:{member}")
            data[member] = raw
            if member.startswith("objects/"):
                json.loads(raw.decode("utf-8"))
    return manifest, data


def _objects_by_kind(manifest: dict[str, Any], data: dict[str, bytes]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in manifest.get("objects", []):
        try:
            value = json.loads(data[entry["path"]].decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"portable_memory_invalid_object:{entry.get('path')}") from exc
        if value.get("task_id") not in {manifest.get("task_id"), None} and entry.get("kind") != "event":
            raise ValueError("portable_memory_cross_task_object")
        out.setdefault(str(entry["kind"]), []).append(value)
    return out


def _canonical_record(value: dict[str, Any]) -> str:
    return canonical_json(value)


def _existing_task_conflict(store: StateStore, incoming: dict[str, Any]) -> str | None:
    existing = store.get_task(str(incoming["task_id"]))
    if existing is None:
        return None
    comparable = dict(incoming)
    comparable.pop("current_qualification", None)
    if _canonical_record(existing) != _canonical_record(comparable):
        return f"portable_memory_task_conflict:{incoming['task_id']}"
    return None


def _same_or_conflict(existing: dict[str, Any] | None, incoming: dict[str, Any], label: str, key: str) -> str | None:
    if existing is None:
        return None
    if _canonical_record(existing) != _canonical_record(incoming):
        return f"{label}_conflict:{incoming.get(key)}"
    return None


def _planned_dependencies(cfg: HarnessConfig, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [_dependency_status(cfg.repo, str(row["path"]), row.get("expected_sha256")) for row in manifest.get("dependency_refs", [])]


def plan_memory_import(cfg: HarnessConfig, *, bundle: Path) -> dict[str, Any]:
    manifest, data = inspect_memory_bundle(bundle)
    task_id = str(manifest["task_id"])
    if manifest.get("task_ids") != [task_id]:
        raise ValueError("portable_memory_multiple_tasks_not_supported")
    if manifest.get("current_qualification") in {"PASS", "VERIFIED"}:
        raise ValueError("portable_memory_current_qualification_must_be_not_evaluated")
    objects = _objects_by_kind(manifest, data)
    tasks = objects.get("task", [])
    if len(tasks) != 1 or str(tasks[0].get("task_id")) != task_id:
        raise ValueError("portable_memory_task_object_missing_or_mismatched")
    sessions = objects.get("session", [])
    session_ids = {str(row["session_id"]) for row in sessions}
    notes = objects.get("note", [])
    jobs = objects.get("context_job", [])
    evidence = objects.get("evidence", [])
    events = [*objects.get("event", []), *objects.get("memory_event", [])]
    for row in sessions:
        if str(row.get("task_id")) != task_id:
            raise ValueError("portable_memory_cross_task_session")
    for row in notes:
        if str(row.get("task_id")) != task_id or (row.get("session_id") is not None and str(row["session_id"]) not in session_ids):
            raise ValueError("portable_memory_cross_task_note")
    for row in jobs:
        if str(row.get("task_id")) != task_id or (row.get("session_id") is not None and str(row["session_id"]) not in session_ids):
            raise ValueError("portable_memory_cross_task_context_job")
    for row in evidence:
        if str(row.get("task_id")) != task_id or (row.get("session_id") is not None and str(row["session_id"]) not in session_ids):
            raise ValueError("portable_memory_cross_task_evidence")
    for row in events:
        if str(row.get("task_id")) not in {task_id, "None", "null"} and row.get("session_id") not in session_ids:
            raise ValueError("portable_memory_cross_task_event")
        body = {key: row.get(key) for key in ("event_id", "session_id", "task_id", "event_type", "ts", "payload", "prev_hash")}
        if row.get("event_id") and sha256_json(body) != row.get("event_hash"):
            raise ValueError(f"portable_memory_event_hash_invalid:{row.get('event_id')}")
    for ref in manifest.get("dependency_refs", []):
        _safe_relative(str(ref["path"]), label="portable_memory_dependency")
        if _secret_like(str(ref["path"])):
            raise ValueError("portable_memory_secret_dependency_forbidden")

    conflicts: list[str] = []
    missing: list[str] = []
    with StateStore(cfg.repo) as store:
        if (conflict := _existing_task_conflict(store, tasks[0])):
            conflicts.append(conflict)
        for row in sessions:
            existing = store.session(str(row["session_id"]))
            incoming = dict(row); incoming.pop("historical", None)
            if existing:
                if isinstance(existing.get("summary_json"), str):
                    existing = dict(existing); existing["summary_json"] = json.loads(existing["summary_json"])
                if _canonical_record(existing) != _canonical_record(incoming):
                    conflicts.append(f"portable_memory_session_conflict:{row['session_id']}")
            else:
                missing.append(f"session:{row['session_id']}")
        for row in notes:
            existing = store.note(str(row["note_id"]))
            if existing:
                incoming = dict(row); incoming.pop("dependency_snapshot", None)
                if _canonical_record(existing) != _canonical_record(incoming):
                    conflicts.append(f"portable_memory_note_conflict:{row['note_id']}")
            else:
                missing.append(f"note:{row['note_id']}")
        for row in jobs:
            existing = store.context_job(str(row["job_id"]))
            if existing:
                incoming = dict(row); incoming.pop("historical", None)
                if _canonical_record(existing) != _canonical_record(incoming):
                    conflicts.append(f"portable_memory_context_job_conflict:{row['job_id']}")
            else:
                missing.append(f"context_job:{row['job_id']}")
        for row in evidence:
            evidence_id = str(row["evidence_id"])
            existing = store.evidence_by_portable_id(evidence_id)
            if existing:
                existing_copy = dict(existing)
                existing_copy["metadata"] = existing_copy.pop("metadata", {})
                # Import adds explicit historical fields to metadata; compare the
                # stable source row rather than timestamps generated at import.
                comparable = {key: existing_copy.get(key) for key in ("session_id", "task_id", "name", "status", "path", "sha256", "revision", "source_identity_sha256")}
                source = {key: row.get(key) for key in comparable}
                if comparable != source:
                    conflicts.append(f"portable_memory_evidence_conflict:{evidence_id}")
            else:
                missing.append(f"evidence:{evidence_id}")
        for row in events:
            source_event_id = str(row.get("source_event_id") or row.get("event_id"))
            existing = store.conn.execute("SELECT * FROM memory_events WHERE source_event_id=?", (source_event_id,)).fetchone()
            local = store.conn.execute("SELECT event_hash FROM events WHERE event_id=?", (source_event_id,)).fetchone()
            if existing and str(existing["event_hash"]) != str(row.get("event_hash")):
                conflicts.append(f"portable_memory_event_conflict:{source_event_id}")
            if local and str(local["event_hash"]) != str(row.get("event_hash")):
                conflicts.append(f"portable_memory_event_id_conflict:{source_event_id}")
            if not existing and not local:
                missing.append(f"event:{source_event_id}")
        imported = store.portable_import(str(manifest["bundle_sha256"]))
        if imported and imported.get("task_id") != task_id:
            conflicts.append("portable_memory_bundle_task_conflict")

    payload_plan: list[dict[str, Any]] = []
    for entry in manifest.get("objects", []):
        if entry.get("kind") != "evidence":
            continue
        value = json.loads(data[entry["path"]].decode("utf-8"))
        payload_ref = value.get("payload_ref")
        if not payload_ref or not value.get("path"):
            continue
        payload_entry = next((row for row in manifest.get("payloads", []) if row.get("sha256") == payload_ref), None)
        if not payload_entry:
            raise ValueError(f"portable_memory_payload_ref_missing:{payload_ref}")
        rel = _safe_relative(str(value["path"]), label="portable_memory_evidence")
        _safe_relative(rel, label="portable_memory_evidence")
        if _secret_like(rel) or classify_path(cfg, rel) not in {"evidence", "generated", "qualification"}:
            raise ValueError(f"portable_memory_evidence_path_not_non_source:{rel}")
        dest, _ = ensure_repo_path(cfg.repo, Path(rel), label="portable_memory_destination")
        raw = data[payload_entry["path"]]
        if dest.exists():
            if dest.is_symlink() or not dest.is_file() or dest.read_bytes() != raw:
                conflicts.append(f"portable_memory_destination_conflict:{rel}")
        else:
            missing.append(f"payload:{rel}")
        payload_plan.append({"source_path": rel, "destination": str(dest), "raw": raw, "sha256": payload_ref})

    imported = None
    with StateStore(cfg.repo) as store:
        imported = store.portable_import(str(manifest["bundle_sha256"]))
    action = "CONFLICT" if conflicts else "IMPORT" if missing else "NOOP"
    if imported and action == "IMPORT":
        action = "REPAIR"
    return {
        "status": "FAIL" if conflicts else "PASS",
        "action": action,
        "dry_run": True,
        "bundle_sha256": manifest["bundle_sha256"],
        "task_id": task_id,
        "source_identity": manifest.get("source_identity"),
        "current_qualification": "NOT_EVALUATED",
        "historical_evidence": len(evidence),
        "objects": {kind: len(rows) for kind, rows in objects.items()},
        "planned_records": missing,
        "conflicts": conflicts,
        "dependency_recheck": _planned_dependencies(cfg, manifest),
        "manifest": manifest,
        "_data": data,
        "_objects": objects,
        "_payload_plan": payload_plan,
    }


def _insert_task(store: StateStore, row: dict[str, Any]) -> None:
    store.conn.execute(
        "INSERT INTO tasks(task_id,scope,status,current_phase,completed_json,blockers_json,next_action,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (row["task_id"], row["scope"], row["status"], row.get("current_phase"), canonical_json(row.get("completed", [])), canonical_json(row.get("blockers", [])), row.get("next_action", ""), row.get("updated_at") or utc_now()),
    )


def _insert_session(store: StateStore, row: dict[str, Any]) -> None:
    columns = ["session_id", "task_id", "scope", "status", "start_head", "start_fingerprint", "start_policy_fingerprint", "start_identity_sha256", "started_at", "finish_fingerprint", "finish_policy_fingerprint", "finish_identity_sha256", "end_head", "closed_at", "summary_json", "start_build_sha256"]
    values = [row.get(column) for column in columns]
    if isinstance(values[14], dict):
        values[14] = canonical_json(values[14])
    store.conn.execute(
        f"INSERT INTO sessions({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", values,
    )


def _insert_note(store: StateStore, row: dict[str, Any]) -> None:
    store.conn.execute(
        "INSERT INTO notes(note_id,task_id,session_id,text,depends_json,dependency_fingerprints_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (row["note_id"], row["task_id"], row.get("session_id"), row["text"], canonical_json(row.get("depends_on", [])), canonical_json(row.get("dependency_fingerprints", {})), row.get("created_at") or utc_now(), row.get("updated_at") or row.get("created_at") or utc_now()),
    )


def _insert_job(store: StateStore, row: dict[str, Any]) -> None:
    store.conn.execute(
        "INSERT INTO context_jobs(job_id,task_id,session_id,provider,status,packet_json,archive_refs_json,source_identity_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (row["job_id"], row["task_id"], row.get("session_id"), row["provider"], row.get("status", "ARCHIVED"), canonical_json(row.get("packet", {})), canonical_json(row.get("archive_refs", [])), row.get("source_identity_sha256"), row.get("created_at") or utc_now()),
    )


def import_memory(cfg: HarnessConfig, *, bundle: Path, dry_run: bool = False) -> dict[str, Any]:
    plan = plan_memory_import(cfg, bundle=bundle)
    if plan["status"] != "PASS" or dry_run or plan.get("action") == "NOOP":
        plan.pop("_data", None); plan.pop("_objects", None); plan.pop("_payload_plan", None)
        if plan.get("action") == "NOOP":
            plan["dry_run"] = False
        return plan
    manifest = plan["manifest"]
    data = plan["_data"]
    objects = plan["_objects"]
    payload_plan = plan["_payload_plan"]
    staging_root = Path(tempfile.mkdtemp(prefix="portable-memory-", dir=str(cfg.root)))
    staged: list[tuple[Path, Path, bytes]] = []
    created: list[Path] = []
    try:
        for index, item in enumerate(payload_plan):
            stage = staging_root / f"payload-{index}.bin"
            stage.write_bytes(item["raw"])
            staged.append((stage, Path(item["destination"]), item["raw"]))
        with StateStore(cfg.repo) as store:
            with store.transaction():
                task = objects["task"][0]
                if store.get_task(str(task["task_id"])) is None:
                    _insert_task(store, task)
                for row in objects.get("session", []):
                    if store.session(str(row["session_id"])) is None:
                        _insert_session(store, row)
                for row in objects.get("note", []):
                    if store.note(str(row["note_id"])) is None:
                        _insert_note(store, row)
                for row in objects.get("context_job", []):
                    if store.context_job(str(row["job_id"])) is None:
                        _insert_job(store, row)
                for row in objects.get("evidence", []):
                    evidence_id = str(row["evidence_id"])
                    if store.evidence_by_portable_id(evidence_id) is None:
                        metadata = dict(row.get("metadata") or {})
                        metadata.update({
                            "classification": "HISTORICAL",
                            "historical_status": row.get("historical_status", row.get("status")),
                            "current_qualification": "NOT_EVALUATED",
                            "portable_bundle_sha256": manifest["bundle_sha256"],
                        })
                        store.add_evidence(
                            session_id=str(row["session_id"]), task_id=str(row["task_id"]), name=str(row["name"]),
                            status=str(row["status"]), path=row.get("path"), sha256=row.get("sha256"), revision=row.get("revision"),
                            source_identity_sha256=row.get("source_identity_sha256"), metadata=metadata,
                            portable_id=evidence_id, recorded_at=row.get("recorded_at"),
                        )
                for row in [*objects.get("event", []), *objects.get("memory_event", [])]:
                    source_event_id = str(row.get("source_event_id") or row.get("event_id"))
                    existing = store.conn.execute("SELECT 1 FROM memory_events WHERE source_event_id=?", (source_event_id,)).fetchone()
                    if not existing:
                        store.record_memory_event(
                            source_event_id=source_event_id, task_id=str(row["task_id"]), session_id=row.get("session_id"),
                            event_type=str(row["event_type"]), ts=str(row["ts"]), payload=row.get("payload", {}),
                            prev_hash=row.get("prev_hash"), event_hash=str(row["event_hash"]), source_bundle_sha256=manifest["bundle_sha256"],
                        )
                for stage, destination, raw in staged:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists():
                        if destination.is_symlink() or not destination.is_file() or destination.read_bytes() != raw:
                            raise ValueError(f"portable_memory_destination_conflict:{destination}")
                    else:
                        os.replace(stage, destination)
                        created.append(destination)
                if store.portable_import(str(manifest["bundle_sha256"])) is None:
                    store.record_portable_import(
                        bundle_sha256=str(manifest["bundle_sha256"]), schema=SCHEMA,
                        task_id=str(manifest["task_id"]), source_identity=manifest["source_identity"],
                        object_count=int(manifest["object_count"]),
                    )
                store.event("MEMORY_IMPORTED", {
                    "bundle_sha256": manifest["bundle_sha256"], "task_id": manifest["task_id"],
                    "object_count": manifest["object_count"], "current_qualification": "NOT_EVALUATED",
                }, task_id=str(manifest["task_id"]))
        result = {key: value for key, value in plan.items() if not key.startswith("_")}
        written = []
        for _, path, _ in staged:
            if path in created and str(path) not in written:
                written.append(str(path))
        result.update({"status": "PASS", "action": "IMPORTED", "dry_run": False, "written": written})
        result["dependency_recheck"] = _planned_dependencies(cfg, manifest)
        return result
    except Exception:
        for path in reversed(created):
            try:
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def memory_context(cfg: HarnessConfig, *, task_id: str | None = None) -> dict[str, Any]:
    with StateStore(cfg.repo) as store:
        if task_id is None:
            return {"status": "PASS", "tasks": store.active_tasks(), "current_qualification": "NOT_EVALUATED"}
        task = store.get_task(task_id)
        if task is None:
            raise ValueError(f"unknown task: {task_id}")
        notes = []
        for row in store.notes_for_task(task_id):
            value = dict(row)
            value["dependency_status"] = [_dependency_status(cfg.repo, path, (row.get("dependency_fingerprints") or {}).get(path)) for path in row.get("depends_on", [])]
            notes.append(value)
        evidence = store.evidence_for_task(task_id)
        for row in evidence:
            row["classification"] = (row.get("metadata") or {}).get("classification", "CURRENT")
            row["current_qualification"] = (row.get("metadata") or {}).get("current_qualification", "NOT_EVALUATED")
        return {
            "status": "PASS",
            "task": task,
            "sessions": store.sessions_for_task(task_id),
            "notes": notes,
            "evidence": evidence,
            "context_jobs": store.context_jobs_for_task(task_id),
            "imported_events": store.memory_events_for_task(task_id),
            "current_qualification": "NOT_EVALUATED",
            "source_identity": _portable_identity(source_identity(cfg)),
        }


def add_note(cfg: HarnessConfig, *, task_id: str, text: str, session_id: str | None = None,
             depends_on: list[str] | None = None, note_id: str | None = None) -> dict[str, Any]:
    depends = [_safe_relative(str(value), label="portable_memory_dependency") for value in (depends_on or [])]
    fingerprints: dict[str, str | None] = {}
    for rel in depends:
        if _secret_like(rel):
            raise ValueError(f"portable_memory_secret_dependency_forbidden:{rel}")
        path = cfg.repo / rel
        fingerprints[rel] = sha256_file(path) if path.is_file() and not path.is_symlink() else None
    with StateStore(cfg.repo) as store:
        value = store.create_note(task_id=task_id, session_id=session_id, text=text, depends_on=depends, dependency_fingerprints=fingerprints, note_id=note_id)
        return store.note(value) or {"note_id": value}


def add_context_job(cfg: HarnessConfig, *, task_id: str, provider: str, packet: dict[str, Any],
                    session_id: str | None = None, archive_refs: list[str] | None = None,
                    job_id: str | None = None) -> dict[str, Any]:
    with StateStore(cfg.repo) as store:
        value = store.create_context_job(task_id=task_id, session_id=session_id, provider=provider, packet=packet, archive_refs=archive_refs, source_identity_sha256=source_identity(cfg)["identity_sha256"], job_id=job_id)
        return store.context_job(value) or {"job_id": value}
