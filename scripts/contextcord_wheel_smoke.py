"""Smoke-test the built ContextCord wheel without network or installation side effects."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args(argv)
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise SystemExit("wheel_missing")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        required = {
            "contextcord/__init__.py",
            "contextcord/host_registry.py",
            "contextcord/schemas/host-evidence-registry.schema.json",
        }
        required_license = next((name for name in names if name.endswith(".dist-info/licenses/LICENSE")), None)
        missing = sorted(required - names)
        if required_license is None:
            missing.append("dist-info/licenses/LICENSE")
        if missing:
            print(json.dumps({"status": "FAIL", "missing": missing}, ensure_ascii=False))
            return 1
        with tempfile.TemporaryDirectory(prefix="contextcord-wheel-smoke-") as temp:
            archive.extractall(temp)
            env = dict(__import__("os").environ)
            env["PYTHONPATH"] = str(Path(temp))
            probe = subprocess.run(
                [sys.executable, "-c", "from contextcord.version import RELEASE_VERSION; from contextcord.host_registry import BUILTIN_HOST_IDS; print(RELEASE_VERSION); print(','.join(BUILTIN_HOST_IDS))"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
    result = {
            "status": "PASS" if probe.returncode == 0 and probe.stdout.splitlines()[:1] == ["0.6.2a1"] else "FAIL",
        "wheel": str(wheel),
        "returncode": probe.returncode,
        "stdout": probe.stdout.strip(),
        "stderr": probe.stderr.strip(),
        "required_license": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
