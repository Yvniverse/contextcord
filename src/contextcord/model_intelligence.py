"""Optional read-only model-intelligence providers.

CodexRadar is an advisory prior only.  This module never logs in, claims a
task, writes to a provider, or receives a Codex credential.  Raw snapshots are
cached only in the local ContextCord state directory and callers should persist
derived metrics, not the payload.
"""

from __future__ import annotations

import json
import math
import statistics
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CODEXRADAR_URL = "https://api.codexradar.com/api/v1/table?benchmark=deep-swe"
ALLOWED_MODELS = {"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"}
ALLOWED_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
DEFAULT_TTL_SECONDS = 600
DEFAULT_MAX_STALE_SECONDS = 86400
DEFAULT_TIMEOUT_SECONDS = 3.0
ATTRIBUTION = "Data source: Codex Radar / Distributed Radar — DeepSWE"


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def default_cache_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / ".contextcord" / "cache" / "model-intelligence" / "codexradar.json"


def _read_cache(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_cache(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def fetch_codexradar_table(
    *,
    url: str = DEFAULT_CODEXRADAR_URL,
    cache_path: str | Path | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    max_stale_seconds: int = DEFAULT_MAX_STALE_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    now: float | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Fetch the public read-only table with bounded cache fallback.

    The returned status is one of ``LIVE``, ``FRESH_CACHE``, ``STALE_CACHE``
    or ``UNAVAILABLE``.  Failure is deliberately non-blocking for routing.
    """

    started = time.monotonic()
    now = time.time() if now is None else float(now)
    path = Path(cache_path).expanduser().resolve() if cache_path else None
    cached = _read_cache(path)
    if cached and not refresh:
        fetched_at = _numeric(cached.get("fetched_at")) or 0.0
        age = max(0.0, now - fetched_at)
        payload = cached.get("payload")
        if age <= ttl_seconds and isinstance(payload, dict):
            return {
                "status": "FRESH_CACHE",
                "payload": payload,
                "retrieved_at": fetched_at,
                "age_seconds": age,
                "source_url": url,
                "raw_payload_committed": False,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
            }

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ContextCord-model-intelligence/0.6.2a1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("codexradar_payload_must_be_object")
        if path:
            _write_cache(path, {"fetched_at": now, "payload": payload})
        return {
            "status": "LIVE",
            "payload": payload,
            "retrieved_at": now,
            "age_seconds": 0.0,
            "source_url": url,
            "raw_payload_committed": False,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
        }
    except Exception as exc:  # noqa: BLE001 - provider failures are advisory.
        if cached and isinstance(cached.get("payload"), dict):
            fetched_at = _numeric(cached.get("fetched_at")) or 0.0
            age = max(0.0, now - fetched_at)
            if age <= max_stale_seconds:
                return {
                    "status": "STALE_CACHE",
                    "payload": cached["payload"],
                    "retrieved_at": fetched_at,
                    "age_seconds": age,
                    "source_url": url,
                    "error": type(exc).__name__,
                    "raw_payload_committed": False,
                    "latency_ms": round((time.monotonic() - started) * 1000, 3),
                }
        return {
            "status": "UNAVAILABLE",
            "payload": None,
            "retrieved_at": None,
            "age_seconds": None,
            "source_url": url,
            "error": type(exc).__name__,
            "raw_payload_committed": False,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
        }


def aggregate_codexradar(table: Mapping[str, Any], *, agent: str = "codex") -> dict[str, Any]:
    """Convert a table payload into derived GPT-5.6 route priors."""

    cells = table.get("cells")
    if not isinstance(cells, Mapping):
        return {
            "schema": "contextcord-codexradar-derived-v1",
            "benchmark_id": table.get("benchmark_id"),
            "routes": [],
            "attribution": ATTRIBUTION,
        }

    grouped: dict[tuple[str, str], dict[str, list[float] | int]] = {}
    for key, raw in cells.items():
        if not isinstance(key, str) or not isinstance(raw, Mapping):
            continue
        try:
            _task_id, model, effort = key.split("|", 2)
        except ValueError:
            continue
        model = model.casefold()
        effort = effort.casefold()
        if model not in ALLOWED_MODELS or effort not in ALLOWED_EFFORTS:
            continue
        raw_agent = str(raw.get("agent") or "").casefold()
        if raw_agent and raw_agent != agent.casefold():
            continue
        bucket = grouped.setdefault(
            (model, effort), {"rates": [], "costs": [], "minutes": [], "quota": [], "runs": 0}
        )
        rate = _numeric(raw.get("rate"))
        if rate is None:
            percentage = _numeric(raw.get("p"))
            if percentage is not None:
                rate = percentage / 100.0 if percentage > 1 else percentage
        if rate is not None and 0 <= rate <= 1:
            bucket["rates"].append(rate)  # type: ignore[index]
        cost = _numeric(raw.get("cost"))
        if cost is not None and cost >= 0:
            bucket["costs"].append(cost)  # type: ignore[index]
        minutes = _numeric(raw.get("min"))
        if minutes is not None and minutes >= 0:
            bucket["minutes"].append(minutes)  # type: ignore[index]
        quota = _numeric(raw.get("est_quota_pct"))
        if quota is not None and quota >= 0:
            bucket["quota"].append(quota)  # type: ignore[index]
        total_n = raw.get("total_n")
        if isinstance(total_n, int) and not isinstance(total_n, bool) and total_n >= 0:
            bucket["runs"] = int(bucket["runs"]) + total_n

    routes: list[dict[str, Any]] = []
    for (model, effort), bucket in sorted(grouped.items()):
        rates = list(bucket["rates"])  # type: ignore[arg-type]
        if not rates:
            continue
        mean_rate = sum(rates) / len(rates)
        routes.append({
            "model_id": model,
            "reasoning_effort": effort,
            "task_equal_pass_rate": mean_rate,
            "iq_equivalent": round(mean_rate * 150.0, 3),
            "task_count": len(rates),
            "run_count": int(bucket["runs"]),
            "median_api_equivalent_cost_usd": _median(list(bucket["costs"])),  # type: ignore[arg-type]
            "median_duration_minutes": _median(list(bucket["minutes"])),  # type: ignore[arg-type]
            "median_estimated_quota_pct": _median(list(bucket["quota"])),  # type: ignore[arg-type]
        })
    return {
        "schema": "contextcord-codexradar-derived-v1",
        "benchmark_id": table.get("benchmark_id"),
        "routes": routes,
        "attribution": ATTRIBUTION,
        "raw_payload_committed": False,
    }


def model_intelligence_snapshot(
    result: Mapping[str, Any],
    *,
    derived: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the persisted, derived-only receipt shape."""

    return {
        "schema": "contextcord-model-intelligence-snapshot-v1",
        "source": "CodexRadar / Distributed Radar",
        "retrieved_at": result.get("retrieved_at"),
        "status": result.get("status", "UNAVAILABLE"),
        "benchmark": (derived or {}).get("benchmark_id"),
        "routes": list((derived or {}).get("routes") or []),
        "attribution": ATTRIBUTION,
        "raw_payload_committed": False,
        "age_seconds": result.get("age_seconds"),
        "source_url": result.get("source_url", DEFAULT_CODEXRADAR_URL),
        "latency_ms": result.get("latency_ms"),
        "external_route_count": len(list((derived or {}).get("routes") or [])),
        "cache_status": result.get("status", "UNAVAILABLE"),
    }


def load_codexradar_prior(
    project_root: str | Path,
    *,
    enabled: bool = False,
    private_dogfood: bool | None = None,
    now: float | None = None,
    **fetch_options: Any,
) -> dict[str, Any]:
    """Load an opt-in derived prior; public/default routing stays disabled.

    ``private_dogfood`` remains accepted for receipt compatibility but is no
    longer a product hard gate.  The caller's explicit provider/capability
    configuration is the sole enablement decision.
    """

    if not enabled:
        return {
            "schema": "contextcord-model-intelligence-snapshot-v1",
            "source": "CodexRadar / Distributed Radar",
            "retrieved_at": None,
            "status": "UNAVAILABLE",
            "benchmark": None,
            "routes": [],
            "attribution": ATTRIBUTION,
            "raw_payload_committed": False,
            "reason": "disabled_by_default_or_public_release",
        }
    options = dict(fetch_options)
    options.setdefault("cache_path", default_cache_path(project_root))
    if now is not None:
        options["now"] = now
    result = fetch_codexradar_table(**options)
    derived = aggregate_codexradar(result.get("payload") or {}) if isinstance(result.get("payload"), Mapping) else {}
    return model_intelligence_snapshot(result, derived=derived)


__all__ = [
    "ALLOWED_EFFORTS",
    "ALLOWED_MODELS",
    "ATTRIBUTION",
    "DEFAULT_CODEXRADAR_URL",
    "aggregate_codexradar",
    "default_cache_path",
    "fetch_codexradar_table",
    "load_codexradar_prior",
    "model_intelligence_snapshot",
]
