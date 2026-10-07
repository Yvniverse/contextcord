"""The single runtime capability registry for ContextCord.

Capabilities are orchestration metadata.  They do not own state, memory, or
decision truth; the existing modules remain the implementation of those
systems.  Keeping this module deliberately small also means feature discovery
does not import optional providers or heavy command handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class CapabilitySpec:
    id: str
    requires: tuple[str, ...] = ()
    optional_extra: str | None = None
    description: str = ""
    cli_group: str | None = None
    mcp_tools: tuple[str, ...] = ()
    dev_only: bool = False
    import_modules: tuple[str, ...] = ()
    product_areas: tuple[str, ...] = ()


def _spec(
    ident: str,
    requires: tuple[str, ...] = (),
    *,
    optional_extra: str | None = None,
    description: str = "",
    cli_group: str | None = None,
    mcp_tools: tuple[str, ...] = (),
    dev_only: bool = False,
    import_modules: tuple[str, ...] = (),
    product_areas: tuple[str, ...] = (),
) -> CapabilitySpec:
    return CapabilitySpec(
        ident,
        requires,
        optional_extra=optional_extra,
        description=description,
        cli_group=cli_group,
        mcp_tools=mcp_tools,
        dev_only=dev_only,
        import_modules=import_modules,
        product_areas=product_areas,
    )


# Keep this mapping as the only canonical capability declaration.  The order
# is also the stable order used by human and JSON status output.
SPECS: dict[str, CapabilitySpec] = {
    "core": _spec(
        "core",
        description="config, identity, store, authority and the capability registry",
        cli_group="core",
        mcp_tools=("identity", "authorize"),
        import_modules=("contextcord.config", "contextcord.store"),
        product_areas=("shared_kernel",),
    ),
    "evidence": _spec(
        "evidence",
        ("core",),
        description="evidence, receipts, replay, qualification and verification",
        cli_group="evidence",
        mcp_tools=("verify", "replay"),
        import_modules=("contextcord.evidence", "contextcord.receipt"),
        product_areas=("veritas",),
    ),
    "continuity": _spec(
        "continuity",
        ("core",),
        description="task/session context and workflow lifecycle",
        cli_group="continuity",
        mcp_tools=("context", "start", "checkpoint", "advance", "finish"),
        import_modules=("contextcord.context", "contextcord.workflow"),
        product_areas=("continuum", "context_engine"),
    ),
    "memory": _spec(
        "memory",
        ("continuity",),
        description="bounded notes, context jobs and portable memory",
        cli_group="memory",
        mcp_tools=("memory", "memory_recheck"),
        import_modules=("contextcord.memory", "contextcord.bm25"),
        product_areas=("context_engine",),
    ),
    "decision": _spec(
        "decision",
        ("core",),
        description="deterministic Decision Fabric and typed policy layer",
        cli_group="decision",
        mcp_tools=("decision_fabric",),
        import_modules=("contextcord.decision", "contextcord.decision_fabric"),
        product_areas=("decision_plane",),
    ),
    "jev": _spec(
        "jev",
        ("decision",),
        optional_extra="jev",
        description="optional TypeSafe Jev provider",
        cli_group="provider",
        import_modules=("contextcord.jev_provider",),
        product_areas=("jev",),
    ),
    "router": _spec(
        "router",
        ("decision",),
        description="closed model x reasoning-effort route planning",
        cli_group="router",
        mcp_tools=("route_model",),
        import_modules=("contextcord.router",),
        product_areas=("decision_plane",),
    ),
    "model_intelligence": _spec(
        "model_intelligence",
        ("core",),
        description="read-only CodexRadar and model-quality priors",
        cli_group="model-intelligence",
        mcp_tools=("model_intelligence_snapshot",),
        import_modules=("contextcord.model_intelligence",),
        product_areas=("decision_plane",),
    ),
    "mcp": _spec(
        "mcp",
        ("core",),
        description="MCP transport and dynamic tool catalog",
        cli_group="mcp",
        import_modules=("contextcord.mcp", "contextcord.service"),
        product_areas=("gateway",),
    ),
    "hosts": _spec(
        "hosts",
        ("mcp",),
        description="host adapters, configuration and integration registry",
        cli_group="hosts",
        import_modules=("contextcord.host_configs", "contextcord.host_registry"),
        product_areas=("gateway",),
    ),
    "handoff": _spec(
        "handoff",
        ("continuity", "memory"),
        description="bounded Handoff preview and atomic confirmation",
        cli_group="handoff",
        mcp_tools=("handoff", "handoff_confirm"),
        import_modules=("contextcord.handoff",),
        product_areas=("continuum",),
    ),
    "closeout": _spec(
        "closeout",
        ("continuity", "evidence"),
        description="closeout facade and generated closeout evidence",
        cli_group="closeout",
        import_modules=("contextcord.closeout",),
        product_areas=("continuum",),
    ),
}

RUNTIME_CAPABILITIES: tuple[str, ...] = tuple(key for key, spec in SPECS.items() if not spec.dev_only)
ALL_CAPABILITIES: tuple[str, ...] = tuple(SPECS)

PROFILES: dict[str, frozenset[str]] = {
    "minimal": frozenset({"core", "evidence"}),
    "continuity": frozenset(
        {"core", "evidence", "continuity", "memory", "handoff", "mcp", "hosts", "closeout"}
    ),
    "decision": frozenset({"core", "evidence", "decision", "router", "model_intelligence"}),
    "full": frozenset(RUNTIME_CAPABILITIES),
    # This is intentionally the compatibility surface, not a new feature
    # profile.  It preserves pre-feature projects with no [features] table.
    "legacy_current": frozenset(RUNTIME_CAPABILITIES),
}

# Product modules are a documentation and UX projection.  Their capability
# membership is derived from the same SPECS entries below; this tuple carries
# only stable display order and labels, not a second runtime registry.
PRODUCT_MODULES: tuple[tuple[str, str], ...] = (
    ("continuum", "Continuum"),
    ("context_engine", "Context Engine"),
    ("veritas", "Veritas"),
    ("decision_plane", "Decision Plane"),
    ("gateway", "MCP / Host Gateway"),
    ("jev", "Jev"),
)


class CapabilityConfigError(ValueError):
    """A user-intent/configuration error with a stable machine-readable code."""

    def __init__(self, code: str, message: str | None = None, *, details: Any = None) -> None:
        self.code = str(code)
        self.details = details
        super().__init__(message or self.code)


def _values(raw: Any, *, field: str) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, str) or not isinstance(raw, (list, tuple, set, frozenset)):
        raise CapabilityConfigError("invalid_feature_config", f"features.{field} must be an array")
    return {str(value) for value in raw}


def _ordered(values: set[str]) -> list[str]:
    return [ident for ident in ALL_CAPABILITIES if ident in values]


def _closure(values: set[str], explicitly_disabled: set[str]) -> set[str]:
    result = set(values)
    todo = list(values)
    while todo:
        current = todo.pop()
        spec = SPECS[current]
        for dependency in spec.requires:
            if dependency in explicitly_disabled:
                raise CapabilityConfigError(
                    "explicit_disable_dependency_conflict",
                    f"explicitly_disabled_dependency:{current}->{dependency}",
                    details={"capability": current, "dependency": dependency},
                )
            if dependency not in result:
                result.add(dependency)
                todo.append(dependency)
    result.add("core")
    return result


def resolve_features(project: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve profile, explicit enable/disable and hard dependency closure."""

    raw = project.get("features")
    if raw is None:
        profile = "legacy_current"
        explicitly_enabled: set[str] = set()
        explicitly_disabled: set[str] = set()
    elif isinstance(raw, Mapping):
        profile = str(raw.get("profile") or "custom")
        explicitly_enabled = _values(raw.get("enable", []), field="enable")
        explicitly_disabled = _values(raw.get("disable", []), field="disable")
    else:
        raise CapabilityConfigError("invalid_feature_config", "features must be a TOML table")

    unknown = sorted((explicitly_enabled | explicitly_disabled) - set(SPECS))
    if unknown:
        raise CapabilityConfigError("unknown_capabilities", f"unknown_capabilities:{unknown}", details=unknown)
    if profile not in PROFILES and profile != "custom":
        raise CapabilityConfigError("unknown_profile", f"unknown_profile:{profile}", details=profile)
    if "core" in explicitly_disabled:
        raise CapabilityConfigError("core_cannot_be_disabled", "core_cannot_be_disabled")

    baseline = set(PROFILES[profile]) if profile != "custom" else {"core"}
    requested = (baseline | explicitly_enabled) - explicitly_disabled
    effective = _closure(requested, explicitly_disabled)
    # Dev-only metadata is queryable but is never implicitly part of a runtime
    # profile.  A user may explicitly mention it without enabling the runtime.
    effective -= {ident for ident, spec in SPECS.items() if spec.dev_only}
    return {
        "profile": profile,
        "requested": _ordered(requested),
        "effective": _ordered(effective),
        "explicitly_enabled": _ordered(explicitly_enabled),
        "explicitly_disabled": _ordered(explicitly_disabled),
    }


def enabled(resolved: Mapping[str, Any], capability: str) -> bool:
    return str(capability) in set(resolved.get("effective") or ())


def product_module_projection(
    resolved: Mapping[str, Any],
    *,
    capability_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return module responsibility and health derived from ``SPECS`` + status.

    The optional status payload lets repository-aware callers reuse the exact
    secret-safe provider inspection they already performed.  A lightweight
    status is derived for library callers, without network access or provider
    imports, so this remains a projection rather than a second registry.
    """

    effective = set(resolved.get("effective") or ())
    if capability_status is None:
        capability_status = status(
            {"features": {"profile": "custom", "enable": sorted(effective)}}
        )
    status_rows = {
        str(row.get("id")): row
        for row in (capability_status.get("capabilities") or [])
        if isinstance(row, Mapping)
    }
    modules: list[dict[str, Any]] = []
    for module_id, label in PRODUCT_MODULES:
        capabilities = [
            ident
            for ident, item in SPECS.items()
            if module_id in item.product_areas
        ]
        effective_capabilities = [ident for ident in capabilities if ident in effective]
        ready_capabilities = [
            ident
            for ident in effective_capabilities
            if bool((status_rows.get(ident) or {}).get("ready"))
        ]
        reasons = [
            str((status_rows.get(ident) or {}).get("reason"))
            for ident in effective_capabilities
            if (status_rows.get(ident) or {}).get("reason")
        ]
        active = bool(effective_capabilities)
        ready = active and len(ready_capabilities) == len(effective_capabilities)
        state = "disabled" if not active else ("ready" if ready else "degraded")
        if not active:
            reasons = ["not_effective"]
        modules.append(
            {
                "id": module_id,
                "name": label,
                "capabilities": capabilities,
                "effective_capabilities": effective_capabilities,
                "ready_capabilities": ready_capabilities,
                "active": active,
                "ready": ready,
                "state": state,
                "reasons": sorted(set(reasons)),
            }
        )
    return {
        "schema": "contextcord-product-module-projection-v2",
        "source": "SPECS",
        "profile": resolved.get("profile"),
        "modules": modules,
        "runtime_registry": list(RUNTIME_CAPABILITIES),
        "state_store": "single repository-local StateStore",
    }


def spec(capability: str) -> CapabilitySpec:
    try:
        return SPECS[str(capability)]
    except KeyError as exc:
        raise CapabilityConfigError("unknown_capability", f"unknown_capability:{capability}") from exc


def _installed(capability: str) -> tuple[bool, str | None]:
    item = spec(capability)
    if item.optional_extra == "jev":
        try:
            installed = find_spec("typesafe_sdk") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            installed = False
        return installed, None if installed else "typesafe_sdk_missing"
    for module in item.import_modules:
        try:
            if find_spec(module) is None:
                return False, f"module_missing:{module}"
        except (ImportError, ModuleNotFoundError, ValueError):
            return False, f"module_missing:{module}"
    return True, None


def status(
    project: Mapping[str, Any],
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return the four-layer capability status without performing provider I/O."""

    resolved = resolve_features(project)
    requested = set(resolved["requested"])
    effective = set(resolved["effective"])
    rows: list[dict[str, Any]] = []
    for ident in RUNTIME_CAPABILITIES:
        item = spec(ident)
        installed, reason = _installed(ident)
        ready = ident in effective and installed
        if ident == "jev" and ident in effective:
            # Importing this helper does not import the SDK or issue a request.
            from .providers import inspect_jev

            provider = inspect_jev(
                project_root=project_root or Path.cwd(),
                feature_enabled=True,
                provider_config=(project.get("providers", {}) or {}).get("jev", {}),
            )
            installed = bool(provider.get("installed"))
            ready = bool(provider.get("ready"))
            reason = provider.get("reason")
        if ident not in effective:
            reason = "not_effective"
        rows.append(
            {
                "id": ident,
                "requested": ident in requested,
                "effective": ident in effective,
                "installed": bool(installed),
                "ready": bool(ready),
                "reason": reason,
                "requires": list(item.requires),
                "description": item.description,
                "product_areas": list(item.product_areas),
            }
        )
    return {
        "schema": "contextcord-capability-status-v1",
        "profile": resolved["profile"],
        "requested": resolved["requested"],
        "effective": resolved["effective"],
        "explicitly_enabled": resolved["explicitly_enabled"],
        "explicitly_disabled": resolved["explicitly_disabled"],
        "capabilities": rows,
    }


def atomic_write_features(
    project_toml: str | Path,
    *,
    profile: str,
    enable: list[str] | tuple[str, ...] | set[str],
    disable: list[str] | tuple[str, ...] | set[str],
) -> None:
    """Atomically replace only the existing ``[features]`` TOML table.

    Python's standard library intentionally has no TOML writer.  Replacing a
    small, bounded table preserves all unrelated project/provider settings and
    avoids introducing a second configuration file or dependency.
    """

    path = Path(project_toml)
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = "\n".join(
        [
            "[features]",
            f"profile = {json.dumps(str(profile), ensure_ascii=False)}",
            f"enable = {json.dumps(sorted({str(x) for x in enable}), ensure_ascii=False)}",
            f"disable = {json.dumps(sorted({str(x) for x in disable}), ensure_ascii=False)}",
        ]
    )
    lines = original.splitlines()
    start = None
    end = None
    for index, line in enumerate(lines):
        if re.match(r"^\s*\[features\]\s*$", line):
            start = index
            break
    if start is not None:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if re.match(r"^\s*\[[^]]+\]\s*$", lines[index]):
                end = index
                break
        updated_lines = lines[:start] + block.splitlines() + lines[end:]
    else:
        updated_lines = lines[:]
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        updated_lines.extend(block.splitlines())
    updated = "\n".join(updated_lines).rstrip("\n") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(updated, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


__all__ = [
    "ALL_CAPABILITIES",
    "CapabilityConfigError",
    "CapabilitySpec",
    "PRODUCT_MODULES",
    "PROFILES",
    "RUNTIME_CAPABILITIES",
    "SPECS",
    "enabled",
    "product_module_projection",
    "atomic_write_features",
    "resolve_features",
    "spec",
    "status",
]
