from __future__ import annotations

from typing import Any

from .config import HarnessConfig
from .contracts import validate
from .fingerprint import policy_fingerprint
from .gitops import head, tree
from .truth import content_fingerprint, dirty_truth_paths, latest_commit_for_kinds, memory_fingerprint
from .util import sha256_json


def source_identity(cfg: HarnessConfig, *, include_files: bool = False) -> dict[str, Any]:
    truth = content_fingerprint(cfg, include_files=include_files)
    memory = memory_fingerprint(cfg, include_files=include_files)
    policy = policy_fingerprint(cfg.repo, cfg.policy_entrypoints)
    value: dict[str, Any] = {
        "schema": "contextcord-source-identity-v1",
        "mode": cfg.identity_mode,
        "git_commit": head(cfg.repo),
        "git_tree": tree(cfg.repo),
        "truth_fingerprint": truth,
        "policy_fingerprint": policy,
        "memory_fingerprint": memory,
        "dirty_truth": dirty_truth_paths(cfg),
    }
    value["identity_sha256"] = sha256_json(value, exclude_keys=("identity_sha256",))
    validate("source-identity", value)
    return value


def memory_commit_errors(cfg: HarnessConfig) -> list[str]:
    if not cfg.require_same_commit_as_truth:
        return []
    source_commit = latest_commit_for_kinds(cfg, ("source", "runtime_input"))
    memory_commit = latest_commit_for_kinds(cfg, ("durable_memory",))
    if source_commit and source_commit != memory_commit:
        return [f"code_memory_commit_mismatch:{source_commit[:12]}!={str(memory_commit)[:12]}"]
    return []


def exact_closeout_errors(cfg: HarnessConfig, identity: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if cfg.identity_mode == "exact_commit" and identity.get("dirty_truth"):
        errors.append("exact_commit_requires_clean_truth:" + ",".join(identity["dirty_truth"][:20]))
    errors.extend(memory_commit_errors(cfg))
    return errors


def compare_identity(current: dict[str, Any], sealed: dict[str, Any], *, sealed_memory: bool = True) -> list[str]:
    errors: list[str] = []
    if current.get("truth_fingerprint", {}).get("sha256") != sealed.get("truth_fingerprint", {}).get("sha256"):
        errors.append("project_truth_changed_since_closeout")
    mode = sealed.get("mode") or current.get("mode")
    if mode == "exact_commit" and current.get("git_commit") != sealed.get("git_commit"):
        errors.append(f"exact_commit_mismatch:{sealed.get('git_commit')}!={current.get('git_commit')}")
    if current.get("policy_fingerprint", {}).get("sha256") != sealed.get("policy_fingerprint", {}).get("sha256"):
        errors.append("policy_changed_since_closeout")
    if sealed_memory and current.get("memory_fingerprint", {}).get("sha256") != sealed.get("memory_fingerprint", {}).get("sha256"):
        errors.append("durable_memory_changed_since_closeout")
    return errors
