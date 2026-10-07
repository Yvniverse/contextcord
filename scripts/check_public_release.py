"""Check a source tree against its explicit release inventory and boundaries."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


LOCAL_PATH = re.compile(r"\b[A-Za-z]:[\\/]|(?<![\w:])/(?:home|Users|workspace|tmp)/[A-Za-z0-9_.-]|/mnt/(?:data|[A-Za-z])/[A-Za-z0-9_.-]", re.I)
SECRET_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"\bsk-[A-Za-z0-9_-]{12,}\b", r"\bghp_[A-Za-z0-9]{20,}\b",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", r"\bAKIA[0-9A-Z]{16}\b",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
))
FORBIDDEN_ROOTS = {"research", "web", "reference", "Source_code", "artifacts", "benchmark", ".work", ".contextcord", ".aws", ".codex", ".ssh"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".zip", ".bundle", ".7z", ".rar", ".pem", ".key", ".pyc", ".whl", ".gz"}
REVIEW_ONLY_FILES = {"REVIEW_RELEASE_REPORT.md", "REVIEW_RELEASE_CHECKS.json", "REVIEW_CONTENT_MANIFEST.json", "PRIVATE_CHANGE_SUMMARY.md", "PUBLIC_RELEASE_REPORT.md", "PUBLIC_RELEASE_CHECKS.json", "PUBLIC_CONTENT_MANIFEST.json"}


def scan_payloads(payloads: dict[str, bytes]) -> list[str]:
    errors = []
    for relative, data in sorted(payloads.items()):
        path = Path(relative)
        if (path.parts[0] in FORBIDDEN_ROOTS or ".git" in path.parts or path.name in REVIEW_ONLY_FILES
                or any(part.casefold().startswith(".env") for part in path.parts)
                or path.suffix.casefold() in FORBIDDEN_SUFFIXES):
            errors.append(f"forbidden_payload:{relative}")
        try:
            body = data.decode("utf-8")
        except UnicodeError:
            errors.append(f"non_text_payload:{relative}")
            continue
        if LOCAL_PATH.search(body):
            errors.append(f"local_path:{relative}")
        if any(pattern.search(body) for pattern in SECRET_PATTERNS):
            errors.append(f"credential_shape:{relative}")
    return errors


def check(root: Path, *, manifest: dict | None = None, history: bool = False) -> dict:
    from stage_public_release import load_allowlist, is_link, content_manifest
    root = root.resolve()
    errors = []
    payloads = {}
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in tuple(folders) + tuple(files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if is_link(path):
                errors.append(f"link_forbidden:{relative}")
                if name in folders:
                    folders.remove(name)
            elif relative == ".git":
                if name in folders:
                    folders.remove(name)
                continue
            elif name in files:
                payloads[relative] = path.read_bytes()
    inventory = load_allowlist(root)
    errors += [f"unexpected:{name}" for name in sorted(set(payloads) - set(inventory))]
    errors += [f"missing:{name}" for name in sorted(set(inventory) - set(payloads))]
    errors += scan_payloads(payloads)
    if manifest is not None:
        if manifest != content_manifest(root, inventory):
            errors.append("content_manifest_mismatch")
    if history:
        def git(*args):
            return subprocess.check_output(["git", "-C", str(root), *args], text=True, encoding="utf-8").strip()
        if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
            raise ValueError("history_must_belong_to_candidate")
        if len(git("rev-list", "--max-parents=0", "HEAD").splitlines()) != 1 or git("remote"):
            errors.append("history_root_or_remote")
        for commit in git("rev-list", "HEAD").splitlines():
            message = git("show", "-s", "--format=%B", commit)
            if LOCAL_PATH.search(message) or any(pattern.search(message) for pattern in SECRET_PATTERNS):
                errors.append("history_message_rejected")
            names = git("ls-tree", "-r", "--name-only", commit).splitlines()
            objects = {name: subprocess.check_output(["git", "-C", str(root), "show", f"{commit}:{name}"]) for name in names}
            errors += [f"history:{item}" for item in scan_payloads(objects)]
        if git("status", "--porcelain"):
            errors.append("candidate_worktree_dirty")
    return {"status": "PASS" if not errors else "FAIL", "public_files": len(payloads), "errors": sorted(set(errors))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = check(args.root, manifest=json.loads(args.manifest.read_text()) if args.manifest else None, history=args.history)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        result = {"status": "FAIL", "errors": [type(exc).__name__]}
    print(json.dumps(result, indent=2))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
