"""Verify built archives and an isolated wheel installation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile

from stage_public_release import load_allowlist, safe_relative
from check_public_release import scan_payloads


def verify_archives(wheel: Path, sdist: Path, source: Path) -> None:
    inventory = load_allowlist(source)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(name.casefold() for name in names)):
            raise ValueError("wheel_duplicate_member")
        payloads = {safe_relative(name): archive.read(name) for name in names}
        package = {name[4:] for name in inventory if name.startswith("src/contextcord/")}
        metadata = wheel.name.split("-py3-")[0] + ".dist-info/"
        generated = {metadata + name for name in ("METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD")}
        licenses = {metadata + "licenses/" + name for name in ("LICENSE", "NOTICE", "docs/architecture/ARCHIFY_LICENSE.txt", "docs/legal/CONTEXTCORD_PREVIOUS_MIT.txt")}
        if set(payloads) != package | generated | licenses:
            raise ValueError("wheel_inventory_mismatch")
        for name in package:
            if payloads[name] != (source / "src" / name).read_bytes():
                raise ValueError("wheel_source_changed")
        for name in licenses:
            if payloads[name] != (source / name[len(metadata + "licenses/"):]).read_bytes():
                raise ValueError("wheel_license_changed")
        if scan_payloads(payloads):
            raise ValueError("wheel_content_boundary_failure")
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        if any(not (item.isdir() or item.isfile()) for item in members):
            raise ValueError("sdist_nonregular_member")
        prefixes = {item.name.split("/", 1)[0] for item in members}
        if len(prefixes) != 1:
            raise ValueError("sdist_root_mismatch")
        payloads = {}
        for item in members:
            if item.isfile():
                name = safe_relative(item.name.split("/", 1)[1])
                if name.casefold() in {key.casefold() for key in payloads}:
                    raise ValueError("sdist_duplicate_member")
                payloads[name] = archive.extractfile(item).read()
        generated = {"PKG-INFO", "setup.cfg"} | {"src/contextcord.egg-info/" + name for name in ("PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt", "requires.txt", "top_level.txt")}
        if set(payloads) != set(inventory) | generated:
            raise ValueError("sdist_inventory_mismatch")
        for name in inventory:
            if payloads[name] != (source / name).read_bytes():
                raise ValueError("sdist_source_changed")
        if scan_payloads(payloads):
            raise ValueError("sdist_content_boundary_failure")


def check(dist: Path) -> dict:
    wheels = list(dist.glob("contextcord-*.whl"))
    sdists = list(dist.glob("contextcord-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("exactly_one_wheel_and_sdist_required")
    source = Path(__file__).resolve().parents[1]
    verify_archives(wheels[0], sdists[0], source)
    with tempfile.TemporaryDirectory(prefix="contextcord-install-") as directory:
        root = Path(directory)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", str(wheels[0].resolve())], env=env, cwd=root, capture_output=True, check=True)
        probe = '''import json, pathlib, contextcord
from contextcord.adapter_lab import discover_manifests
from contextcord.contracts import SCHEMAS, schema
from contextcord.host_registry import load_registry
from jsonschema import Draft202012Validator
assert 'site-packages' in pathlib.Path(contextcord.__file__).parts
assert all(row['status']=='PASS' for row in discover_manifests())
assert len(discover_manifests()) >= 5
for name in SCHEMAS: Draft202012Validator.check_schema(schema(name))
assert not any(row['qualification']['qualified'] for row in load_registry('.') ['built_in_hosts'])
print(json.dumps({'status':'PASS','schemas':len(SCHEMAS)}))
'''
        subprocess.run([str(python), "-c", probe], env=env, cwd=root, capture_output=True, check=True)
        subprocess.run([str(python), "-m", "contextcord", "--help"], env=env, cwd=root, capture_output=True, check=True)
        smoke_path = Path(__file__).with_name("mcp_smoke.py")
        subprocess.run([str(python), str(smoke_path)], env=env, cwd=root, capture_output=True, timeout=60, check=True)
    return {"status": "PASS", "wheel": "PASS", "sdist": "PASS", "isolated_install": "PASS", "installed_mcp": "PASS"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    print(json.dumps(check(parser.parse_args().dist), indent=2))
