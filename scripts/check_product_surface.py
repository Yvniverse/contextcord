"""Derive the product surface from the runtime registries and cross-check docs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from contextcord.capabilities import PRODUCT_MODULES, RUNTIME_CAPABILITIES, SPECS
from contextcord.decision_fabric import QUESTION_SPECS
from contextcord.host_registry import BUILTIN_HOST_IDS
from contextcord.host_configs import generate_host_config
from contextcord.service import TOOLS, TOOL_CAPABILITIES


def derive() -> dict:
    declared = {"contextcord_" + name: ident for ident, spec in SPECS.items() if not spec.dev_only for name in spec.mcp_tools}
    if declared != TOOL_CAPABILITIES or set(TOOLS) != set(TOOL_CAPABILITIES):
        raise ValueError("capability_tool_surface_mismatch")
    for host in BUILTIN_HOST_IDS:
        generate_host_config(host)
    return {"schema": "contextcord-runtime-surface-v1",
            "product_modules": [name for _, name in PRODUCT_MODULES],
            "runtime_capabilities": list(RUNTIME_CAPABILITIES), "mcp_tools": list(TOOLS),
            "typed_decisions": [spec["id"] for spec in QUESTION_SPECS], "host_contracts": list(BUILTIN_HOST_IDS)}


def counts(surface: dict) -> dict:
    return {key: len(surface[key]) for key in ("product_modules", "runtime_capabilities", "mcp_tools", "typed_decisions", "host_contracts")}


def check_docs(root: Path, surface: dict) -> None:
    expected = counts(surface)
    markers = {
        "README.md": [f"{expected['runtime_capabilities']} runtime capabilities", f"{expected['mcp_tools']} MCP tools", f"{expected['typed_decisions']} typed decision categories"],
        "README_CN.md": [f"{expected['runtime_capabilities']} 项运行时能力", f"{expected['mcp_tools']} 个 MCP 工具", f"{expected['typed_decisions']} 类 typed decision"],
    }
    for name, values in markers.items():
        text = (root / name).read_text(encoding="utf-8")
        if any(value not in text for value in values) or any(name not in text for name in surface["product_modules"]):
            raise ValueError(f"document_surface_mismatch:{name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    surface = derive()
    path = root / "docs/runtime_surface.json"
    if args.write:
        path.write_text(json.dumps(surface, indent=2) + "\n", encoding="utf-8")
    elif json.loads(path.read_text(encoding="utf-8")) != surface:
        raise ValueError("generated_surface_mismatch")
    check_docs(root, surface)
    print(json.dumps({"status": "PASS", **counts(surface)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
