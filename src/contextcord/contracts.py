from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator


class ContractError(RuntimeError):
    pass


SCHEMAS = {
    "project": "project.schema.json",
    "truth": "truth.schema.json",
    "workflow": "workflow.schema.json",
    "authority": "authority.schema.json",
    "runtime": "runtime.schema.json",
    "evidence": "evidence.schema.json",
    "qualification": "qualification.schema.json",
    "source-identity": "source-identity.schema.json",
    "event": "event.schema.json",
    "session-receipt": "session-receipt.schema.json",
    "runner-receipt": "runner-receipt.schema.json",
    "qualification-note": "qualification-note.schema.json",
    "dual-run-ledger": "dual-run-ledger.schema.json",
    "release-identity": "release-identity.schema.json",
    "portable-bundle": "portable-bundle.schema.json",
    "portable-memory": "portable-memory.schema.json",
    "model-route-outcome": "model-route-outcome.schema.json",
    "model-route-decision-v3": "model-route-decision-v3.schema.json",
    "execution-route-capability": "execution-route-capability.schema.json",
    "adaptive-router-calibration": "adaptive-router-calibration.schema.json",
}


def schema(name: str) -> dict[str, Any]:
    filename = SCHEMAS.get(name)
    if not filename:
        raise ContractError(f"unknown schema: {name}")
    resource = files("contextcord.schemas").joinpath(filename)
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"invalid bundled schema: {filename}")
    return value


def validation_errors(name: str, payload: Any) -> list[str]:
    validator = Draft202012Validator(schema(name))
    out: list[str] = []
    for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(x) for x in error.absolute_path) or "$"
        out.append(f"{path}: {error.message}")
    return out


def validate(name: str, payload: Any) -> None:
    errors = validation_errors(name, payload)
    if errors:
        raise ContractError(f"{name} contract validation failed: " + "; ".join(errors[:12]))
