from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .gitops import head


def _field(value: Any, dotted: str) -> Any:
    cur = value
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def run_probes(repo: Path, runtime_cfg: dict[str, Any], *, scope: str | None = None) -> dict[str, Any]:
    expected_head = head(repo)
    results = []
    for row in runtime_cfg.get("probes", []):
        probe = dict(row); pid = str(probe.get("id", "probe")); kind = str(probe.get("kind", "http_json")); required = bool(probe.get("required", False))
        result: dict[str, Any] = {"id": pid, "kind": kind, "required": required, "status": "UNKNOWN"}
        try:
            if kind == "http_json":
                req = urllib.request.Request(str(probe["url"]), headers={"User-Agent": "contextcord/0.6"})
                with urllib.request.urlopen(req, timeout=float(probe.get("timeout", 2.0))) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                observed = _field(payload, str(probe.get("revision_field", "revision")))
                result.update({"reachable": True, "observed_revision": observed, "payload": payload})
            elif kind == "file_json":
                p = Path(str(probe["path"])); p = p if p.is_absolute() else repo / p
                payload = json.loads(p.read_text(encoding="utf-8")); observed = _field(payload, str(probe.get("revision_field", "revision")))
                result.update({"reachable": True, "observed_revision": observed, "path": str(p)})
            elif kind == "command_json":
                proc = subprocess.run([str(x) for x in probe["command"]], cwd=repo, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=float(probe.get("timeout", 10.0)), shell=False)
                if proc.returncode != 0:
                    raise ValueError(f"command_json_exit:{proc.returncode}:{proc.stderr.strip()[:200]}")
                payload = json.loads(proc.stdout); observed = _field(payload, str(probe.get("revision_field", "revision")))
                result.update({"reachable": True, "observed_revision": observed, "payload": payload})
            else:
                raise ValueError(f"unsupported probe kind: {kind}")
            expected = probe.get("expected", "HEAD"); expected_value = expected_head if expected == "HEAD" else str(expected)
            exact = (not probe.get("revision_field")) or result.get("observed_revision") == expected_value
            result.update({"expected_revision": expected_value, "exact_match": exact, "status": "PASS" if exact else "FAIL"})
        except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError, TimeoutError, subprocess.TimeoutExpired) as exc:
            result.update({"reachable": False, "status": "BLOCKED" if required else "NOT_AVAILABLE", "error": str(exc)})
        results.append(result)
    required_by_scope = scope is not None and scope in {str(x) for x in runtime_cfg.get("required_scopes", [])}
    hard = [r for r in results if (r.get("required") or required_by_scope) and r.get("status") != "PASS"]
    if hard:
        overall = "BLOCKED"
    elif not results:
        overall = "PASS"
    elif any(r.get("status") == "FAIL" for r in results):
        overall = "STALE"
    elif all(r.get("status") == "PASS" for r in results):
        overall = "PASS"
    elif all(r.get("status") == "NOT_AVAILABLE" for r in results):
        overall = "NOT_AVAILABLE"
    else:
        overall = "DEGRADED"
    return {"expected_head": expected_head, "scope": scope, "required_by_scope": required_by_scope, "status": overall, "probes": results}
