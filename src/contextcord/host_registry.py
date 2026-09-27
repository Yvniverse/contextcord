"""Vendor-neutral ContextCord Host Evidence Registry v3.

Product integration, continuation evidence and qualification evidence are
independent dimensions.  The canonical registry is ContextCord-native v3;
the historical Agent-Nexus v2 shape is read and normalized in memory without
rewriting the preserved source document.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


BUILTIN_HOST_IDS = ("codex", "qoder", "cursor", "opencode", "workbuddy")
LEGACY_BUILTIN_HOST_IDS = ("qoder", "cursor", "opencode", "workbuddy")
REGISTRY_SCHEMA = "contextcord-host-evidence-registry-v3"
LEGACY_REGISTRY_SCHEMA = "agent-nexus-host-evidence-registry-v2"
# Legacy v2 payloads are normalized in memory for compatibility.  Historical
# copies live outside the active registry path; new reads and writes use the
# ContextCord-native v3 artifact.
REGISTRY_RELATIVE_PATH = Path("research") / "host_evidence_registry_v3.json"


class RegistryError(ValueError):
    """Raised when a host registry is malformed."""


def registry_path(repo: str | Path) -> Path:
    return Path(repo).expanduser().resolve() / REGISTRY_RELATIVE_PATH


def _require(value: Mapping[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    if key not in value or not isinstance(value[key], kind):
        raise RegistryError(f"registry_field_invalid:{key}")
    return value[key]


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RegistryError(f"registry_field_invalid:{field}")
    return list(value)


def _validate_integration(host_id: str, value: Mapping[str, Any]) -> None:
    adapter = _require(value, "adapter", Mapping)
    if adapter.get("status") not in {"PASS", "PARTIAL", "NOT_RUN"}:
        raise RegistryError(f"registry_adapter_contract_invalid:{host_id}")
    _require(adapter, "manifest", str)
    _require(adapter, "manifest_schema", str)
    config = _require(value, "config", Mapping)
    if config.get("status") not in {"PASS", "PARTIAL", "NOT_RUN"}:
        raise RegistryError(f"registry_config_contract_invalid:{host_id}")


def _validate_continuation(host_id: str, value: Mapping[str, Any]) -> None:
    if value.get("status") not in {"VERIFIED", "PARTIAL", "PENDING", "NOT_RUN"}:
        raise RegistryError(f"registry_continuation_invalid:{host_id}")
    _string_list(value.get("evidence_refs"), f"continuation.evidence_refs:{host_id}")
    protocol_id = value.get("protocol_id")
    if protocol_id is not None and not isinstance(protocol_id, str):
        raise RegistryError(f"registry_continuation_protocol_invalid:{host_id}")
    model_observation = value.get("model_observation")
    if model_observation is not None and not isinstance(model_observation, str):
        raise RegistryError(f"registry_continuation_model_invalid:{host_id}")


def _validate_qualification(host_id: str, value: Mapping[str, Any]) -> None:
    status = value.get("status")
    if status not in {"PASS", "PARTIAL", "NOT_QUALIFIED", "NOT_RUN", "PROVIDER_UNAVAILABLE"}:
        raise RegistryError(f"registry_qualification_invalid:{host_id}")
    qualified = value.get("qualified")
    if not isinstance(qualified, bool):
        raise RegistryError(f"registry_qualification_qualified_invalid:{host_id}")
    evidence_refs = _string_list(value.get("evidence_refs"), f"qualification.evidence_refs:{host_id}")
    protocol_id = value.get("protocol_id")
    if protocol_id is not None and not isinstance(protocol_id, str):
        raise RegistryError(f"registry_qualification_protocol_invalid:{host_id}")
    if qualified:
        if status != "PASS" or not isinstance(protocol_id, str) or not protocol_id.strip() or not evidence_refs:
            raise RegistryError(f"registry_qualified_evidence_invalid:{host_id}")
    trials = value.get("trials_per_arm")
    if trials is not None and (not isinstance(trials, int) or isinstance(trials, bool) or trials < 0):
        raise RegistryError(f"registry_qualification_trials_invalid:{host_id}")


def _validate_host(row: Mapping[str, Any]) -> None:
    host_id = _require(row, "host_id", str)
    if host_id not in BUILTIN_HOST_IDS:
        raise RegistryError(f"registry_unknown_builtin_host:{host_id}")
    _require(row, "display_name", str)
    if row.get("product_tier") != "BUILT_IN":
        raise RegistryError(f"registry_product_tier_invalid:{host_id}")
    _validate_integration(host_id, _require(row, "integration", Mapping))
    _validate_continuation(host_id, _require(row, "continuation", Mapping))
    _validate_qualification(host_id, _require(row, "qualification", Mapping))
    limitations = _require(row, "limitations", list)
    if not all(isinstance(item, str) for item in limitations):
        raise RegistryError(f"registry_limitations_invalid:{host_id}")


def validate_registry(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a canonical v3 registry and return a detached dictionary."""
    if not isinstance(value, Mapping):
        raise RegistryError("registry_must_be_object")
    if value.get("schema") != REGISTRY_SCHEMA:
        raise RegistryError("registry_schema_invalid")
    registry_version = _require(value, "registry_version", str)
    if not registry_version.strip():
        raise RegistryError("registry_version_invalid")
    hosts = _require(value, "built_in_hosts", list)
    if len(hosts) != len(BUILTIN_HOST_IDS):
        raise RegistryError("registry_must_contain_exactly_five_builtin_hosts")
    if not all(isinstance(row, Mapping) for row in hosts):
        raise RegistryError("registry_host_row_must_be_object")
    ids = [row["host_id"] for row in hosts]
    if len(set(ids)) != len(ids) or set(ids) != set(BUILTIN_HOST_IDS):
        raise RegistryError("registry_must_contain_exactly_the_five_builtin_hosts")
    for row in hosts:
        _validate_host(row)
    byoh = _require(value, "byoh", Mapping)
    if byoh.get("product_tier") != "BYOH" or not isinstance(byoh.get("manifest_schema"), str):
        raise RegistryError("registry_byoh_invalid")
    if not isinstance(value.get("truth_boundary"), str) or not value["truth_boundary"].strip():
        raise RegistryError("registry_truth_boundary_invalid")
    verified_at = value.get("verified_at")
    if verified_at is not None and not isinstance(verified_at, str):
        raise RegistryError("registry_verified_at_invalid")
    return dict(value)


def _legacy_qualification(benchmark: Mapping[str, Any], host_id: str) -> dict[str, Any]:
    status = benchmark.get("status")
    if status == "PENDING":
        status = "NOT_RUN"
    if status not in {"PASS", "PARTIAL", "NOT_QUALIFIED", "NOT_RUN", "PROVIDER_UNAVAILABLE"}:
        raise RegistryError(f"legacy_registry_qualification_invalid:{host_id}")
    evidence = benchmark.get("evidence", [])
    evidence_refs = _string_list(evidence, f"benchmark.evidence:{host_id}")
    return {
        "status": status,
        "qualified": benchmark.get("qualified") is True,
        "protocol_id": benchmark.get("generation"),
        "trials_per_arm": benchmark.get("trials_per_arm"),
        "latest_probe": benchmark.get("latest_probe"),
        "evidence_refs": evidence_refs,
        "legacy_status": benchmark.get("status"),
    }


def _normalize_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    hosts = _require(value, "built_in_hosts", list)
    if len(hosts) != len(LEGACY_BUILTIN_HOST_IDS):
        raise RegistryError("legacy_registry_must_contain_exactly_four_builtin_hosts")
    legacy_ids = [row.get("host_id") for row in hosts if isinstance(row, Mapping)]
    if len(set(legacy_ids)) != len(legacy_ids) or set(legacy_ids) != set(LEGACY_BUILTIN_HOST_IDS):
        raise RegistryError("legacy_registry_must_contain_the_four_known_builtin_hosts")
    normalized_hosts: list[dict[str, Any]] = []
    for raw in hosts:
        if not isinstance(raw, Mapping):
            raise RegistryError("legacy_registry_host_row_must_be_object")
        host_id = _require(raw, "host_id", str)
        adapter = dict(_require(raw, "adapter_contract", Mapping))
        config = dict(_require(raw, "config_contract", Mapping))
        continuation = dict(_require(raw, "native_continuation", Mapping))
        qualification = _legacy_qualification(_require(raw, "benchmark", Mapping), host_id)
        normalized_hosts.append({
            "host_id": host_id,
            "display_name": _require(raw, "display_name", str),
            **({"vendor": raw["vendor"]} if isinstance(raw.get("vendor"), str) else {}),
            "product_tier": raw.get("product_tier"),
            "integration": {"adapter": adapter, "config": config},
            "continuation": continuation,
            "qualification": qualification,
            "limitations": list(_require(raw, "limitations", list)),
            "legacy_schema": LEGACY_REGISTRY_SCHEMA,
        })
    normalized = {
        "schema": REGISTRY_SCHEMA,
        "registry_version": str(value.get("registry_version", "legacy-v2")),
        "verified_at": value.get("verified_at"),
        "built_in_hosts": normalized_hosts,
        "byoh": dict(_require(value, "byoh", Mapping)),
        "truth_boundary": _require(value, "truth_boundary", str),
        "legacy_schema": LEGACY_REGISTRY_SCHEMA,
    }
    # The legacy shape has four hosts and therefore cannot be a canonical v3
    # registry.  It is still normalized for callers that only need to inspect
    # historical rows; the missing Codex row is intentionally not fabricated.
    return normalized


def normalize_registry(value: Mapping[str, Any]) -> dict[str, Any]:
    """Read v3 directly or normalize a historical v2 document in memory."""
    if not isinstance(value, Mapping):
        raise RegistryError("registry_must_be_object")
    schema = value.get("schema")
    if schema == REGISTRY_SCHEMA:
        return validate_registry(value)
    if schema == LEGACY_REGISTRY_SCHEMA:
        return _normalize_v2(value)
    raise RegistryError("registry_schema_invalid")


def _read_registry_file(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise RegistryError("host_evidence_registry_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RegistryError("host_evidence_registry_invalid_json") from exc
    return normalize_registry(value)


def load_registry(repo: str | Path) -> dict[str, Any]:
    return _read_registry_file(registry_path(repo))


def load_registry_file(path: str | Path) -> dict[str, Any]:
    """Load either a canonical v3 or historical v2 registry file."""
    return _read_registry_file(Path(path).expanduser().resolve())


def host_row(repo: str | Path, host_id: str) -> dict[str, Any]:
    value = load_registry(repo)
    for row in value["built_in_hosts"]:
        if row["host_id"] == host_id:
            return dict(row)
    raise RegistryError(f"unknown_builtin_host:{host_id}")


def benchmark_qualified(row: Mapping[str, Any]) -> bool:
    qualification = row.get("qualification") if isinstance(row, Mapping) else None
    if not isinstance(qualification, Mapping):
        return False
    evidence_refs = qualification.get("evidence_refs")
    protocol_id = qualification.get("protocol_id")
    return bool(
        row.get("product_tier") == "BUILT_IN"
        and qualification.get("status") == "PASS"
        and qualification.get("qualified") is True
        and isinstance(protocol_id, str)
        and bool(protocol_id.strip())
        and isinstance(evidence_refs, list)
        and bool(evidence_refs)
    )


def summary(repo: str | Path) -> dict[str, Any]:
    value = load_registry(repo)
    rows = value["built_in_hosts"]
    verified = [row["host_id"] for row in rows if row["continuation"].get("status") == "VERIFIED"]
    return {
        "schema": value["schema"],
        "built_in_host_ids": list(BUILTIN_HOST_IDS),
        "built_in_count": len(rows),
        "qualified_current_hosts": [row["host_id"] for row in rows if benchmark_qualified(row)],
        "continuation_verified_hosts": verified,
        "native_continuation_verified_hosts": verified,
        "truth_source": str(REGISTRY_RELATIVE_PATH).replace("\\", "/"),
    }


__all__ = [
    "BUILTIN_HOST_IDS",
    "LEGACY_BUILTIN_HOST_IDS",
    "LEGACY_REGISTRY_SCHEMA",
    "REGISTRY_SCHEMA",
    "RegistryError",
    "benchmark_qualified",
    "host_row",
    "load_registry",
    "load_registry_file",
    "normalize_registry",
    "registry_path",
    "summary",
    "validate_registry",
]
