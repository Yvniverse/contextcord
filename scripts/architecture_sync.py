#!/usr/bin/env python3
"""Architecture Truth inventory, Archify delivery, and portable web sync.

The repository's source package is the only architecture authority.  This
script deliberately keeps the generated inventory and active atlas outputs
separate from the normal ContextCord state database; closeout invokes the
same entry point for its architecture phase.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ACTIVE_VIEWS = ("system", "router", "workflow", "sequence", "dataflow", "lifecycle")
VIEW_TYPES = {
    "system": "architecture",
    "router": "architecture",
    "workflow": "workflow",
    "sequence": "sequence",
    "dataflow": "dataflow",
    "lifecycle": "lifecycle",
}
LANGUAGES = ("en", "zh")
ARCHIFY_VERSION = "2.16"
GROUPS = (
    "Continuity Core",
    "Context Engine",
    "Trust & Freshness",
    "Decision Fabric",
    "Adaptive Router",
    "Model Intelligence",
    "Capability Registry",
    "MCP / Host Gateway",
    "Evidence & Runtime",
)

# A module belongs to one logical responsibility group.  These are labels,
# not deployment claims.  The fallback deliberately remains Evidence & Runtime
# so a newly added module is never silently omitted from the inventory.
MODULE_GROUPS = {
    "context": "Continuity Core",
    "handoff": "Continuity Core",
    "memory": "Continuity Core",
    "store": "Continuity Core",
    "bm25": "Context Engine",
    "build_identity": "Trust & Freshness",
    "contracts": "Trust & Freshness",
    "evidence": "Trust & Freshness",
    "fingerprint": "Trust & Freshness",
    "identity": "Trust & Freshness",
    "portable": "Trust & Freshness",
    "qualification": "Trust & Freshness",
    "receipt": "Trust & Freshness",
    "truth": "Trust & Freshness",
    "decision": "Decision Fabric",
    "decision_fabric": "Decision Fabric",
    "jev_dotenv": "Decision Fabric",
    "jev_provider": "Decision Fabric",
    "calibration": "Adaptive Router",
    "execution_routes": "Adaptive Router",
    "router": "Adaptive Router",
    "model_intelligence": "Model Intelligence",
    "providers": "Model Intelligence",
    "capabilities": "Capability Registry",
    "config": "Capability Registry",
    "profiles": "Capability Registry",
    "__init__": "MCP / Host Gateway",
    "__main__": "MCP / Host Gateway",
    "adapter_lab": "MCP / Host Gateway",
    "adapters": "MCP / Host Gateway",
    "cli": "MCP / Host Gateway",
    "entrypoint": "MCP / Host Gateway",
    "host_configs": "MCP / Host Gateway",
    "host_registry": "MCP / Host Gateway",
    "hostbridge": "MCP / Host Gateway",
    "mcp": "MCP / Host Gateway",
    "service": "MCP / Host Gateway",
    "dualrun": "Evidence & Runtime",
    "extensions": "Evidence & Runtime",
    "gitops": "Evidence & Runtime",
    "migration": "Evidence & Runtime",
    "policy": "Evidence & Runtime",
    "process": "Evidence & Runtime",
    "release_identity": "Evidence & Runtime",
    "replay": "Evidence & Runtime",
    "runner": "Evidence & Runtime",
    "runtime": "Evidence & Runtime",
    "util": "Evidence & Runtime",
    "workflow": "Evidence & Runtime",
    "workflow_checks": "Evidence & Runtime",
    "version": "Evidence & Runtime",
}

VIEW_TITLES = {
    "system": {"zh": "当前系统架构", "en": "Current system architecture"},
    "router": {"zh": "Adaptive Router v3", "en": "Adaptive Router v3"},
    "workflow": {"zh": "接续与执行工作流", "en": "Continuity and execution workflow"},
    "sequence": {"zh": "路由执行时序", "en": "Routing execution sequence"},
    "dataflow": {"zh": "数据流与证据边界", "en": "Data flow and evidence custody"},
    "lifecycle": {"zh": "任务、路由与交接生命周期", "en": "Task, routing and handoff lifecycle"},
}

README = """# ContextCord Architecture Atlas

This directory is the source-backed Architecture Truth baseline for
ContextCord 0.6.2a1. It contains six current views in two languages (12
standalone Archify maps), their typed specifications, delivery receipts, and
the generated inventory of `src/contextcord/*.py`.

The nine logical responsibility groups are labels over the current Python
modules, not independent deployment services. The active atlas intentionally
contains only `system`, `router`, `workflow`, `sequence`, `dataflow`, and
`lifecycle`; older proposal views remain historical evidence outside the
active selector.

The homepage keeps only lightweight diagram metadata and lazy-loads the
selected standalone viewer URL. The complete interactive Archify viewers
remain under `maps/`; no full viewer payload is embedded in the homepage.

## Status

- Source package: `src/contextcord/`
- Source inventory: `source-inventory.json`
- Active specs/maps: 12 / 12
- Fingerprint: `fingerprint.json` (v3)
- Public publication: `NOT_DONE`
"""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _description(node: ast.AST) -> str:
    return (ast.get_docstring(node, clean=True) or "").strip()


def _symbol_rows(tree: ast.Module) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(body: Iterable[ast.AST], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{node.name}"
                row: dict[str, Any] = {
                    "name": name,
                    "kind": type(node).__name__,
                    "line": int(getattr(node, "lineno", 0)),
                    "end_line": int(getattr(node, "end_lineno", getattr(node, "lineno", 0))),
                    "description": _description(node),
                }
                rows.append(row)
                if isinstance(node, ast.ClassDef):
                    visit(node.body, name + ".")

    visit(tree.body)
    return rows


def _local_imports(tree: ast.Module) -> list[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "contextcord" or alias.name.startswith("contextcord."):
                    found.add(alias.name.rsplit(".", 1)[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    found.add(node.module.split(".", 1)[0])
                else:
                    found.update(alias.name for alias in node.names)
            elif node.module and (node.module == "contextcord" or node.module.startswith("contextcord.")):
                found.add(node.module.rsplit(".", 1)[-1])
    return sorted(found)


def _module_group(module: str) -> str:
    return MODULE_GROUPS.get(module, "Evidence & Runtime")


def scan_source_inventory(repo: Path) -> dict[str, Any]:
    """Scan only the canonical top-level Python source package."""
    repo = _repo_path(repo)
    source_root = repo / "src" / "contextcord"
    modules: list[dict[str, Any]] = []
    if source_root.is_dir():
        paths = sorted(source_root.glob("*.py"), key=lambda path: path.name)
    else:
        paths = []
    for path in paths:
        module = path.stem
        raw = path.read_bytes()
        try:
            tree = ast.parse(raw.decode("utf-8"), filename=str(path))
        except SyntaxError as exc:
            raise ValueError(f"architecture_source_syntax_error:{path}:{exc.lineno}") from exc
        modules.append(
            {
                "path": path.relative_to(repo).as_posix(),
                "module": module,
                "group": _module_group(module),
                "sha256": _sha256_bytes(raw),
                "symbols": _symbol_rows(tree),
                "local_imports": _local_imports(tree),
            }
        )
    module_digest_input = [
        {"path": row["path"], "module": row["module"], "group": row["group"], "sha256": row["sha256"]}
        for row in modules
    ]
    groups = {group: [row["module"] for row in modules if row["group"] == group] for group in GROUPS}
    base: dict[str, Any] = {
        "schema": "contextcord-source-inventory-v3",
        "scope": "top-level src/contextcord/*.py; static source inventory, not a runtime call trace",
        "source_package": "src/contextcord",
        "module_count": len(modules),
        "logical_groups": list(GROUPS),
        "groups": groups,
        "source_modules_sha256": _sha256_bytes(_canonical(module_digest_input).encode("utf-8")),
        "modules": modules,
    }
    base["source_inventory_sha256"] = _sha256_bytes(_canonical(base).encode("utf-8"))
    return base


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_inventory(repo: Path, inventory: dict[str, Any]) -> Path:
    path = repo / "docs" / "architecture" / "source-inventory.json"
    _write_json(path, inventory)
    return path


def write_source_map(repo: Path, inventory: dict[str, Any]) -> Path:
    lines = [
        "# Source map / 源码目录",
        "",
        f"{inventory['module_count']} Python modules scanned from `src/contextcord/*.py`.",
        "This is a static inventory, not a runtime call trace.",
        "",
        f"Source inventory SHA-256: `{inventory['source_inventory_sha256']}`",
        "",
        "Architecture labels describe logical responsibility groups, not separate deployed services.",
        "",
        "| Logical group | File | Top-level symbols | Local imports |",
        "|---|---|---|---|",
    ]
    for group in GROUPS:
        for row in inventory["modules"]:
            if row["group"] != group:
                continue
            symbols = ", ".join(f"`{item['name']}`" for item in row["symbols"] if item["name"].split(".")[-1])
            imports = ", ".join(f"`{item}`" for item in row["local_imports"])
            lines.append(f"| {group} | `{row['path']}` | {symbols} | {imports} |")
    lines += [
        "",
        "## Active architecture views",
        "",
        "The active atlas contains only six current views in English and Chinese:",
        "`system`, `router`, `workflow`, `sequence`, `dataflow`, and `lifecycle`.",
        "",
        "Historical proposal artifacts are not active and are never used as current source truth.",
        "",
    ]
    path = repo / "docs" / "architecture" / "SOURCE_MAP.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def active_index() -> dict[str, Any]:
    views = []
    for view in ACTIVE_VIEWS:
        views.append(
            {
                "id": view,
                "title": VIEW_TITLES[view],
                "type": VIEW_TYPES[view],
                "status": "source-backed",
                "files": {"zh": f"maps/{view}.zh.html", "en": f"maps/{view}.en.html"},
            }
        )
    return {"views": views, "view_count": len(views), "artifacts": len(views) * 2}


def write_active_index(repo: Path) -> Path:
    path = repo / "docs" / "architecture" / "atlas-index.json"
    _write_json(path, active_index())
    return path


def _copy_kit_assets(repo: Path, kit_dir: Path) -> list[str]:
    copied: list[str] = []
    for relative in ("architecture/specs", "architecture/maps"):
        source_root = kit_dir / relative
        target_root = repo / "docs" / relative
        target_root.mkdir(parents=True, exist_ok=True)
        for view in ACTIVE_VIEWS:
            for language in LANGUAGES:
                name = f"{view}.{language}.json" if relative.endswith("specs") else f"{view}.{language}.html"
                source = source_root / name
                if not source.is_file():
                    raise FileNotFoundError(f"kit_active_asset_missing:{source}")
                shutil.copy2(source, target_root / name)
                copied.append((Path("docs") / relative / name).as_posix())
    return copied


def _archify_candidates(repo: Path, explicit: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_value = os.environ.get("CONTEXTCORD_ARCHIFY_BIN")
    if env_value:
        candidates.append(Path(env_value))
    candidates += [
        repo / ".agents" / "skills" / "archify" / "bin" / "archify.mjs",
        repo / ".contextcord" / "archify" / "archify" / "bin" / "archify.mjs",
    ]
    candidates += sorted(repo.glob(".contextcord/archify-*/archify/bin/archify.mjs"), reverse=True)
    return [candidate.resolve() for candidate in candidates if candidate.is_file()]


def _archify_run(binary: Path, args: list[str]) -> tuple[int, str, str]:
    node = os.environ.get("NODE_BINARY", "node")
    try:
        result = subprocess.run([node, str(binary), *args], capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        return 127, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def _json_from_output(text: str) -> dict[str, Any]:
    for line in reversed([line.strip() for line in text.splitlines() if line.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {"raw": text[-4000:]}


def render_active_maps(repo: Path, binary: Path) -> tuple[str, list[dict[str, Any]]]:
    """Validate and deliver all active specs with Archify, preserving receipts."""
    spec_root = repo / "docs" / "architecture" / "specs"
    map_root = repo / "docs" / "architecture" / "maps"
    receipt_root = repo / "docs" / "architecture" / "receipts"
    receipt_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    overall = "SYNCED"
    for view in ACTIVE_VIEWS:
        kind = VIEW_TYPES[view]
        for language in LANGUAGES:
            spec = spec_root / f"{view}.{language}.json"
            output = map_root / f"{view}.{language}.html"
            validate_rc, validate_out, validate_err = _archify_run(
                binary, ["validate", kind, str(spec), "--quality", "showcase", "--json"]
            )
            validation = _json_from_output(validate_out or validate_err)
            deliver: dict[str, Any] = {}
            deliver_rc = validate_rc
            deliver_out = ""
            deliver_err = ""
            if validate_rc == 0:
                deliver_rc, deliver_out, deliver_err = _archify_run(
                    binary,
                    ["deliver", kind, str(spec), str(output), "--quality", "showcase", "--json"],
                )
                deliver = _json_from_output(deliver_out or deliver_err)
            ok = validate_rc == 0 and deliver_rc == 0 and output.is_file() and "<svg" in output.read_text(encoding="utf-8")
            if not ok:
                overall = "VALIDATION_FAILED"
            receipt = {
                "schema": "contextcord-architecture-delivery-receipt-v1",
                "view": view,
                "language": language,
                "type": kind,
                "status": "PASS" if ok else "FAIL",
                "spec": spec.relative_to(repo).as_posix(),
                "map": output.relative_to(repo).as_posix(),
                "spec_sha256": _sha256_file(spec) if spec.is_file() else None,
                "map_sha256": _sha256_file(output) if output.is_file() else None,
                "validation": validation,
                "delivery": deliver,
                "stderr": (validate_err + deliver_err)[-2000:] or None,
            }
            receipt_name = f"architecture-sync-{view}.{language}.json"
            _write_json(receipt_root / receipt_name, receipt)
            results.append(receipt)
    return overall, results


def _map_payloads(repo: Path) -> dict[str, str]:
    payloads: dict[str, str] = {}
    for view in ACTIVE_VIEWS:
        for language in ("zh", "en"):
            path = repo / "docs" / "architecture" / "maps" / f"{view}.{language}.html"
            if not path.is_file():
                raise FileNotFoundError(f"active_map_missing:{path}")
            payloads[f"{view}.{language}"] = base64.b64encode(path.read_bytes()).decode("ascii")
    return payloads


def _replace_script(html_text: str, script_id: str, body: str) -> str:
    pattern = rf'(<script\s+id="{re.escape(script_id)}"\s+type="application/json">)[\s\S]*?(</script>)'
    updated, count = re.subn(pattern, lambda match: match.group(1) + body + match.group(2), html_text, count=1)
    if count != 1:
        raise ValueError(f"web_script_missing:{script_id}")
    return updated


def _extract_scripts(html_text: str) -> list[tuple[str, str]]:
    return [(match.group(0), match.group(1)) for match in re.finditer(r"<script\b[^>]*>([\s\S]*?)</script>", html_text, re.I)]


def update_web(repo: Path, inventory: dict[str, Any], *, sample_html: Path | None = None) -> dict[str, Any]:
    """Refresh metadata while preserving the production lazy-load contract."""
    path = repo / "web" / "index.html"
    if not path.is_file():
        return {"status": "SKIPPED", "reason": "web_index_missing"}
    current = path.read_text(encoding="utf-8")
    # The canonical source inventory remains a repository artifact.  Home only
    # needs a public path index for its existing source-list UX; descriptions,
    # imports and compatibility names stay out of the browser payload.
    public_inventory = {
        "schema": "contextcord-public-source-index-v1",
        "scope": "top-level src/contextcord/*.py paths only",
        "module_count": int(inventory.get("module_count", 0)),
        "modules": [
            {"path": str(row.get("path", ""))}
            for row in inventory.get("modules", [])
            if isinstance(row, Mapping) and str(row.get("path", "")).startswith("src/contextcord/")
        ],
    }
    inventory_json = json.dumps(public_inventory, ensure_ascii=False, separators=(",", ":"))
    updated, inventory_count = re.subn(
        r'<script\s+id="source-inventory-data"\s+type="application/json">[\s\S]*?</script>\s*',
        f'<script id="source-inventory-data" type="application/json">{inventory_json}</script>\n',
        current,
        count=1,
        flags=re.I,
    )
    if inventory_count == 0:
        marker = "</head>"
        if marker not in updated:
            raise ValueError("web_head_missing")
        updated = updated.replace(
            marker,
            f'<script id="source-inventory-data" type="application/json">{inventory_json}</script>{marker}',
            1,
        )
    updated, _ = re.subn(
        r'<script\s+id="architecture-data"\s+type="application/json">[\s\S]*?</script>',
        '<!-- Full Archify viewers are loaded from docs/architecture/maps on demand. -->',
        updated,
        count=1,
        flags=re.I,
    )
    updated, count = re.subn(
        r'(<iframe\s+id="arch-frame"[^>]*?)\s+srcdoc="[\s\S]*?"',
        r'\1',
        updated,
        count=1,
        flags=re.I,
    )
    if not re.search(r'<iframe\s+id="arch-frame"[^>]*>', updated, flags=re.I):
        raise ValueError("web_iframe_missing")
    if "MAP_ROOT='../docs/architecture/maps'" not in updated or "function mapUrl" not in updated:
        raise ValueError("web_lazy_map_loader_missing")
    updated, count = re.subn(r'(<div\s+class=")frame-loading(?:\s+hidden)?("\s+id="frame-loading")', r'\1frame-loading hidden\2', updated, count=1, flags=re.I)
    if count != 1:
        raise ValueError("web_loading_overlay_missing")
    path.write_text(updated, encoding="utf-8", newline="\n")
    return {
        "status": "SYNCED",
        "path": path.relative_to(repo).as_posix(),
        "architecture_keys": len(_map_payloads(repo)),
        "decompression_stream": updated.count("DecompressionStream"),
        "default_srcdoc_svg": False,
        "lazy_map_urls": len(_map_payloads(repo)),
        "inline_architecture_payload": False,
    }


def _fingerprint(repo: Path, inventory: dict[str, Any], *, status: str, archify_version: str | None) -> dict[str, Any]:
    spec_count = sum(1 for view in ACTIVE_VIEWS for language in LANGUAGES if (repo / "docs" / "architecture" / "specs" / f"{view}.{language}.json").is_file())
    map_count = sum(1 for view in ACTIVE_VIEWS for language in LANGUAGES if (repo / "docs" / "architecture" / "maps" / f"{view}.{language}.html").is_file())
    return {
        "schema": "contextcord-architecture-fingerprint-v3",
        "source_package": "src/contextcord",
        "source_inventory_sha256": inventory["source_inventory_sha256"],
        "module_count": inventory["module_count"],
        "active_specs": spec_count,
        "active_maps": map_count,
        "generated_from_commit": _git(repo, "rev-parse", "HEAD"),
        "archify_version": archify_version,
        "status": status,
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def current_architecture_status(repo: Path) -> dict[str, Any]:
    repo = _repo_path(repo)
    inventory = scan_source_inventory(repo)
    fingerprint_path = repo / "docs" / "architecture" / "fingerprint.json"
    recorded = _load_json(fingerprint_path, {})
    index = _load_json(repo / "docs" / "architecture" / "atlas-index.json", {})
    current_ids = [str(row.get("id")) for row in index.get("views", [])] if isinstance(index, dict) else []
    expected_ids = list(ACTIVE_VIEWS)
    source_drift = recorded.get("source_inventory_sha256") != inventory["source_inventory_sha256"]
    shape_drift = (
        recorded.get("schema") != "contextcord-architecture-fingerprint-v3"
        or recorded.get("module_count") != inventory["module_count"]
        or recorded.get("active_specs") != 12
        or recorded.get("active_maps") != 12
        or recorded.get("status") != "SYNCED"
        or current_ids != expected_ids
    )
    stale_ids = [value for value in ("routing-proposed", "closeout-proposed") if value in current_ids]
    return {
        "status": "DRIFT" if source_drift or shape_drift or stale_ids else "SYNCED",
        "source_drift": source_drift,
        "shape_drift": shape_drift,
        "stale_active_views": stale_ids,
        "current": inventory,
        "recorded": recorded,
        "active_view_ids": current_ids,
        "expected_view_ids": expected_ids,
    }


def stamp_fingerprint(repo: Path) -> dict[str, Any]:
    """Bind an already-synced fingerprint to the commit that contains it."""
    repo = _repo_path(repo)
    status = current_architecture_status(repo)
    if status["status"] != "SYNCED":
        return {
            "status": "DRIFT",
            "reason": "architecture_must_be_synced_before_stamp",
            "source_inventory_sha256": status["current"]["source_inventory_sha256"],
        }
    fingerprint = dict(status["recorded"])
    fingerprint["generated_from_commit"] = _git(repo, "rev-parse", "HEAD")
    fingerprint["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    _write_json(repo / "docs" / "architecture" / "fingerprint.json", fingerprint)
    return {"status": "STAMPED", "fingerprint": fingerprint}


def sync_architecture(
    repo: Path,
    *,
    mode: str = "sync",
    kit_dir: Path | None = None,
    archify: str | Path | None = None,
    no_render: bool = False,
    no_web: bool = False,
) -> dict[str, Any]:
    repo = _repo_path(repo)
    status_before = current_architecture_status(repo)
    if mode == "auto" and status_before["status"] == "SYNCED":
        return {
            "status": "SOURCE_UNCHANGED",
            "idempotent": True,
            "source_inventory_sha256": status_before["current"]["source_inventory_sha256"],
            "module_count": status_before["current"]["module_count"],
        }

    inventory = status_before["current"]
    copied: list[str] = []
    if kit_dir:
        copied = _copy_kit_assets(repo, _repo_path(kit_dir))
    write_inventory(repo, inventory)
    write_source_map(repo, inventory)
    write_active_index(repo)
    (repo / "docs" / "architecture" / "README.md").write_text(README, encoding="utf-8", newline="\n")

    binary = next(iter(_archify_candidates(repo, archify)), None)
    render_status = "RENDER_PENDING"
    receipts: list[dict[str, Any]] = []
    if not no_render and binary:
        render_status, receipts = render_active_maps(repo, binary)
    elif not no_render:
        render_status = "RENDER_PENDING"

    web_result: dict[str, Any] = {"status": "SKIPPED", "reason": "disabled"}
    if not no_web and render_status == "SYNCED":
        sample = _repo_path(kit_dir) / "web" / "ContextCord_0.6.2a1_Architecture_Updated_FIXED_v2.html" if kit_dir else None
        web_result = update_web(repo, inventory, sample_html=sample)

    final_status = render_status
    if no_render:
        final_status = "RENDER_PENDING"
    fingerprint = _fingerprint(repo, inventory, status=final_status, archify_version=ARCHIFY_VERSION if binary and final_status == "SYNCED" else None)
    _write_json(repo / "docs" / "architecture" / "fingerprint.json", fingerprint)
    receipt = {
        "schema": "contextcord-architecture-sync-receipt-v1",
        "status": final_status,
        "mode": mode,
        "source_inventory_sha256": inventory["source_inventory_sha256"],
        "module_count": inventory["module_count"],
        "active_specs": fingerprint["active_specs"],
        "active_maps": fingerprint["active_maps"],
        "renderer": str(binary) if binary else None,
        "copied_from_kit": copied,
        "map_receipts": [row["map"] for row in receipts],
        "web": web_result,
        "visual_check": "VISUAL_CHECK_NOT_CERTIFIED",
    }
    receipt_path = repo / "docs" / "architecture" / "receipts" / f"architecture-sync-{inventory['source_inventory_sha256'][:16]}.json"
    _write_json(receipt_path, receipt)
    return {**receipt, "fingerprint": fingerprint, "receipt_path": receipt_path.relative_to(repo).as_posix()}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inventory", "sync", "auto", "status", "stamp"])
    parser.add_argument("--repo", default=".")
    parser.add_argument("--kit-dir")
    parser.add_argument("--archify")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo = _repo_path(args.repo)
    if args.command == "inventory":
        value = scan_source_inventory(repo)
    elif args.command == "status":
        value = current_architecture_status(repo)
    elif args.command == "stamp":
        value = stamp_fingerprint(repo)
    else:
        value = sync_architecture(
            repo,
            mode="auto" if args.command == "auto" else "sync",
            kit_dir=_repo_path(args.kit_dir) if args.kit_dir else None,
            archify=args.archify,
            no_render=bool(args.no_render),
            no_web=bool(args.no_web),
        )
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if value.get("status") not in {"VALIDATION_FAILED", "DRIFT"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
