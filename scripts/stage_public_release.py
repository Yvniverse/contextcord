"""Stage the reviewed source inventory for a reproducible local release."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

ALLOWLIST = "support/public_release_allowlist.json"
CATEGORIES = {"source", "schema", "test", "example", "documentation", "evaluation", "packaging", "ci", "legal", "tooling", "integration"}


def safe_relative(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("inventory_path_must_be_string")
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or PureWindowsPath(value).drive
            or path.as_posix() != value or any(part in {".", "..", ".git"} for part in path.parts)
            or any(char in value for char in "\\:*?[]")
            or any(part.endswith((".", " ")) for part in path.parts)):
        raise ValueError("unsafe_inventory_path")
    return value


def is_link(path: Path) -> bool:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def checked_path(root: Path, relative: str) -> Path:
    safe_relative(relative)
    path = root
    for part in PurePosixPath(relative).parts:
        path = path / part
        if is_link(path):
            raise ValueError("inventory_link_forbidden")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("inventory_escape")
    return path


def load_allowlist(root: Path) -> dict[str, str]:
    data = json.loads(checked_path(root, ALLOWLIST).read_text(encoding="utf-8"))
    if data.get("schema") != "contextcord-public-allowlist-v1" or not isinstance(data.get("files"), list):
        raise ValueError("invalid_inventory_schema")
    inventory = {}
    folded = set()
    for row in data["files"]:
        if not isinstance(row, dict) or not {"path", "category"} <= set(row) or set(row) - {"path", "category", "source"}:
            raise ValueError("invalid_inventory_row")
        relative = safe_relative(row["path"])
        if relative.casefold() in folded or row["category"] not in CATEGORIES:
            raise ValueError("inventory_collision_or_category")
        checked_path(root, relative)
        if "source" in row:
            checked_path(root, row["source"])
        folded.add(relative.casefold())
        inventory[relative] = row["category"]
    if ALLOWLIST not in inventory:
        raise ValueError("inventory_must_include_itself")
    return dict(sorted(inventory.items()))


def public_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    data.decode("utf-8")
    if b"\x00" in data:
        raise ValueError("binary_payload_not_supported")
    return data.replace(b"\r\n", b"\n")


def content_manifest(root: Path, inventory: dict[str, str] | None = None) -> dict:
    inventory = inventory if inventory is not None else load_allowlist(root)
    rows = []
    for relative, category in sorted(inventory.items()):
        path = checked_path(root, relative)
        if not path.is_file():
            raise ValueError(f"missing_inventory_file:{relative}")
        data = path.read_bytes()
        rows.append({"path": relative, "category": category, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return {"schema": "contextcord-public-content-manifest-v1", "files": rows}


def stage(root: Path, destination: Path) -> Path:
    # Compute the staging-relative path before resolving the source root.
    # Windows runners can expose the same temporary directory through a short
    # path alias; resolving only one side makes lexical relative_to() reject
    # paths that refer to the same staging subtree.
    root_absolute = root.absolute()
    relative = destination.absolute().relative_to(root_absolute)
    safe_relative(relative.as_posix())
    root = root.resolve()
    # checked_path() still walks every destination component from the resolved
    # root and rejects symlinks/junctions/reparse points before any output.
    destination = checked_path(root, relative.as_posix())
    if not relative.parts or relative.parts[0] != ".work":
        raise ValueError("destination_must_be_in_staging_directory")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("destination_must_be_empty")
    inventory = load_allowlist(root)
    rules = json.loads(checked_path(root, ALLOWLIST).read_text(encoding="utf-8"))["files"]
    source_paths = {row["path"]: row.get("source", row["path"]) for row in rules}
    payloads = {}
    for relative in inventory:
        source = checked_path(root, source_paths[relative])
        if not source.is_file():
            raise ValueError(f"missing_inventory_file:{relative}")
        payloads[relative] = public_bytes(source)
    # Validate the bytes before creating any output. New source files are
    # absent from this inventory until a maintainer explicitly adds them.
    from check_public_release import scan_payloads
    errors = scan_payloads(payloads)
    if errors:
        raise ValueError("release_content_rejected:" + ",".join(errors))
    destination.mkdir(parents=True, exist_ok=True)
    for relative, data in payloads.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--destination", type=Path, default=Path(".work/public-release/candidate"))
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    destination = args.destination if args.destination.is_absolute() else args.root / args.destination
    output = stage(args.root, destination)
    manifest = content_manifest(output)
    if args.manifest:
        manifest_path = args.manifest.resolve()
        if manifest_path.is_relative_to(output):
            raise ValueError("manifest_is_a_sidecar")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "public_files": len(manifest["files"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
