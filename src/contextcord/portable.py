from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
import hashlib
import re
from typing import Any

from .config import HarnessConfig
from .contracts import validate
from .identity import compare_identity, source_identity
from .receipt import chain_order_newest_first, verify_receipt_chain, receipt_hash, verify_receipt
from .build_identity import build_identity
from .store import StateStore
from .util import ensure_repo_path
from .truth import classify_path
from .util import canonical_json, sha256_file, sha256_json

SCHEMA = "contextcord-portable-bundle-v1"


def _safe_archive_path(value: str) -> str:
    p = PurePosixPath(value)
    if (p.is_absolute() or ".." in p.parts or not p.parts or "\\" in value
        or PureWindowsPath(value).drive or ":" in value or p.as_posix() != value
        or any(part.endswith((".", " ")) or re.match(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", part) for part in p.parts)):
        raise ValueError(f"portable_bundle_unsafe_path:{value}")
    return p.as_posix()


def _portable_evidence_path(cfg: HarnessConfig, rel: str) -> None:
    kind = classify_path(cfg, rel)
    if kind not in {"evidence", "generated", "qualification"}:
        raise ValueError(f"portable_evidence_path_not_non_source:{rel}:{kind}")


def _manifest_hash(value: dict[str, Any]) -> str:
    return sha256_json(value, exclude_keys=("bundle_sha256",))


def export_bundle(cfg: HarnessConfig, *, output: Path) -> dict[str, Any]:
    chain = verify_receipt_chain(cfg)
    if chain["status"] != "PASS" or not chain.get("leaf"):
        raise ValueError("portable_bundle_requires_valid_nonempty_receipt_chain")
    rows = chain_order_newest_first(cfg)
    latest_path, latest = rows[0]
    files: dict[str, tuple[Path, str]] = {}
    for path, _ in rows:
        rel = path.relative_to(cfg.repo).as_posix(); files[rel] = (path, "receipt")
    for row in [item for _, receipt in rows for item in receipt.get("evidence_records", [])]:
        rel = row.get("path")
        if not rel:
            continue
        rel = _safe_archive_path(str(rel)); _portable_evidence_path(cfg, rel)
        path, _ = ensure_repo_path(cfg.repo, Path(rel), label="portable_evidence")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"portable_bundle_evidence_missing_or_symlink:{rel}")
        if sha256_file(path) != row.get("sha256"):
            raise ValueError(f"portable_bundle_evidence_hash_mismatch:{rel}")
        files[rel] = (path, "evidence")
    with StateStore(cfg.repo) as store:
        ok, bad = store.verify_event_chain()
        if not ok:
            raise ValueError(f"event_chain_invalid:{bad}")
        verdict = verify_receipt(cfg, store, latest)
        if verdict["status"] != "PASS":
            raise ValueError("portable_export_requires_valid_live_closeout:" + str(verdict["failures"]))
        events = store.recent_events(1_000_000)
    entries = [{"path": rel, "sha256": sha256_file(path), "bytes": path.stat().st_size, "kind": kind} for rel, (path, kind) in sorted(files.items())]
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "source_identity": latest["source_identity"],
        "receipt_leaf": chain["leaf"],
        "events": events,
        "files": entries,
    }
    manifest["bundle_sha256"] = _manifest_hash(manifest); validate("portable-bundle", manifest)
    output = output.resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        for rel, (path, _) in sorted(files.items()):
            z.write(path, arcname=rel)
    tmp.replace(output)
    return {"status": "PASS", "output": str(output), "receipt_leaf": chain["leaf"], "file_count": len(entries), "source_identity": latest["source_identity"], "manifest": manifest}


def inspect_bundle(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    path = path.resolve()
    with zipfile.ZipFile(path, "r") as z:
        names = z.namelist()
        if len(names) > 10000 or sum(i.file_size for i in z.infolist()) > 128 * 1024 * 1024:
            raise ValueError("portable_bundle_size_limit")
        if len({n.casefold() for n in names}) != len(names):
            raise ValueError("portable_bundle_duplicate_archive_path")
        for info in z.infolist():
            _safe_archive_path(info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("portable_bundle_symlink_member")
        if "manifest.json" not in names:
            raise ValueError("portable_bundle_manifest_missing")
        if len(names) != len(set(names)):
            raise ValueError("portable_bundle_duplicate_archive_path")
        payload = json.loads(z.read("manifest.json").decode("utf-8"))
        validate("portable-bundle", payload)
        if _manifest_hash(payload) != payload.get("bundle_sha256"):
            raise ValueError("portable_bundle_manifest_hash_mismatch")
        data: dict[str, bytes] = {}
        expected = {str(row["path"]): row for row in payload.get("files", [])}
        if len(expected) != len(payload.get("files", [])):
            raise ValueError("portable_bundle_duplicate_manifest_path")
        archive_payload = {name for name in names if name != "manifest.json"}
        if archive_payload != set(expected):
            raise ValueError("portable_bundle_file_set_mismatch")
        for rel, row in expected.items():
            safe = _safe_archive_path(rel)
            raw = z.read(safe)
            import hashlib
            if hashlib.sha256(raw).hexdigest() != row.get("sha256") or len(raw) != row.get("bytes"):
                raise ValueError(f"portable_bundle_file_hash_mismatch:{rel}")
            data[rel] = raw
    return payload, data


def verify_bundle(cfg: HarnessConfig, *, path: Path) -> dict[str, Any]:
    try:
        manifest, data = inspect_bundle(path)
        identity_errors = compare_identity(source_identity(cfg), manifest.get("source_identity", {}), sealed_memory=cfg.sealed_memory_on_verify)
        for rel, row in [(str(x["path"]), x) for x in manifest.get("files", [])]:
            if row.get("kind") == "evidence":
                _portable_evidence_path(cfg, rel)
            elif row.get("kind") == "receipt":
                if classify_path(cfg, rel) not in {"evidence", "generated", "qualification"}:
                    raise ValueError(f"portable_receipt_path_not_non_source:{rel}:{classify_path(cfg, rel)}")
        errors = list(identity_errors)
        receipts = {}
        for row in manifest['files']:
            if row['kind'] != 'receipt':
                continue
            receipt = json.loads(data[row['path']])
            validate('session-receipt', receipt)
            if receipt_hash(receipt) != receipt['receipt_hash']:
                raise ValueError('portable_receipt_hash_mismatch')
            receipts[receipt['receipt_hash']] = receipt
        leaf = manifest['receipt_leaf']
        if leaf not in receipts:
            raise ValueError('portable_receipt_leaf_missing')
        seen = set()
        cursor = leaf
        while cursor:
            if cursor in seen or cursor not in receipts:
                raise ValueError('portable_receipt_chain_invalid')
            seen.add(cursor)
            cursor = receipts[cursor].get('previous_receipt_hash')
        if len(seen) != len(receipts):
            raise ValueError('portable_receipt_chain_disconnected')
        receipt = receipts[leaf]
        if receipt['receipt_type'] != 'COMPLETE' or receipt['closeout_status'] != 'PASS' or receipt['integrity_status'] != 'PASS':
            errors.append('portable_closeout_not_complete_pass')
        if receipt.get('workflow_verdict', {}).get('status') != 'PASS':
            errors.append('portable_workflow_not_pass')
        if receipt.get('runtime', {}).get('required_by_scope') and receipt['runtime'].get('status') != 'PASS':
            errors.append('portable_required_runtime_not_pass')
        errors.extend(compare_identity(manifest['source_identity'], receipt['source_identity'], sealed_memory=True))
        if receipt.get('build_identity', {}).get('sha256') != build_identity()['sha256']:
            errors.append('portable_build_identity_mismatch')
        previous = None
        hashes = set()
        for event in manifest.get('events', []):
            body = {k: event.get(k) for k in ('event_id','session_id','task_id','event_type','ts','payload','prev_hash')}
            if body['prev_hash'] != previous or sha256_json(body) != event.get('event_hash'):
                raise ValueError('portable_event_chain_invalid')
            previous = event['event_hash']; hashes.add(previous)
        if not receipt.get('event_chain_head') or receipt['event_chain_head'] not in hashes:
            errors.append('portable_event_anchor_missing')
        if not receipt.get('evidence_records'):
            errors.append('portable_evidence_missing')
        for evidence in receipt.get('evidence_records', []):
            if evidence.get('status') != 'PASS':
                errors.append('portable_evidence_not_pass')
            raw = data.get(evidence.get('path'))
            if raw is None or hashlib.sha256(raw).hexdigest() != evidence.get('sha256'):
                errors.append('portable_evidence_hash_mismatch')
            sealed = evidence.get('metadata', {}).get('source_identity', {})
            for field, fingerprint in [('truth_sha256','truth_fingerprint'),('policy_sha256','policy_fingerprint'),('memory_sha256','memory_fingerprint')]:
                if sealed.get(field) != receipt['source_identity'].get(fingerprint, {}).get('sha256'):
                    errors.append('portable_evidence_identity_mismatch')
        return {"status": "PASS" if not errors else "FAIL", "errors": errors, "manifest": manifest, "file_count": len(data)}
    except Exception as exc:
        return {"status": "FAIL", "errors": [str(exc)], "manifest": None, "file_count": 0}


def import_bundle(cfg: HarnessConfig, *, path: Path) -> dict[str, Any]:
    verified = verify_bundle(cfg, path=path)
    if verified["status"] != "PASS":
        return verified
    manifest, data = inspect_bundle(path)
    if manifest != verified["manifest"]:
        raise ValueError("portable_bundle_changed_during_import")
    # Validate every destination before the first write; never overwrite different evidence.
    for rel, raw in data.items():
        dest, _ = ensure_repo_path(cfg.repo, Path(rel), label="portable_destination")
        if dest.exists() and (not dest.is_file() or dest.read_bytes() != raw):
            raise ValueError(f"portable_destination_conflict:{rel}")
    written: list[str] = []
    for row in manifest.get("files", []):
        rel = _safe_archive_path(str(row["path"])); kind = str(row["kind"])
        if kind == "evidence":
            _portable_evidence_path(cfg, rel)
        else:
            if classify_path(cfg, rel) not in {"evidence", "generated", "qualification"}:
                raise ValueError(f"portable_receipt_path_not_non_source:{rel}")
        dest = cfg.repo / rel
        # All portable paths are non-source, but still reject a symlinked parent.
        current = cfg.repo
        for part in Path(rel).parts[:-1]:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError(f"portable_bundle_destination_traverses_symlink:{current}")
        if dest.exists() and dest.is_symlink():
            raise ValueError(f"portable_bundle_destination_symlink:{rel}")
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data[rel]); written.append(rel)
    return {"status": "PASS", "written": written, "manifest": manifest}
