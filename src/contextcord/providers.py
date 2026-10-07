"""Secret-safe provider status and doctor helpers.

Status inspection is intentionally local-only.  It reports provenance labels
and readiness, never key values, prefixes, lengths, hashes or headers.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Mapping

from .model_intelligence import DEFAULT_CODEXRADAR_URL, default_cache_path


def _module_installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _dotenv_key_present(path: Path, key_env: str) -> bool:
    """Check one dotenv key without parsing or returning its value."""

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    prefix = f"{key_env}="
    export_prefix = f"export {key_env}="
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(export_prefix):
            value = stripped[len(export_prefix):].strip()
        elif stripped.startswith(prefix):
            value = stripped[len(prefix):].strip()
        else:
            continue
        if value and not value.startswith("#"):
            return True
    return False


def inspect_jev(
    *,
    project_root: str | Path,
    feature_enabled: bool,
    provider_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(provider_config or {})
    mode = str(cfg.get("mode") or "manual").strip().casefold()
    key_env = str(cfg.get("key_env") or "TYPESAFE_API_KEY").strip() or "TYPESAFE_API_KEY"
    dotenv = Path(project_root).expanduser().resolve() / ".env"
    process_present = bool(os.environ.get(key_env, "").strip())
    dotenv_present = bool(cfg.get("allow_project_dotenv", True)) and _dotenv_key_present(dotenv, key_env)
    sdk_installed = _module_installed("typesafe_sdk")
    dotenv_loader_installed = _module_installed("dotenv")
    if process_present:
        key_source = "process_environment"
    elif dotenv_present:
        key_source = "project_dotenv_present"
    else:
        key_source = "not_configured"
    enabled = bool(feature_enabled) and mode != "off"
    ready = enabled and sdk_installed and key_source != "not_configured"
    reason: str | None = None
    if mode not in {"off", "manual", "auto"}:
        ready = False
        reason = "invalid_provider_mode"
    elif not enabled:
        reason = "provider_disabled"
    elif not sdk_installed:
        reason = "typesafe_sdk_missing"
    elif key_source == "not_configured":
        reason = f"{key_env}_not_configured"
    elif key_source == "project_dotenv_present" and not dotenv_loader_installed:
        # The optional provider cannot load a project dotenv without the
        # optional loader, while process environment configuration remains
        # fully usable without it.
        ready = False
        reason = "python_dotenv_missing"
    return {
        "schema": "contextcord-provider-status-v1",
        "provider": "jev",
        "enabled": enabled,
        "installed": sdk_installed,
        "ready": ready,
        "mode": mode,
        "model": str(cfg.get("model") or "jev-latest"),
        "endpoint": "https://api.typesafe.ai",
        "key_env": key_env,
        "key_configured": key_source != "not_configured",
        "key_source": key_source,
        "reason": reason,
        "secret_value_exposed": False,
        "network_probe_performed": False,
    }


def inspect_codexradar(
    *,
    project_root: str | Path,
    feature_enabled: bool,
    provider_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(provider_config or {})
    provider_enabled = bool(cfg.get("enabled", False))
    enabled = bool(feature_enabled) and provider_enabled
    cache_path = default_cache_path(project_root)
    return {
        "schema": "contextcord-provider-status-v1",
        "provider": "codexradar",
        "enabled": enabled,
        "installed": True,
        "ready": enabled,
        "mode": str(cfg.get("mode") or "on_demand"),
        "benchmark": str(cfg.get("benchmark") or "deep-swe"),
        "source": "Codex Radar / Distributed Radar",
        "source_url": str(cfg.get("source_url") or DEFAULT_CODEXRADAR_URL),
        "cache_path": str(cache_path),
        "network_probe_performed": False,
        "reason": None if enabled else "provider_disabled",
        "secret_value_exposed": False,
    }


def list_provider_statuses(
    *,
    project_root: str | Path,
    resolved_features: Mapping[str, Any],
    project: Mapping[str, Any],
) -> list[dict[str, Any]]:
    providers = project.get("providers", {})
    if not isinstance(providers, Mapping):
        providers = {}
    jev_config = providers.get("jev", {}) if isinstance(providers.get("jev", {}), Mapping) else {}
    radar_config = providers.get("codexradar", {}) if isinstance(providers.get("codexradar", {}), Mapping) else {}
    effective = set(resolved_features.get("effective") or ())
    return [
        inspect_jev(
            project_root=project_root,
            feature_enabled="jev" in effective,
            provider_config=jev_config,
        ),
        inspect_codexradar(
            project_root=project_root,
            feature_enabled="model_intelligence" in effective,
            provider_config=radar_config,
        ),
    ]


__all__ = ["inspect_codexradar", "inspect_jev", "list_provider_statuses"]
