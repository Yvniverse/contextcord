"""Bring Your Own Host / Adapter Lab for manifest-driven MCP clients."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .util import atomic_write_json, sha256_json, utc_now


MANIFEST_SCHEMA = "contextcord-host-adapter-v1"
CERTIFICATION_LADDER = (
    "TEMPLATE_ONLY",
    "CONFIG_RENDERED",
    "MCP_CONNECTED",
    "TOOLS_DISCOVERED",
    "MEMORY_CALL_PASS",
    "CONTINUATION_PASS",
    "BENCHMARK_QUALIFIED",
)
SECRET_NAME_RE = re.compile(r"(?i)(api[_-]?key|secret|token|password|authorization|private[_-]?key)")
SECRET_VALUE_RE = re.compile(r"(?i)(bearer\s+[a-z0-9._-]{12,}|sk-[a-z0-9_-]{12,}|typesafe[_-]api[_-]?key|-----begin [^-]+ key-----)")
SAFE_DECLARATIONS = {"optional", "unknown", "host_returned", "host_returned_or_unknown", "host_returned_or_unknown", "host_returned; a11 returned auto"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _schema_path() -> Path:
    return _repo_root() / "support" / "adapter_manifest.schema.json"


def _redact(value: str) -> str:
    value = SECRET_VALUE_RE.sub("[REDACTED]", value)
    return value[:1024]


def _secret_paths(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            harmless = isinstance(item, str) and item.casefold() in SAFE_DECLARATIONS
            if SECRET_NAME_RE.search(str(key)) and item not in (None, "", False, [], {}) and not harmless:
                found.append(child)
            found.extend(_secret_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_secret_paths(item, f"{path}[{index}]"))
    elif isinstance(value, str) and SECRET_VALUE_RE.search(value):
        found.append(path)
    return found


def load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("adapter_manifest_must_be_object")
    return value


def validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    schema_path = _schema_path()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: str(error.path))
    failures = [error.message for error in errors]
    failures.extend("secret_like_manifest_field:" + item for item in _secret_paths(value))
    return {
        "status": "PASS" if not failures else "FAIL",
        "schema": value.get("schema"),
        "manifest_id": value.get("id"),
        "errors": failures,
        "required_tools": list(value.get("required_contextcord_tools") or []),
        "secret_fields_rejected": bool(_secret_paths(value)),
    }


def discover_manifests(root: Path | None = None) -> list[dict[str, Any]]:
    directory = (root or (_repo_root() / "support" / "adapters")).resolve()
    rows = []
    for path in sorted(directory.glob("*.adapter.json")):
        try:
            value = load_manifest(path)
            result = validate_manifest(value)
            result["path"] = str(path)
            result["display_name"] = value.get("display_name")
            rows.append(result)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            rows.append({"status": "FAIL", "path": str(path), "errors": [type(exc).__name__ + ":" + str(exc)]})
    return rows


def init_manifest(manifest_id: str, output: Path, *, display_name: str | None = None, force: bool = False) -> dict[str, Any]:
    manifest_id = str(manifest_id).strip().casefold()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", manifest_id):
        raise ValueError("adapter_id_invalid")
    if output.exists() and not force:
        raise ValueError("adapter_manifest_output_exists_use_force")
    value = {
        "schema": MANIFEST_SCHEMA,
        "id": manifest_id,
        "display_name": display_name or manifest_id,
        "vendor": "user",
        "transports": ["stdio"],
        "config_scopes": ["project"],
        "config_template": {"stdio": {"command": "contextcord", "args": ["mcp"]}},
        "reload": {"kind": "manual", "instruction": "Reload the host MCP configuration."},
        "list_tools": {"kind": "host_specific", "instruction": "Discover ContextCord tools."},
        "permissions": {"user_confirmation_required": True},
        "telemetry": {"model_id": "host_returned_or_unknown", "token_usage": "host_returned_or_unknown"},
        "required_contextcord_tools": ["contextcord_memory", "contextcord_memory_recheck"],
    }
    checked = validate_manifest(value)
    if checked["status"] != "PASS":
        raise ValueError("adapter_manifest_template_invalid:" + ";".join(checked["errors"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output, value)
    return {"status": "PASS", "path": str(output.resolve()), "manifest": value}


def _command(value: Any) -> list[str] | None:
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return list(value)
    if isinstance(value, str) and value.strip():
        return shlex.split(value, posix=False)
    return None


def _safe_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        if SECRET_NAME_RE.search(key):
            env.pop(key, None)
    return env


def _run_probe(command: list[str], *, repo: Path | None, timeout: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=str(repo) if repo else None, env=_safe_environment(), shell=False,
                                   capture_output=True, text=True, timeout=max(1.0, min(float(timeout), 30.0)), check=False)
        return {"status": "PASS" if completed.returncode == 0 else "FAIL", "returncode": completed.returncode,
                "command": command, "stdout": _redact(completed.stdout), "stderr": _redact(completed.stderr)}
    except FileNotFoundError:
        return {"status": "NOT_FOUND", "command": command, "error": "executable_not_found"}
    except subprocess.TimeoutExpired as exc:
        return {"status": "TIMEOUT", "command": command, "error": "probe_timeout", "stdout": _redact(str(exc.stdout or "")), "stderr": _redact(str(exc.stderr or ""))}
    except OSError as exc:
        return {"status": "FAIL", "command": command, "error": type(exc).__name__}


def probe_manifest(value: dict[str, Any], *, repo: Path | None = None, execute: bool = False) -> dict[str, Any]:
    checked = validate_manifest(value)
    if checked["status"] != "PASS":
        return {"status": "FAIL", "validation": checked, "probes": []}
    if not execute:
        return {"status": "NOT_RUN_USER_APPROVAL", "manifest_id": value.get("id"), "probes": [], "execute": False}
    probes: list[dict[str, Any]] = []
    version = ((value.get("version_probe") or {}).get("command"))
    if version:
        command = _command(version)
        probes.append(_run_probe(command, repo=repo, timeout=10.0) if command else {"status": "FAIL", "error": "version_probe_command_invalid"})
    list_tools = ((value.get("list_tools") or {}).get("command"))
    if list_tools:
        command = _command(list_tools)
        probes.append(_run_probe(command, repo=repo, timeout=10.0) if command else {"status": "FAIL", "error": "list_tools_command_invalid"})
    if not probes:
        probes.append({"status": "NOT_CONFIGURED", "message": "manifest declares host-managed discovery"})
    return {"status": "PASS" if all(row.get("status") == "PASS" for row in probes) else "PARTIAL", "manifest_id": value.get("id"), "probes": probes, "execute": True}


def render_manifest(value: dict[str, Any], *, output: Path, repo: Path | None = None, force: bool = False) -> dict[str, Any]:
    checked = validate_manifest(value)
    if checked["status"] != "PASS":
        return {"status": "FAIL", "validation": checked}
    if output.exists() and not force:
        raise ValueError("adapter_render_output_exists_use_force")
    rendered = {
        "schema": "contextcord-rendered-adapter-v1",
        "manifest_id": value["id"],
        "generated_at": utc_now(),
        "repo": str(repo.resolve()) if repo else None,
        "host_configuration": value.get("config_template") or {},
        "required_contextcord_tools": value.get("required_contextcord_tools") or [],
        "mutation_boundary": "Rendered staging artifact only; host configuration is not modified by Adapter Lab.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output, rendered)
    return {"status": "PASS", "path": str(output.resolve()), "rendered": rendered, "sha256": sha256_json(rendered)}


def certify_manifest(value: dict[str, Any], *, repo: Path | None = None, execute: bool = False, fixture: Path | None = None) -> dict[str, Any]:
    checked = validate_manifest(value)
    stages = [{"stage": stage, "status": "NOT_RUN"} for stage in CERTIFICATION_LADDER]
    if checked["status"] != "PASS":
        stages[0]["status"] = "FAIL"
        return {"status": "FAIL", "manifest_id": value.get("id"), "stages": stages, "validation": checked}
    stages[0]["status"] = "PASS"
    stages[1]["status"] = "PASS"
    if not execute:
        return {"status": "PARTIAL", "manifest_id": value.get("id"), "stages": stages, "validation": checked, "execution": "not requested"}
    probe = probe_manifest(value, repo=repo, execute=True)
    connected = probe.get("status") in {"PASS", "PARTIAL"}
    stages[2]["status"] = "PASS" if connected else "FAIL"
    tools_text = json.dumps(probe, ensure_ascii=False).casefold()
    required = [str(tool).casefold() for tool in (value.get("required_contextcord_tools") or [])]
    discovered = connected and all(tool in tools_text for tool in required)
    stages[3]["status"] = "PASS" if discovered else "NOT_OBSERVED"
    stages[4]["status"] = "NOT_RUN" if fixture is None else ("PASS" if discovered else "NOT_OBSERVED")
    stages[5]["status"] = "NOT_RUN"
    stages[6]["status"] = "NOT_RUN"
    status = "PASS" if all(row["status"] == "PASS" for row in stages[:5]) else "PARTIAL"
    return {"status": status, "manifest_id": value.get("id"), "stages": stages, "validation": checked, "probe": probe}


__all__ = ["CERTIFICATION_LADDER", "certify_manifest", "discover_manifests", "init_manifest", "load_manifest", "probe_manifest", "render_manifest", "validate_manifest"]
