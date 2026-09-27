#!/usr/bin/env python3
"""Read-only Architecture Truth drift gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from architecture_sync import current_architecture_status  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--release", action="store_true", help="fail on unresolved architecture drift")
    parser.add_argument("--public-staging", action="store_true", help="alias for the strict release gate")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    value = current_architecture_status(Path(args.repo).resolve())
    strict = bool(args.release or args.public_staging)
    value["gate"] = "FAIL" if strict and value["status"] != "SYNCED" else "PASS"
    value["strict"] = strict
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if value["gate"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
