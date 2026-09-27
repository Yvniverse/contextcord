from __future__ import annotations

import fnmatch
import hashlib
import json
import posixpath
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .build_identity import build_identity
from .contracts import validate
from .gitops import git_dir
from .util import canonical_json, utc_now

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  status TEXT NOT NULL,
  start_head TEXT NOT NULL,
  start_fingerprint TEXT NOT NULL,
  start_policy_fingerprint TEXT,
  start_identity_sha256 TEXT,
  started_at TEXT NOT NULL,
  finish_fingerprint TEXT,
  finish_policy_fingerprint TEXT,
  finish_identity_sha256 TEXT,
  end_head TEXT,
  closed_at TEXT,
  summary_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_task_status ON sessions(task_id, status);
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  status TEXT NOT NULL,
  current_phase TEXT,
  completed_json TEXT NOT NULL,
  blockers_json TEXT NOT NULL,
  next_action TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT UNIQUE NOT NULL,
  session_id TEXT,
  task_id TEXT,
  event_type TEXT NOT NULL,
  ts TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  prev_hash TEXT,
  event_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leases (
  lease_key TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  path TEXT,
  sha256 TEXT,
  revision TEXT,
  source_identity_sha256 TEXT,
  metadata_json TEXT NOT NULL,
  recorded_at TEXT
);
CREATE TABLE IF NOT EXISTS notes (
  note_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  session_id TEXT,
  text TEXT NOT NULL,
  depends_json TEXT NOT NULL,
  dependency_fingerprints_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_task ON notes(task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notes_session ON notes(session_id, created_at);
CREATE TABLE IF NOT EXISTS context_jobs (
  job_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  session_id TEXT,
  provider TEXT NOT NULL,
  status TEXT NOT NULL,
  packet_json TEXT NOT NULL,
  archive_refs_json TEXT NOT NULL,
  source_identity_sha256 TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_context_jobs_task ON context_jobs(task_id, created_at);
CREATE TABLE IF NOT EXISTS memory_events (
  source_event_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  session_id TEXT,
  event_type TEXT NOT NULL,
  ts TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  prev_hash TEXT,
  event_hash TEXT NOT NULL,
  source_bundle_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_events_task ON memory_events(task_id, ts);
CREATE TABLE IF NOT EXISTS portable_imports (
  bundle_sha256 TEXT PRIMARY KEY,
  schema TEXT NOT NULL,
  task_id TEXT NOT NULL,
  source_identity_json TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  object_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS receipt_index (
  receipt_hash TEXT PRIMARY KEY,
  previous_hash TEXT,
  path TEXT NOT NULL,
  session_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_outcomes (
  outcome_id TEXT PRIMARY KEY,
  task_id TEXT,
  task_class TEXT NOT NULL,
  role TEXT NOT NULL,
  model_id TEXT NOT NULL,
  reasoning_effort TEXT NOT NULL,
  identity_evidence TEXT NOT NULL DEFAULT 'confirmed',
  context_profile TEXT,
  source_identity_sha256 TEXT,
  route_decision_receipt_sha256 TEXT,
  verifier_id TEXT,
  verifier_pass INTEGER NOT NULL,
  attempts INTEGER NOT NULL,
  elapsed_ms REAL,
  input_tokens INTEGER,
  output_tokens INTEGER,
  observed_subscription_quota_delta REAL,
  api_equivalent_usd REAL,
  external_prior_source TEXT,
  external_prior_age_seconds REAL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_outcomes_route ON model_outcomes(model_id, reasoning_effort, role, created_at);
CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def _selector(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    if ".." in Path(raw).parts:
        raise ValueError("lease selector parent traversal is forbidden")
    m = re.match(r"^/mnt/([A-Za-z])/(.*)$", raw)
    if m:
        raw = f"{m.group(1).lower()}:/{m.group(2)}"
    m = re.match(r"^/run/desktop/mnt/host/([A-Za-z])/(.*)$", raw)
    if m:
        raw = f"{m.group(1).lower()}:/{m.group(2)}"
    if re.match(r"^[A-Za-z]:/", raw):
        raw = raw[0].lower() + raw[1:]
    return raw.lstrip("./")


def _literal_prefix(pattern: str) -> str:
    stop = len(pattern)
    for token in ("*", "?", "["):
        idx = pattern.find(token)
        if idx >= 0:
            stop = min(stop, idx)
    return pattern[:stop].rstrip("/")


def lease_keys_overlap(a: str, b: str) -> bool:
    a = _selector(a); b = _selector(b)
    if a == b or fnmatch.fnmatchcase(a, b) or fnmatch.fnmatchcase(b, a):
        return True
    pa, pb = _literal_prefix(a), _literal_prefix(b)
    if not pa or not pb:
        return True  # global/ambiguous selector: conservative conflict
    return pa == pb or pa.startswith(pb + "/") or pb.startswith(pa + "/")


def atomic(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.transaction():
            return method(self, *args, **kwargs)
    return wrapped


class StateStore:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        # ContextCord keeps its primary local state beside its config.  The
        # legacy Git-dir location remains readable for un-migrated Harness
        # projects and is intentionally not copied implicitly.
        contextcord_root = self.repo / ".contextcord"
        if (contextcord_root / "project.toml").is_file():
            self.path = contextcord_root / "state.db"
        else:
            self.path = git_dir(self.repo) / "project-harness" / "state.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        # Setting WAL can report SQLITE_BUSY immediately during concurrent first
        # opens, even with busy_timeout. Retry only initialization lock contention.
        deadline = time.monotonic() + 30
        while True:
            try:
                self.conn.executescript(SCHEMA)
                with self.transaction():
                    self._migrate()
                    self.conn.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('store_id',?)", (str(uuid.uuid4()),))
                break
            except sqlite3.OperationalError as exc:
                if 'locked' not in str(exc).lower() or time.monotonic() >= deadline:
                    self.conn.close()
                    raise
                time.sleep(.05)

    def _migrate(self) -> None:
        session_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(sessions)")}
        for name, sql_type in [
            ("start_build_sha256", "TEXT"), ("start_policy_fingerprint", "TEXT"), ("finish_policy_fingerprint", "TEXT"),
            ("start_identity_sha256", "TEXT"), ("finish_identity_sha256", "TEXT"),
        ]:
            if name not in session_cols:
                self.conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {sql_type}")
        evidence_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(evidence)")}
        if "source_identity_sha256" not in evidence_cols:
            self.conn.execute("ALTER TABLE evidence ADD COLUMN source_identity_sha256 TEXT")
        if "recorded_at" not in evidence_cols:
            self.conn.execute("ALTER TABLE evidence ADD COLUMN recorded_at TEXT")
        if "portable_id" not in evidence_cols:
            self.conn.execute("ALTER TABLE evidence ADD COLUMN portable_id TEXT")
        self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_portable_id ON evidence(portable_id) WHERE portable_id IS NOT NULL")
        outcome_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(model_outcomes)")}
        if "identity_evidence" not in outcome_cols:
            self.conn.execute("ALTER TABLE model_outcomes ADD COLUMN identity_evidence TEXT NOT NULL DEFAULT 'confirmed'")

    @contextmanager
    def transaction(self):
        nested = self.conn.in_transaction
        if not nested:
            self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self
            if not nested:
                self.conn.execute("COMMIT")
        except BaseException:
            if not nested and self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

    @property
    def store_id(self):
        return self.conn.execute("SELECT value FROM metadata WHERE key='store_id'").fetchone()[0]

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @atomic
    def event(self, event_type: str, payload: dict[str, Any], *, session_id: str | None = None, task_id: str | None = None) -> str:
        """Atomically append one event and advance the event hash chain.

        BEGIN IMMEDIATE serializes writers so two processes cannot read the same
        chain head and fork the local event history.
        """
        event_id = str(uuid.uuid4()); ts = utc_now()
        try:
            last = self.conn.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            prev = last[0] if last else None
            body = {"event_id": event_id, "session_id": session_id, "task_id": task_id, "event_type": event_type, "ts": ts, "payload": payload, "prev_hash": prev}
            validate("event", {**body, "event_hash": "0" * 64})
            event_hash = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
            self.conn.execute(
                "INSERT INTO events(event_id,session_id,task_id,event_type,ts,payload_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?)",
                (event_id, session_id, task_id, event_type, ts, canonical_json(payload), prev, event_hash),
            )
        except Exception:
            raise
        return event_id

    def event_chain_head(self) -> str | None:
        row = self.conn.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return str(row[0]) if row else None

    def event_hash_exists(self, event_hash: str | None) -> bool:
        if not event_hash:
            return True
        row = self.conn.execute("SELECT 1 FROM events WHERE event_hash=?", (event_hash,)).fetchone()
        return row is not None

    def verify_event_chain(self) -> tuple[bool, str | None]:
        prev = None
        for row in self.conn.execute("SELECT * FROM events ORDER BY seq"):
            try:
                payload = json.loads(row["payload_json"])
            except (ValueError, TypeError):
                return False, row["event_id"]
            body = {"event_id": row["event_id"], "session_id": row["session_id"], "task_id": row["task_id"], "event_type": row["event_type"], "ts": row["ts"], "payload": payload, "prev_hash": row["prev_hash"]}
            expected = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
            try:
                validate("event", {**body, "event_hash": row["event_hash"]})
            except Exception:
                return False, row["event_id"]
            if row["prev_hash"] != prev or row["event_hash"] != expected:
                return False, row["event_id"]
            prev = row["event_hash"]
        return True, None

    @atomic
    def create_session(self, *, task_id: str, scope: str, head: str, fingerprint: str, policy_fingerprint: str | None = None, source_identity_sha256: str | None = None, session_id: str | None = None) -> str:
        session_id = session_id or f"s-{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            "INSERT INTO sessions(session_id,task_id,scope,status,start_head,start_fingerprint,start_policy_fingerprint,start_identity_sha256,started_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (session_id, task_id, scope, "OPEN", head, fingerprint, policy_fingerprint, source_identity_sha256, utc_now()),
        )
        self.conn.execute("UPDATE sessions SET start_build_sha256=? WHERE session_id=?", (build_identity()["sha256"], session_id))
        self.event("SESSION_STARTED", {"scope": scope, "head": head, "fingerprint": fingerprint, "policy_fingerprint": policy_fingerprint, "source_identity_sha256": source_identity_sha256}, session_id=session_id, task_id=task_id)
        return session_id

    def session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def open_sessions(self, task_id: str | None = None) -> list[dict[str, Any]]:
        if task_id:
            rows = self.conn.execute("SELECT * FROM sessions WHERE status='OPEN' AND task_id=? ORDER BY started_at", (task_id,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM sessions WHERE status='OPEN' ORDER BY started_at").fetchall()
        return [dict(r) for r in rows]

    @atomic
    def close_session(self, session_id: str, *, fingerprint: str, end_head: str, summary: dict[str, Any], policy_fingerprint: str | None = None, source_identity_sha256: str | None = None, status: str = "CLOSED") -> None:
        rec = self.session(session_id)
        if not rec or rec["status"] != "OPEN":
            raise RuntimeError(f"session_not_open: {session_id}")
        self.conn.execute(
            "UPDATE sessions SET status=?,finish_fingerprint=?,finish_policy_fingerprint=?,finish_identity_sha256=?,end_head=?,closed_at=?,summary_json=? WHERE session_id=?",
            (status, fingerprint, policy_fingerprint, source_identity_sha256, end_head, utc_now(), canonical_json(summary), session_id),
        )
        self.conn.execute("DELETE FROM leases WHERE session_id=?", (session_id,))
        self.event("SESSION_FINISHED", {"status": status, "fingerprint": fingerprint, "policy_fingerprint": policy_fingerprint, "source_identity_sha256": source_identity_sha256, "end_head": end_head}, session_id=session_id, task_id=rec["task_id"])

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        value = dict(row); value["completed"] = json.loads(value.pop("completed_json")); value["blockers"] = json.loads(value.pop("blockers_json"))
        return value

    @atomic
    def upsert_task(self, value: dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT INTO tasks(task_id,scope,status,current_phase,completed_json,blockers_json,next_action,updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(task_id) DO UPDATE SET scope=excluded.scope,status=excluded.status,current_phase=excluded.current_phase,
               completed_json=excluded.completed_json,blockers_json=excluded.blockers_json,next_action=excluded.next_action,updated_at=excluded.updated_at""",
            (value["task_id"], value["scope"], value["status"], value.get("current_phase"), canonical_json(value.get("completed", [])), canonical_json(value.get("blockers", [])), value.get("next_action", ""), utc_now()),
        )

    def active_tasks(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM tasks WHERE status IN ('ACTIVE','READY_TO_FINISH') ORDER BY updated_at DESC").fetchall()
        out = []
        for row in rows:
            value = dict(row); value["completed"] = json.loads(value.pop("completed_json")); value["blockers"] = json.loads(value.pop("blockers_json")); out.append(value)
        return out

    def latest_closed_session(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE status LIKE 'CLOSED%' ORDER BY closed_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    @atomic
    def add_evidence(self, *, session_id: str, task_id: str, name: str, status: str, path: str | None, sha256: str | None, revision: str | None, source_identity_sha256: str | None = None, metadata: dict[str, Any] | None = None, portable_id: str | None = None, recorded_at: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO evidence(session_id,task_id,name,status,path,sha256,revision,source_identity_sha256,metadata_json,recorded_at,portable_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, task_id, name, status, path, sha256, revision, source_identity_sha256, canonical_json(metadata or {}), recorded_at or utc_now(), portable_id),
        )
        self.event("EVIDENCE_RECORDED", {"name": name, "status": status, "path": path, "sha256": sha256, "revision": revision, "source_identity_sha256": source_identity_sha256}, session_id=session_id, task_id=task_id)

    def evidence_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM evidence WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
        out = []
        for row in rows:
            value = dict(row); value["metadata"] = json.loads(value.pop("metadata_json")); out.append(value)
        return out

    def evidence_for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM evidence WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        out = []
        for row in rows:
            value = dict(row); value["metadata"] = json.loads(value.pop("metadata_json")); out.append(value)
        return out

    def evidence_by_portable_id(self, portable_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM evidence WHERE portable_id=?", (portable_id,)).fetchone()
        if not row:
            return None
        value = dict(row); value["metadata"] = json.loads(value.pop("metadata_json")); return value

    @atomic
    def record_model_outcome(
        self,
        *,
        task_class: str,
        role: str,
        model_id: str,
        reasoning_effort: str,
        verifier_pass: bool,
        identity_evidence: str = "confirmed",
        attempts: int = 1,
        context_profile: str | None = None,
        source_identity_sha256: str | None = None,
        route_decision_receipt_sha256: str | None = None,
        verifier_id: str | None = None,
        elapsed_ms: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        observed_subscription_quota_delta: float | None = None,
        api_equivalent_usd: float | None = None,
        external_prior_source: str | None = None,
        external_prior_age_seconds: float | None = None,
        task_id: str | None = None,
        outcome_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        """Append one route outcome without storing prompt or credential data."""

        try:
            attempts = int(attempts)
        except (TypeError, ValueError) as exc:
            raise ValueError("model_outcome_attempts_invalid") from exc
        if attempts < 1:
            raise ValueError("model_outcome_attempts_must_be_positive")
        identity_evidence = str(identity_evidence).casefold()
        if identity_evidence not in {"confirmed", "configured_explicit", "host_only"}:
            raise ValueError("model_outcome_identity_evidence_invalid")
        if input_tokens is not None:
            input_tokens = int(input_tokens)
            if input_tokens < 0:
                raise ValueError("model_outcome_input_tokens_invalid")
        if output_tokens is not None:
            output_tokens = int(output_tokens)
            if output_tokens < 0:
                raise ValueError("model_outcome_output_tokens_invalid")
        outcome_id = outcome_id or f"o-{uuid.uuid4().hex[:12]}"
        value = {
            "schema": "contextcord-model-route-outcome-v1",
            "outcome_id": str(outcome_id),
            "task_id": None if task_id is None else str(task_id),
            "task_class": str(task_class),
            "role": str(role),
            "model_id": str(model_id),
            "reasoning_effort": str(reasoning_effort).casefold(),
            "identity_evidence": identity_evidence,
            "context_profile": None if context_profile is None else str(context_profile),
            "source_identity_sha256": source_identity_sha256,
            "route_decision_receipt_sha256": route_decision_receipt_sha256,
            "verifier_id": None if verifier_id is None else str(verifier_id),
            "verifier_pass": bool(verifier_pass),
            "attempts": attempts,
            "elapsed_ms": elapsed_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "observed_subscription_quota_delta": observed_subscription_quota_delta,
            "api_equivalent_usd": api_equivalent_usd,
            "external_prior_source": external_prior_source,
            "external_prior_age_seconds": external_prior_age_seconds,
            "created_at": created_at or utc_now(),
        }
        validate("model-route-outcome", value)
        self.conn.execute(
            """INSERT INTO model_outcomes(
                outcome_id,task_id,task_class,role,model_id,reasoning_effort,
                identity_evidence,context_profile,source_identity_sha256,route_decision_receipt_sha256,
                verifier_id,verifier_pass,attempts,elapsed_ms,input_tokens,output_tokens,
                observed_subscription_quota_delta,api_equivalent_usd,external_prior_source,
                external_prior_age_seconds,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                value["outcome_id"], value["task_id"], value["task_class"], value["role"],
                value["model_id"], value["reasoning_effort"], value["identity_evidence"], value["context_profile"],
                value["source_identity_sha256"], value["route_decision_receipt_sha256"],
                value["verifier_id"], int(value["verifier_pass"]), value["attempts"],
                value["elapsed_ms"], value["input_tokens"], value["output_tokens"],
                value["observed_subscription_quota_delta"], value["api_equivalent_usd"],
                value["external_prior_source"], value["external_prior_age_seconds"],
                value["created_at"],
            ),
        )
        self.event(
            "MODEL_ROUTE_OUTCOME_RECORDED",
            {
                "outcome_id": value["outcome_id"],
                "task_class": value["task_class"],
                "role": value["role"],
                "model_id": value["model_id"],
                "reasoning_effort": value["reasoning_effort"],
                "identity_evidence": value["identity_evidence"],
                "verifier_pass": value["verifier_pass"],
            },
            task_id=task_id,
        )
        return value

    def model_outcomes(
        self,
        *,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
        role: str | None = None,
        task_class: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("model_id", model_id),
            ("reasoning_effort", reasoning_effort),
            ("role", role),
            ("task_class", task_class),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(str(value))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        limit = max(1, min(int(limit), 10000))
        rows = self.conn.execute(
            f"SELECT * FROM model_outcomes{where} ORDER BY created_at DESC, outcome_id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [
            {
                **dict(row),
                "verifier_pass": bool(row["verifier_pass"]),
            }
            for row in rows
        ]

    def model_outcome_summary(
        self,
        *,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
        role: str | None = None,
        task_class: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("model_id", model_id),
            ("reasoning_effort", reasoning_effort),
            ("role", role),
            ("task_class", task_class),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(str(value))
        learning_clauses = ["COALESCE(identity_evidence, 'confirmed') != 'host_only'", *clauses]
        where = " WHERE " + " AND ".join(learning_clauses)
        rows = self.conn.execute(
            f"""SELECT model_id, reasoning_effort, role,
                       COUNT(*) AS observations,
                       SUM(CASE WHEN verifier_pass=1 THEN 1 ELSE 0 END) AS successes,
                       SUM(CASE WHEN verifier_pass=0 THEN 1 ELSE 0 END) AS failures,
                       SUM(CASE WHEN COALESCE(identity_evidence, 'confirmed')='confirmed' THEN 1 ELSE 0 END) AS confirmed_observations,
                       SUM(CASE WHEN identity_evidence='configured_explicit' THEN 1 ELSE 0 END) AS configured_explicit_observations,
                       AVG(elapsed_ms) AS mean_elapsed_ms,
                       AVG(attempts) AS mean_attempts,
                       MAX(created_at) AS last_observed_at
                FROM model_outcomes{where}
                GROUP BY model_id, reasoning_effort, role
                ORDER BY model_id, reasoning_effort, role""",
            params,
        ).fetchall()
        return [
            {
                "model_id": row["model_id"],
                "reasoning_effort": row["reasoning_effort"],
                "role": row["role"],
                "identity_evidence": "confirmed" if int(row["confirmed_observations"] or 0) else "configured_explicit",
                "observations": int(row["observations"] or 0),
                "successes": int(row["successes"] or 0),
                "failures": int(row["failures"] or 0),
                "confirmed_observations": int(row["confirmed_observations"] or 0),
                "configured_explicit_observations": int(row["configured_explicit_observations"] or 0),
                "mean_elapsed_ms": row["mean_elapsed_ms"],
                "mean_attempts": row["mean_attempts"],
                "last_observed_at": row["last_observed_at"],
            }
            for row in rows
        ]

    @atomic
    def create_note(self, *, task_id: str, text: str, session_id: str | None = None,
                    depends_on: list[str] | None = None,
                    dependency_fingerprints: dict[str, str | None] | None = None,
                    note_id: str | None = None, created_at: str | None = None,
                    updated_at: str | None = None) -> str:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"unknown task: {task_id}")
        if session_id:
            session = self.session(session_id)
            if not session or session["task_id"] != task_id:
                raise ValueError(f"note_session_task_mismatch:{session_id}:{task_id}")
        text = str(text).strip()
        if not text:
            raise ValueError("note_text_required")
        note_id = note_id or f"n-{uuid.uuid4().hex[:12]}"
        depends = [str(x) for x in (depends_on or [])]
        fingerprints = {str(k): (None if v is None else str(v)) for k, v in (dependency_fingerprints or {}).items()}
        now = created_at or utc_now()
        self.conn.execute(
            "INSERT INTO notes(note_id,task_id,session_id,text,depends_json,dependency_fingerprints_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (note_id, task_id, session_id, text, canonical_json(depends), canonical_json(fingerprints), now, updated_at or now),
        )
        self.event("NOTE_CREATED", {"note_id": note_id, "depends_on": depends}, session_id=session_id, task_id=task_id)
        return note_id

    def note(self, note_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM notes WHERE note_id=?", (note_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["depends_on"] = json.loads(value.pop("depends_json"))
        value["dependency_fingerprints"] = json.loads(value.pop("dependency_fingerprints_json"))
        return value

    def notes_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM notes WHERE task_id=? ORDER BY created_at, note_id", (task_id,)).fetchall()
        return [self._note_row(row) for row in rows]

    def notes_for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM notes WHERE session_id=? ORDER BY created_at, note_id", (session_id,)).fetchall()
        return [self._note_row(row) for row in rows]

    @staticmethod
    def _note_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["depends_on"] = json.loads(value.pop("depends_json"))
        value["dependency_fingerprints"] = json.loads(value.pop("dependency_fingerprints_json"))
        return value

    @atomic
    def create_context_job(self, *, task_id: str, provider: str, packet: dict[str, Any],
                           session_id: str | None = None, archive_refs: list[str] | None = None,
                           source_identity_sha256: str | None = None, job_id: str | None = None,
                           created_at: str | None = None) -> str:
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"unknown task: {task_id}")
        if session_id:
            session = self.session(session_id)
            if not session or session["task_id"] != task_id:
                raise ValueError(f"context_job_session_task_mismatch:{session_id}:{task_id}")
        job_id = job_id or f"job-{uuid.uuid4().hex[:12]}"
        created_at = created_at or utc_now()
        self.conn.execute(
            "INSERT INTO context_jobs(job_id,task_id,session_id,provider,status,packet_json,archive_refs_json,source_identity_sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (job_id, task_id, session_id, str(provider), "ARCHIVED", canonical_json(packet), canonical_json([str(x) for x in (archive_refs or [])]), source_identity_sha256, created_at),
        )
        self.event("CONTEXT_JOB_ARCHIVED", {"job_id": job_id, "provider": provider}, session_id=session_id, task_id=task_id)
        return job_id

    def context_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM context_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["packet"] = json.loads(value.pop("packet_json"))
        value["archive_refs"] = json.loads(value.pop("archive_refs_json"))
        return value

    def context_jobs_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM context_jobs WHERE task_id=? ORDER BY created_at, job_id", (task_id,)).fetchall()
        return [self._context_job_row(row) for row in rows]

    @staticmethod
    def _context_job_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["packet"] = json.loads(value.pop("packet_json"))
        value["archive_refs"] = json.loads(value.pop("archive_refs_json"))
        return value

    def sessions_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM sessions WHERE task_id=? ORDER BY started_at, session_id", (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def portable_import(self, bundle_sha256: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM portable_imports WHERE bundle_sha256=?", (bundle_sha256,)).fetchone()
        if not row:
            return None
        value = dict(row); value["source_identity"] = json.loads(value.pop("source_identity_json")); return value

    @atomic
    def record_portable_import(self, *, bundle_sha256: str, schema: str, task_id: str,
                               source_identity: dict[str, Any], object_count: int) -> None:
        self.conn.execute(
            "INSERT INTO portable_imports(bundle_sha256,schema,task_id,source_identity_json,imported_at,object_count) VALUES(?,?,?,?,?,?)",
            (bundle_sha256, schema, task_id, canonical_json(source_identity), utc_now(), int(object_count)),
        )

    @atomic
    def record_memory_event(self, *, source_event_id: str, task_id: str, session_id: str | None,
                            event_type: str, ts: str, payload: dict[str, Any], prev_hash: str | None,
                            event_hash: str, source_bundle_sha256: str) -> None:
        self.conn.execute(
            "INSERT INTO memory_events(source_event_id,task_id,session_id,event_type,ts,payload_json,prev_hash,event_hash,source_bundle_sha256) VALUES(?,?,?,?,?,?,?,?,?)",
            (source_event_id, task_id, session_id, event_type, ts, canonical_json(payload), prev_hash, event_hash, source_bundle_sha256),
        )

    def memory_events_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM memory_events WHERE task_id=? ORDER BY ts, source_event_id", (task_id,)).fetchall()
        out = []
        for row in rows:
            value = dict(row); value["payload"] = json.loads(value.pop("payload_json")); out.append(value)
        return out

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in reversed(rows):
            d = dict(r); d["payload"] = json.loads(d.pop("payload_json")); out.append(d)
        return out

    @atomic
    def acquire_lease(self, *, lease_key: str, session_id: str, task_id: str, ttl_seconds: int = 900) -> dict[str, Any]:
        now = datetime.now(timezone.utc); acquired_at = now.isoformat(); expires_at = (now + timedelta(seconds=max(1, ttl_seconds))).isoformat()
        key = _selector(lease_key)
        try:
            self.conn.execute("DELETE FROM leases WHERE expires_at <= ?", (now.isoformat(),))
            rows = self.conn.execute("SELECT * FROM leases").fetchall()
            for row in rows:
                if row["session_id"] != session_id and lease_keys_overlap(key, row["lease_key"]):
                    return {"acquired": False, "reason": "lease_overlap_held", "requested_key": key, **dict(row)}
            self.conn.execute(
                "INSERT INTO leases(lease_key,session_id,task_id,acquired_at,expires_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(lease_key) DO UPDATE SET session_id=excluded.session_id,task_id=excluded.task_id,acquired_at=excluded.acquired_at,expires_at=excluded.expires_at",
                (key, session_id, task_id, acquired_at, expires_at),
            )
        except Exception:
            raise
        self.event("LEASE_ACQUIRED", {"lease_key": key, "expires_at": expires_at}, session_id=session_id, task_id=task_id)
        return {"acquired": True, "lease_key": key, "session_id": session_id, "task_id": task_id, "acquired_at": acquired_at, "expires_at": expires_at}

    @atomic
    def release_lease(self, *, lease_key: str, session_id: str) -> dict[str, Any]:
        key = _selector(lease_key)
        row = self.conn.execute("SELECT * FROM leases WHERE lease_key=?", (key,)).fetchone()
        if not row:
            return {"released": True, "reason": "lease_absent", "lease_key": key}
        if row["session_id"] != session_id:
            return {"released": False, "reason": "lease_owned_by_other_session", **dict(row)}
        task_id = row["task_id"]
        self.conn.execute("DELETE FROM leases WHERE lease_key=?", (key,))
        self.event("LEASE_RELEASED", {"lease_key": key}, session_id=session_id, task_id=task_id)
        return {"released": True, "lease_key": key, "session_id": session_id, "task_id": task_id}

    def active_leases(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("DELETE FROM leases WHERE expires_at <= ?", (now,))
        return [dict(r) for r in self.conn.execute("SELECT * FROM leases ORDER BY lease_key").fetchall()]

    def lease_conflict(self, *, target: str, session_id: str | None) -> dict[str, Any] | None:
        key = _selector(target)
        for row in self.active_leases():
            if session_id and row["session_id"] == session_id:
                continue
            if lease_keys_overlap(key, row["lease_key"]):
                return dict(row)
        return None

    def receipt_head(self) -> str | None:
        row = self.conn.execute("SELECT value FROM metadata WHERE key='receipt_head'").fetchone()
        return str(row[0]) if row and row[0] else None

    @atomic
    def append_receipt_index(self, *, receipt_hash: str, previous_hash: str | None, path: str, session_id: str, task_id: str) -> bool:
        """CAS-append a sealed receipt to the local receipt chain."""
        try:
            row = self.conn.execute("SELECT value FROM metadata WHERE key='receipt_head'").fetchone()
            current = str(row[0]) if row and row[0] else None
            if current != previous_hash:
                return False
            self.conn.execute("INSERT INTO receipt_index(receipt_hash,previous_hash,path,session_id,task_id,created_at) VALUES(?,?,?,?,?,?)", (receipt_hash, previous_hash, path, session_id, task_id, utc_now()))
            self.conn.execute("INSERT INTO metadata(key,value) VALUES('receipt_head',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (receipt_hash,))
            return True
        except Exception:
            raise
