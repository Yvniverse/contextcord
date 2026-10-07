from __future__ import annotations

import json
import os
import re
try:  # Python 3.11+ standard library; tomli keeps older Linux runners readable.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Linux 3.10 runner
    import tomli as tomllib  # type: ignore[no-redef]
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ContractError, validate
from .util import expand_string, ensure_repo_path


class ConfigError(RuntimeError):
    pass


PRIMARY_STATE_DIR = ".contextcord"
LEGACY_STATE_DIR = ".harness"


def state_root(repo: Path) -> Path:
    """Return the canonical config root, for new and migrated projects."""
    repo = repo.resolve()
    requested = os.environ.get("CONTEXTCORD_STATE_DIR")
    candidates = ([requested] if requested else []) + [PRIMARY_STATE_DIR]
    seen: set[str] = set()
    for name in candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        root = repo / name
        if (root / "project.toml").is_file():
            return root
    raise ConfigError(f"missing {PRIMARY_STATE_DIR} directory in {repo}; run contextcord migrate for legacy state")


VALID_OPERATIONS = {
    "read", "write", "delete", "move", "test", "git", "checkpoint",
    "push", "release", "deploy", "tag", "force-push",
}


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return expand_string(value)
    if isinstance(value, list):
        return [_expand(x) for x in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_data(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    if path.is_symlink():
        raise ConfigError(f"trusted harness config must not be a symlink: {path}")
    suffix = path.suffix.lower()
    if suffix == ".toml":
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    elif suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ConfigError("YAML config requires optional PyYAML; use TOML/JSON for zero-dependency mode") from exc
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        raise ConfigError(f"unsupported config format: {path}")
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be an object/table: {path}")
    return _expand(data)


def _validate_regexes(evidence: dict[str, Any]) -> None:
    patterns = evidence.get("rules", {}).get("runner_redact_patterns", [])
    for pattern in patterns:
        try:
            re.compile(str(pattern))
        except re.error as exc:
            raise ConfigError(f"invalid runner_redact_patterns regex {pattern!r}: {exc}") from exc


def _legacy_truth(project: dict[str, Any], *, state_name: str = LEGACY_STATE_DIR) -> dict[str, Any]:
    """Compatibility bridge for a v0.2 project.toml that only had excludes.

    New profiles ship truth.toml. During shadow migration, old installs still load
    with a conservative source-default classifier and explicit ignore rules.
    """
    rules: list[dict[str, str]] = [
        {"pattern": f"{state_name}/generated/**", "kind": "generated"},
        {"pattern": f"{state_name}/receipts/**", "kind": "evidence"},
        {"pattern": f"{state_name}/dual-run/**", "kind": "evidence"},
    ]
    for pattern in project.get("fingerprint", {}).get("exclude", []):
        pattern = str(pattern)
        if pattern in {f"{state_name}/generated/**", f"{state_name}/receipts/**"}:
            continue
        rules.append({"pattern": pattern, "kind": "ignore"})
    return {"defaults": {"kind": "source"}, "rules": rules}


def _legacy_qualification(project: dict[str, Any], *, state_name: str = LEGACY_STATE_DIR) -> dict[str, Any]:
    q = project.get("qualification", {})
    default_ref = "refs/notes/contextcord"
    return {
        "notes_ref": str(q.get("notes_ref") or default_ref),
        "default_profile": "current-records",
        "profiles": {},
    }


def _repo_owned_entrypoint(value: str, *, label: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigError(f"{label} must be a repository-relative path without parent traversal: {value}")


def _trusted_repo_path(repo: Path, path: Path, *, label: str) -> tuple[Path, str]:
    """Translate trusted-boundary path failures into configuration errors.

    ``ensure_repo_path`` deliberately keeps its generic ``ValueError`` contract
    for callers that need to distinguish path validation failures.  Config
    discovery is a policy boundary, so the same failures must be surfaced as a
    stable ``ConfigError`` instead of leaking an implementation exception.
    """

    try:
        return ensure_repo_path(repo, path, label=label)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _validate_semantics(
    *,
    project: dict[str, Any],
    workflow: dict[str, Any],
    authority: dict[str, Any],
    runtime: dict[str, Any],
    evidence: dict[str, Any],
    qualification: dict[str, Any],
    state_name: str,
) -> None:
    knowledge = project.get("knowledge", {}).get("entrypoints", ["AGENTS.md"])
    policy = project.get("policy", {}).get("entrypoints", knowledge)
    if not isinstance(knowledge, list) or not all(isinstance(x, str) and x for x in knowledge):
        raise ConfigError("project.knowledge.entrypoints must be an array of non-empty strings")
    if not isinstance(policy, list) or not all(isinstance(x, str) and x for x in policy):
        raise ConfigError("project.policy.entrypoints must be an array of non-empty strings")
    for rel in [*knowledge, *policy]:
        _repo_owned_entrypoint(rel, label="trusted entrypoint")

    release_identity = project.get("release_identity", {})
    if not isinstance(release_identity, dict):
        raise ConfigError("project.release_identity must be a table")
    for key in ("dependency_files", "config_files", "migration_files", "required_patterns"):
        values = release_identity.get(key, [])
        if not isinstance(values, list) or not all(isinstance(x, str) and x for x in values):
            raise ConfigError(f"project.release_identity.{key} must be an array of strings")
        for pattern in values:
            _repo_owned_entrypoint(pattern, label=f"release_identity.{key}")

    dogfood = project.get("dogfood", {})
    required_classes = dogfood.get("required_task_classes", [])
    if not isinstance(required_classes, list) or not all(isinstance(x, str) and x for x in required_classes):
        raise ConfigError("project.dogfood.required_task_classes must be an array of strings")
    ledger_path = dogfood.get("ledger_path", f"{state_name}/dual-run/adjudications.json")
    if not isinstance(ledger_path, str) or not ledger_path:
        raise ConfigError("project.dogfood.ledger_path must be a non-empty string")
    _repo_owned_entrypoint(ledger_path, label="dogfood ledger_path")

    scopes = authority.get("scopes", {})
    if not isinstance(scopes, dict) or not scopes:
        raise ConfigError("authority.scopes must contain at least one scope")
    for scope_name, scope in scopes.items():
        if not isinstance(scope, dict):
            raise ConfigError(f"authority.scopes.{scope_name} must be a table")
        ops = scope.get("allow_operations", [])
        unknown = sorted({str(x) for x in ops} - VALID_OPERATIONS)
        if unknown:
            raise ConfigError(f"authority.scopes.{scope_name}.allow_operations contains unknown operations: {unknown}")
    for index, row in enumerate(authority.get("protected", [])):
        unknown = sorted({str(x) for x in row.get("operations", [])} - VALID_OPERATIONS)
        if unknown:
            raise ConfigError(f"authority.protected[{index}].operations contains unknown operations: {unknown}")

    required_scopes = [str(x) for x in runtime.get("required_scopes", [])]
    unknown_scopes = sorted(set(required_scopes) - set(scopes))
    if unknown_scopes:
        raise ConfigError(f"runtime.required_scopes contains unknown authority scopes: {unknown_scopes}")
    probes = runtime.get("probes", [])
    ids = [str(x.get("id")) for x in probes if isinstance(x, dict)]
    if len(ids) != len(set(ids)):
        raise ConfigError("runtime probe ids must be unique")
    probe_ids = set(ids)

    phases = {str(x.get("id")) for x in workflow.get("phases", []) if isinstance(x, dict)}
    for phase, contract in workflow.get("phase_contracts", {}).items():
        for probe_id in contract.get("required_runtime", []):
            if str(probe_id) not in probe_ids:
                raise ConfigError(f"workflow.phase_contracts.{phase} references unknown runtime probe: {probe_id}")
        profile = contract.get("require_qualification_profile")
        if profile and str(profile) != "current-records" and str(profile) not in qualification.get("profiles", {}):
            raise ConfigError(f"workflow.phase_contracts.{phase} references unknown qualification profile: {profile}")

    rules = evidence.get("rules", {})
    for key in ("receipt_dir", "runner_dir"):
        value = str(rules.get(key) or (f"{state_name}/receipts" if key == "receipt_dir" else f"{state_name}/generated/evidence"))
        _repo_owned_entrypoint(value, label=f"evidence.{key}")

    default_profile = str(qualification.get("default_profile") or "current-records")
    if default_profile != "current-records" and default_profile not in qualification.get("profiles", {}):
        raise ConfigError(f"qualification.default_profile is unknown: {default_profile}")


@dataclass(frozen=True)
class HarnessConfig:
    repo: Path
    root: Path
    project: dict[str, Any]
    truth: dict[str, Any]
    workflow: dict[str, Any]
    authority: dict[str, Any]
    runtime: dict[str, Any]
    evidence: dict[str, Any]
    qualification: dict[str, Any]

    @property
    def notes_ref(self) -> str:
        fallback = "refs/notes/contextcord"
        return str(self.qualification.get("notes_ref") or self.project.get("qualification", {}).get("notes_ref") or fallback)

    @property
    def identity_mode(self) -> str:
        return str(self.project.get("identity", {}).get("mode") or "content_equivalent")

    @property
    def fingerprint_excludes(self) -> list[str]:
        # Backward-compatibility property. New trust code uses truth.toml instead.
        values = self.project.get("fingerprint", {}).get("exclude", [f"{self.root.name}/**"])
        return [str(x) for x in values]

    @property
    def knowledge_entrypoints(self) -> list[str]:
        values = self.project.get("knowledge", {}).get("entrypoints", ["AGENTS.md"])
        return [str(x) for x in values]

    @property
    def policy_entrypoints(self) -> list[str]:
        values = self.project.get("policy", {}).get("entrypoints", self.knowledge_entrypoints)
        return [str(x) for x in values]

    @property
    def require_same_commit_as_truth(self) -> bool:
        return bool(self.project.get("memory", {}).get("require_same_commit_as_truth", False))

    @property
    def sealed_memory_on_verify(self) -> bool:
        return bool(self.project.get("memory", {}).get("sealed_on_verify", True))


def discover(repo: Path) -> HarnessConfig:
    repo = repo.resolve()
    root = state_root(repo)
    state_name = root.name
    _trusted_repo_path(repo, Path(state_name) / "project.toml", label="trusted_config")
    project = load_data(root / "project.toml")
    truth_path = root / "truth.toml"
    truth = load_data(truth_path) if truth_path.is_file() else _legacy_truth(project, state_name=state_name)
    workflow = load_data(root / "workflow.toml")
    authority = load_data(root / "authority.toml")
    runtime = load_data(root / "runtime.toml")
    evidence = load_data(root / "evidence.toml")
    qualification_path = root / "qualification.toml"
    qualification = load_data(qualification_path) if qualification_path.is_file() else _legacy_qualification(project, state_name=state_name)
    try:
        for name, value in [
            ("project", project), ("truth", truth), ("workflow", workflow),
            ("authority", authority), ("runtime", runtime), ("evidence", evidence),
            ("qualification", qualification),
        ]:
            validate(name, value)
    except ContractError as exc:
        raise ConfigError(str(exc)) from exc
    if str(project.get("identity", {}).get("mode") or "content_equivalent") not in {"content_equivalent", "exact_commit"}:
        raise ConfigError("project.identity.mode must be content_equivalent or exact_commit")
    _validate_regexes(evidence)
    _validate_semantics(project=project, workflow=workflow, authority=authority, runtime=runtime, evidence=evidence, qualification=qualification, state_name=state_name)
    # Trusted knowledge inputs cannot hide behind symlinks: policy drift must
    # observe the actual bytes named by the repository, not a host-side target.
    trusted_entries = set(project.get("knowledge", {}).get("entrypoints", ["AGENTS.md"])) | set(project.get("policy", {}).get("entrypoints", project.get("knowledge", {}).get("entrypoints", ["AGENTS.md"])))
    for rel in trusted_entries:
        p, _ = _trusted_repo_path(repo, Path(str(rel)), label="trusted_entrypoint")
        if p.is_symlink():
            raise ConfigError(f"trusted knowledge/policy entrypoint must not be a symlink: {rel}")
    return HarnessConfig(
        repo=repo,
        root=root,
        project=project,
        truth=truth,
        workflow=workflow,
        authority=authority,
        runtime=runtime,
        evidence=evidence,
        qualification=qualification,
    )
