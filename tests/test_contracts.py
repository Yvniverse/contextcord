from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from project_harness.config import ConfigError, discover
from project_harness.contracts import SCHEMAS, schema, validate
from project_harness.identity import source_identity
from project_harness.profiles import write_profile
from project_harness.store import StateStore


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class ContractTests(unittest.TestCase):
    def make_repo(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        td=tempfile.TemporaryDirectory(); repo=Path(td.name); subprocess.check_call(["git","init","-q",str(repo)])
        git(repo,"config","user.email","c@x"); git(repo,"config","user.name","contracts"); (repo/"AGENTS.md").write_text("rules\n"); (repo/"src").mkdir(); (repo/"src/x.py").write_text("x=1\n")
        write_profile(repo,"generic"); git(repo,"add","."); git(repo,"commit","-qm","initial"); return td,repo

    def test_all_bundled_schemas_are_valid_draft_2020_12(self):
        for name in SCHEMAS:
            Draft202012Validator.check_schema(schema(name))

    def test_actual_source_identity_and_event_validate(self):
        td,repo=self.make_repo()
        try:
            cfg=discover(repo); ident=source_identity(cfg); validate("source-identity",ident)
            with StateStore(repo) as store:
                store.event("TEST",{"ok":True},task_id="t")
                row=store.recent_events(1)[0]
                payload={k:row[k] for k in ("event_id","session_id","task_id","event_type","ts","payload","prev_hash","event_hash")}
                validate("event",payload)
        finally: td.cleanup()

    def test_invalid_runtime_probe_kind_fails_config_load(self):
        td,repo=self.make_repo()
        try:
            p=repo/".harness/runtime.toml"; p.write_text('required_scopes = []\n[[probes]]\nid="x"\nkind="made-up"\n')
            with self.assertRaises(ConfigError): discover(repo)
        finally: td.cleanup()

    def test_unknown_required_scope_fails_config_load(self):
        td,repo=self.make_repo()
        try:
            p=repo/".harness/runtime.toml"; p.write_text('required_scopes = ["missing"]\n')
            with self.assertRaises(ConfigError): discover(repo)
        finally: td.cleanup()

    def test_invalid_redaction_regex_fails_config_load(self):
        td,repo=self.make_repo()
        try:
            p=repo/".harness/evidence.toml"; p.write_text(p.read_text().replace('runner_redact_patterns = []','runner_redact_patterns = ["("]'))
            with self.assertRaises(ConfigError): discover(repo)
        finally: td.cleanup()

    def test_unknown_authority_operation_fails_config_load(self):
        td,repo=self.make_repo()
        try:
            p=repo/".harness/authority.toml"; p.write_text(p.read_text().replace('"checkpoint"]','"checkpoint", "wirte"]',1))
            with self.assertRaises(ConfigError): discover(repo)
        finally: td.cleanup()

    def test_phase_contract_unknown_runtime_probe_fails_config_load(self):
        td,repo=self.make_repo()
        try:
            p=repo/".harness/workflow.toml"; text=p.read_text(); p.write_text(text.replace('[phase_contracts.delivery]\nrequire_qualification_profile = "release"', '[phase_contracts.delivery]\nrequire_qualification_profile = "release"\nrequired_runtime=["missing-probe"]'))
            with self.assertRaises(ConfigError): discover(repo)
        finally: td.cleanup()

    def test_policy_entrypoint_cannot_escape_repository(self):
        td,repo=self.make_repo()
        try:
            p=repo/".harness/project.toml"; p.write_text(p.read_text().replace('entrypoints = ["AGENTS.md"]','entrypoints = ["../outside.md"]',1))
            with self.assertRaises(ConfigError): discover(repo)
        finally: td.cleanup()


if __name__ == "__main__": unittest.main()
