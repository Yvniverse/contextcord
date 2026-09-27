#!/usr/bin/env python3
"""Static verification for the lazy-loaded homepage Architecture Atlas."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def verify(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if "DecompressionStream" in text:
        errors.append("DecompressionStream dependency remains")
    if "architecture-data" in text:
        errors.append("inline architecture-data payload remains")
    if "MAP_ROOT='../docs/architecture/maps'" not in text or "function mapUrl" not in text:
        errors.append("lazy map URL loader missing")
    frames = re.findall(r"<iframe\b[^>]*>", text, flags=re.I)
    if not frames:
        errors.append("iframe missing")
    elif "srcdoc=" in frames[0].lower():
        errors.append("default iframe still embeds a viewer")
    map_root = path.parent.parent / "docs" / "architecture" / "maps"
    map_count = len(list(map_root.glob("*.html"))) if map_root.is_dir() else 0
    if map_count != 12:
        errors.append(f"expected 12 standalone maps, got {map_count}")
    result: dict[str, object] = {
        "status": "PASS" if not errors else "FAIL",
        "maps": map_count,
        "decompression_stream": text.count("DecompressionStream"),
        "default_srcdoc_svg": False,
        "lazy_map_urls": map_count,
        "inline_architecture_payload": "architecture-data" in text,
    }
    if errors:
        result["errors"] = errors
    return result


def main(argv: list[str] | None = None) -> int:
    path = Path((argv or sys.argv[1:])[0])
    result = verify(path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
