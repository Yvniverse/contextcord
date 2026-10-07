from __future__ import annotations

from typing import Any

from .config import HarnessConfig
from .gitops import branch, head, status_porcelain, upstream, upstream_head
from .identity import source_identity
from .runtime import run_probes
from .store import StateStore
from .truth import classification_counts


def resolve_context(cfg: HarnessConfig, store: StateStore, *, task_id: str | None = None, include_fingerprint: bool = False) -> dict[str, Any]:
    repo = cfg.repo; task = store.get_task(task_id) if task_id else None
    knowledge = []
    for rel in cfg.knowledge_entrypoints:
        p = repo / rel
        knowledge.append({"path": rel, "exists": p.is_file() and not p.is_symlink(), "bytes": p.stat().st_size if p.is_file() and not p.is_symlink() else None})
    runtime = run_probes(repo, cfg.runtime, scope=str(task.get("scope")) if task else None)
    value: dict[str, Any] = {
        "project": {"name": cfg.project.get("project", {}).get("name", repo.name), "repo": str(repo), "identity_mode": cfg.identity_mode},
        "git": {"branch": branch(repo), "head": head(repo), "dirty": bool(status_porcelain(repo)), "status": status_porcelain(repo).splitlines(), "upstream": upstream(repo), "upstream_head": upstream_head(repo)},
        "task": task,
        "knowledge": knowledge,
        "runtime": runtime,
        "open_sessions": store.open_sessions(task_id),
        "classification_counts": classification_counts(cfg),
        "event_chain_head": store.event_chain_head(),
        "receipt_chain_head": store.receipt_head(),
    }
    if include_fingerprint:
        value["source_identity"] = source_identity(cfg, include_files=False)
    return value


def render_context(value: dict[str, Any]) -> str:
    git = value["git"]; task = value.get("task") or {}; runtime = value.get("runtime") or {}
    lines = [
        "CONTEXTCORD",
        f"project      {value['project']['name']}",
        f"repo         {value['project']['repo']}",
        f"identity     {value['project'].get('identity_mode')}",
        "", "git",
        f"  branch     {git['branch']}", f"  head       {git['head']}", f"  dirty      {'YES' if git['dirty'] else 'NO'}",
        f"  upstream   {git.get('upstream') or '-'}", f"  upstream#  {git.get('upstream_head') or '-'}", "",
    ]
    if task:
        lines += ["task", f"  id         {task.get('task_id')}", f"  scope      {task.get('scope')}", f"  status     {task.get('status')}", f"  phase      {task.get('current_phase') or '-'}", f"  next       {task.get('next_action') or '-'}", f"  blockers   {len(task.get('blockers', []))}", ""]
    lines += ["runtime", f"  status     {runtime.get('status', 'UNKNOWN')}"]
    for probe in runtime.get("probes", []):
        lines.append(f"  {probe.get('id')}   {probe.get('status')} observed={probe.get('observed_revision') or '-'} expected={probe.get('expected_revision') or '-'}")
    missing = [x["path"] for x in value.get("knowledge", []) if not x["exists"]]
    lines += ["", f"knowledge    {'PASS' if not missing else 'BLOCKED'}"]
    if missing:
        lines.append("  missing    " + ", ".join(missing))
    lines += ["", f"event head   {value.get('event_chain_head') or '-'}", f"receipt head {value.get('receipt_chain_head') or '-'}"]
    return "\n".join(lines)
