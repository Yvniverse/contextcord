from __future__ import annotations

import multiprocessing as mp
import subprocess
import tempfile
import unittest
from pathlib import Path

from contextcord.config import discover
from contextcord.hostbridge import HostAction, authorize_host_action
from contextcord.profiles import write_profile
from contextcord.store import StateStore


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _event_worker(repo: str, barrier, queue, index: int) -> None:
    try:
        barrier.wait(timeout=20)
        with StateStore(Path(repo)) as store:
            event_id = store.event("CONCURRENCY_TEST", {"worker": index}, session_id=f"s-{index}", task_id="concurrency")
        queue.put((index, True, event_id))
    except BaseException as exc:  # pragma: no cover - returned to parent for assertion
        queue.put((index, False, repr(exc)))


def _lease_worker(repo: str, barrier, queue, index: int) -> None:
    try:
        barrier.wait(timeout=20)
        with StateStore(Path(repo)) as store:
            result = store.acquire_lease(lease_key="src/**", session_id=f"s-{index}", task_id=f"t-{index}", ttl_seconds=60)
        queue.put((index, bool(result.get("acquired")), result))
    except BaseException as exc:  # pragma: no cover
        queue.put((index, False, {"error": repr(exc)}))


class ConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.repo = Path(self.tmp.name)
        subprocess.check_call(["git", "init", "-q", str(self.repo)])
        git(self.repo, "config", "user.email", "conc@example.com"); git(self.repo, "config", "user.name", "Concurrency")
        (self.repo / "AGENTS.md").write_text("rules\n"); (self.repo / "src").mkdir(); (self.repo / "src/app.py").write_text("x=1\n")
        write_profile(self.repo, "generic"); git(self.repo, "add", "."); git(self.repo, "commit", "-qm", "initial")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_multiprocess_event_append_preserves_single_hash_chain(self) -> None:
        ctx = mp.get_context("spawn")
        workers = 16; barrier = ctx.Barrier(workers); queue = ctx.Queue()
        procs = [ctx.Process(target=_event_worker, args=(str(self.repo), barrier, queue, i)) for i in range(workers)]
        for p in procs: p.start()
        for p in procs: p.join(30)
        self.assertTrue(all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs])
        rows = [queue.get(timeout=3) for _ in range(workers)]
        self.assertTrue(all(ok for _, ok, _ in rows), rows)
        with StateStore(self.repo) as store:
            ok, bad = store.verify_event_chain(); self.assertTrue(ok, bad)
            events = [x for x in store.recent_events(100) if x["event_type"] == "CONCURRENCY_TEST"]
            self.assertEqual(len(events), workers)
            self.assertEqual(len({x["event_hash"] for x in events}), workers)

    def test_multiprocess_same_lease_has_exactly_one_winner(self) -> None:
        ctx = mp.get_context("spawn")
        workers = 8; barrier = ctx.Barrier(workers); queue = ctx.Queue()
        procs = [ctx.Process(target=_lease_worker, args=(str(self.repo), barrier, queue, i)) for i in range(workers)]
        for p in procs: p.start()
        for p in procs: p.join(30)
        self.assertTrue(all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs])
        rows = [queue.get(timeout=3) for _ in range(workers)]
        winners = [row for row in rows if row[1]]
        self.assertEqual(len(winners), 1, rows)
        with StateStore(self.repo) as store:
            active = store.active_leases(); self.assertEqual(len(active), 1); self.assertEqual(active[0]["lease_key"], "src/**")

    def test_overlapping_lease_and_host_authorization_are_enforced(self) -> None:
        cfg = discover(self.repo)
        with StateStore(self.repo) as store:
            first = store.acquire_lease(lease_key="src/**", session_id="owner", task_id="owner-task", ttl_seconds=60)
            self.assertTrue(first["acquired"])
            second = store.acquire_lease(lease_key="src/app.py", session_id="other", task_id="other-task", ttl_seconds=60)
            self.assertFalse(second["acquired"]); self.assertEqual(second["reason"], "lease_overlap_held")
            denied = authorize_host_action(cfg, store, action=HostAction("write", "src/app.py", "high", "test"), scope="code", task_id=None, session_id="other")
            self.assertFalse(denied["allowed"]); self.assertEqual(denied["reason"], "writer_lease_conflict")
            allowed = authorize_host_action(cfg, store, action=HostAction("write", "src/app.py", "high", "test"), scope="code", task_id=None, session_id="owner")
            self.assertTrue(allowed["allowed"])

    def test_cross_host_aliases_conflict_for_external_leases(self):
        with StateStore(self.repo) as store:
            first=store.acquire_lease(lease_key="D:/carbon-data/**",session_id="win",task_id="a",ttl_seconds=60); self.assertTrue(first["acquired"])
            second=store.acquire_lease(lease_key="/mnt/d/carbon-data/file.txt",session_id="wsl",task_id="b",ttl_seconds=60); self.assertFalse(second["acquired"])
            third=store.acquire_lease(lease_key="/run/desktop/mnt/host/d/carbon-data/other.txt",session_id="docker",task_id="c",ttl_seconds=60); self.assertFalse(third["acquired"])


if __name__ == "__main__":
    unittest.main()
