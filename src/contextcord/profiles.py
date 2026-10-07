from __future__ import annotations

from pathlib import Path

GENERIC_PROJECT = '''[project]
name = "replace-me"

[identity]
mode = "content_equivalent"

[knowledge]
entrypoints = ["AGENTS.md"]

[policy]
entrypoints = ["AGENTS.md"]

[memory]
require_same_commit_as_truth = false
sealed_on_verify = true

[dogfood]
ledger_path = ".contextcord/dual-run/adjudications.json"
required_task_classes = []
'''
GENERIC_TRUTH = '''[defaults]
kind = "source"

[[rules]]
pattern = ".contextcord/generated/**"
kind = "generated"
[[rules]]
pattern = ".contextcord/receipts/**"
kind = "evidence"
[[rules]]
pattern = ".contextcord/dual-run/**"
kind = "evidence"
[[rules]]
pattern = ".contextcord/*.toml"
kind = "source"
'''
GENERIC_WORKFLOW = '''[[phases]]
id = "authority"
requires = []
[[phases]]
id = "implementation"
requires = ["authority"]
[[phases]]
id = "tests"
requires = ["implementation"]
[[phases]]
id = "qualification"
requires = ["tests"]
[[phases]]
id = "delivery"
requires = ["qualification"]

[scope_profiles.code]
required_phases = ["authority", "implementation", "tests"]
[scope_profiles.release]
required_phases = ["authority", "implementation", "tests", "qualification", "delivery"]

[phase_contracts.authority]
require_policy_stable = true
[phase_contracts.tests]
minimum_pass_evidence = 1
[phase_contracts.qualification]
require_qualification_profile = "candidate"
[phase_contracts.delivery]
require_qualification_profile = "release"

[operation_gates.push]
allowed_current_phases = ["delivery"]
requires_completed = ["qualification"]
[operation_gates.release]
allowed_current_phases = ["delivery"]
requires_completed = ["qualification"]
[operation_gates.deploy]
allowed_current_phases = ["delivery"]
requires_completed = ["qualification"]
'''
GENERIC_AUTHORITY = '''[[protected]]
path = ".git/**"
operations = ["write", "delete", "move"]
reason = "direct Git metadata mutation is forbidden; use Git commands"

[leases]
enforce_conflicts = true
require_for_mutation = false

[scopes.code]
allow_operations = ["read", "write", "delete", "move", "test", "git", "checkpoint"]
write_patterns = ["**"]
forbidden_patterns = [".git/**"]
allow_external = false

[scopes.release]
allow_operations = ["read", "write", "delete", "move", "test", "git", "checkpoint", "push", "release", "deploy"]
write_patterns = ["**"]
forbidden_patterns = [".git/**"]
allow_external = false
'''
GENERIC_RUNTIME = '''required_scopes = []
# Optional probes support http_json, file_json, or command_json.
'''
GENERIC_EVIDENCE = '''[rules]
require_file_for_pass = true
require_any_test_for_complete = true
exact_revision_required = true
allow_external_paths = false
receipt_dir = ".contextcord/receipts"
runner_dir = ".contextcord/generated/evidence"
runner_allow_external_cwd = false
runner_max_output_bytes = 1048576
runner_redact_patterns = []
runner_require_identity_stable = true
require_workflow_complete = true
require_policy_stable = true
'''
GENERIC_QUALIFICATION = '''notes_ref = "refs/notes/contextcord"
default_profile = "current-records"

[profiles.candidate]
required = ["ci"]
[profiles.release]
required = ["ci", "review"]
'''

CARBON_PROJECT = '''[project]
name = "Carbon-Bot"

[identity]
mode = "exact_commit"

[knowledge]
entrypoints = [
  "AGENTS.md",
  "PROJECT_RULES.md",
  "docs/agent/PROJECT_MEMORY.md",
  "docs/agent/ENVIRONMENT_AUTHORITY.md",
  "docs/agent/KNOWN_ISSUES.md"
]

[policy]
entrypoints = [
  "AGENTS.md",
  "PROJECT_RULES.md",
  "docs/agent/ENVIRONMENT_AUTHORITY.md",
  "docs/agent/KNOWN_ISSUES.md"
]

[memory]
require_same_commit_as_truth = false
sealed_on_verify = true

[dogfood]
ledger_path = ".contextcord/dual-run/adjudications.json"
required_task_classes = ["code-only", "data-readonly", "staging", "release"]
'''
CARBON_TRUTH = '''[defaults]
kind = "source"
[[rules]]
pattern = ".contextcord/generated/**"
kind = "generated"
[[rules]]
pattern = ".contextcord/receipts/**"
kind = "evidence"
[[rules]]
pattern = ".contextcord/dual-run/**"
kind = "evidence"
[[rules]]
pattern = "docs/agent/sessions/**"
kind = "evidence"
[[rules]]
pattern = "docs/agent/PROJECT_MEMORY.md"
kind = "durable_memory"
[[rules]]
pattern = "training/**"
kind = "runtime_input"
[[rules]]
pattern = "knowledge_base/**"
kind = "runtime_input"
[[rules]]
pattern = "benchmarks/**"
kind = "runtime_input"
[[rules]]
pattern = "evaluation/**"
kind = "runtime_input"
[[rules]]
pattern = ".contextcord/*.toml"
kind = "source"
'''
CARBON_WORKFLOW = '''[[phases]]
id = "A_AUTHORITY"
requires = []
[[phases]]
id = "B_EXECUTION_GUARDS"
requires = ["A_AUTHORITY"]
[[phases]]
id = "C_DATA_BOUND_TESTS"
requires = ["B_EXECUTION_GUARDS"]
[[phases]]
id = "D_LOCAL_STAGING"
requires = ["C_DATA_BOUND_TESTS"]
[[phases]]
id = "E_QWEN_LOCAL_COMPARE"
requires = ["D_LOCAL_STAGING"]
[[phases]]
id = "F_BROWSER_EVIDENCE"
requires = ["E_QWEN_LOCAL_COMPARE"]
[[phases]]
id = "G_MEMORY_CLOSEOUT"
requires = ["F_BROWSER_EVIDENCE"]
[[phases]]
id = "H_PUSH_CI"
requires = ["G_MEMORY_CLOSEOUT"]
[[phases]]
id = "I_PUBLIC_DEPLOY"
requires = ["H_PUSH_CI"]
[[phases]]
id = "J_PUBLIC_SMOKE_REVIEW"
requires = ["I_PUBLIC_DEPLOY"]

[scope_profiles.code-only]
required_phases = ["A_AUTHORITY", "B_EXECUTION_GUARDS"]
[scope_profiles.data-readonly]
required_phases = ["A_AUTHORITY", "B_EXECUTION_GUARDS", "C_DATA_BOUND_TESTS"]
[scope_profiles.staging]
required_phases = ["A_AUTHORITY", "B_EXECUTION_GUARDS", "C_DATA_BOUND_TESTS", "D_LOCAL_STAGING"]
[scope_profiles.release]
required_phases = ["A_AUTHORITY", "B_EXECUTION_GUARDS", "C_DATA_BOUND_TESTS", "D_LOCAL_STAGING", "E_QWEN_LOCAL_COMPARE", "F_BROWSER_EVIDENCE", "G_MEMORY_CLOSEOUT", "H_PUSH_CI", "I_PUBLIC_DEPLOY", "J_PUBLIC_SMOKE_REVIEW"]

[phase_contracts.A_AUTHORITY]
require_policy_stable = true
[phase_contracts.B_EXECUTION_GUARDS]
minimum_pass_evidence = 1
[phase_contracts.C_DATA_BOUND_TESTS]
required_evidence = ["data-bound-tests"]
[phase_contracts.D_LOCAL_STAGING]
required_evidence = ["local-staging"]
[phase_contracts.E_QWEN_LOCAL_COMPARE]
required_evidence = ["qwen-local-compare"]
[phase_contracts.F_BROWSER_EVIDENCE]
required_evidence = ["browser-evidence"]
[phase_contracts.G_MEMORY_CLOSEOUT]
require_clean_truth = true
[phase_contracts.H_PUSH_CI]
require_qualification_profile = "candidate"
[phase_contracts.I_PUBLIC_DEPLOY]
require_qualification_profile = "production"
[phase_contracts.J_PUBLIC_SMOKE_REVIEW]
required_evidence = ["public-smoke-review"]

[operation_gates.push]
allowed_current_phases = ["H_PUSH_CI"]
requires_completed = ["G_MEMORY_CLOSEOUT"]
[operation_gates.release]
allowed_current_phases = ["I_PUBLIC_DEPLOY"]
requires_completed = ["H_PUSH_CI"]
[operation_gates.deploy]
allowed_current_phases = ["I_PUBLIC_DEPLOY"]
requires_completed = ["H_PUSH_CI"]
'''
CARBON_AUTHORITY = '''[[protected]]
path = "${CARBON_DATA_ROOT}/serving/**"
operations = ["write", "delete", "move"]
reason = "protected Carbon data authority subtree"
[[protected]]
path = "${CARBON_DATA_ROOT}/immutable/**"
operations = ["write", "delete", "move"]
reason = "immutable Carbon data authority subtree"
[[protected]]
path = "${CARBON_DATA_ROOT}/scientific_artifacts/**"
operations = ["write", "delete", "move"]
reason = "scientific artifacts are protected"
[[protected]]
path = "${CARBON_DATA_ROOT}/artifacts/**"
operations = ["write", "delete", "move"]
reason = "approved artifacts are protected"
[[protected]]
path = "${CARBON_DATA_ROOT}/state/**"
operations = ["write", "delete", "move"]
reason = "approved state is protected"
[[protected]]
path = ".git/**"
operations = ["write", "delete", "move"]
reason = "direct Git metadata mutation is forbidden"

[leases]
enforce_conflicts = true
require_for_mutation = false

[scopes.code-only]
allow_operations = ["read", "write", "delete", "move", "test", "git", "checkpoint"]
write_patterns = ["**"]
forbidden_patterns = [".git/**"]
allow_external = false

[scopes.data-readonly]
allow_operations = ["read", "write", "delete", "move", "test", "git", "checkpoint"]
write_patterns = ["**"]
forbidden_patterns = [".git/**"]
allow_external = true
external_read_patterns = ["${CARBON_DATA_ROOT}/**"]

[scopes.staging]
allow_operations = ["read", "write", "delete", "move", "test", "git", "checkpoint"]
write_patterns = ["**"]
forbidden_patterns = [".git/**"]
allow_external = true
external_read_patterns = ["${CARBON_DATA_ROOT}/**"]
external_write_patterns = ["${CARBON_STAGING_ROOT}/**"]

[scopes.release]
allow_operations = ["read", "write", "delete", "move", "test", "git", "checkpoint", "push", "release", "deploy"]
write_patterns = ["**"]
forbidden_patterns = [".git/**"]
allow_external = true
external_read_patterns = ["${CARBON_DATA_ROOT}/**"]
external_write_patterns = ["${CARBON_STAGING_ROOT}/**"]
'''
CARBON_RUNTIME = '''required_scopes = []
# Add Carbon provider/data/runtime collectors as command_json probes during real rollout.
'''
CARBON_QUALIFICATION = '''notes_ref = "refs/notes/contextcord"
default_profile = "current-records"
[profiles.candidate]
required = ["ci"]
[profiles.production]
required = ["ci", "deployment:production"]
'''

MATERIAL_PROJECT = '''[project]
name = "MaterialBrain"

[identity]
mode = "exact_commit"

[knowledge]
entrypoints = [
  "AGENTS.md",
  "backend/AGENTS.md",
  "frontend/AGENTS.md",
  "docs/PROJECT_MEMORY.md",
  "docs/DOCUMENTATION_MAP.md"
]

[policy]
entrypoints = [
  "AGENTS.md",
  "backend/AGENTS.md",
  "frontend/AGENTS.md",
  "docs/DOCUMENTATION_MAP.md"
]

[memory]
require_same_commit_as_truth = true
sealed_on_verify = true

[dogfood]
ledger_path = ".contextcord/dual-run/adjudications.json"
required_task_classes = ["backend", "frontend", "browser", "release"]
'''
MATERIAL_TRUTH = '''[defaults]
kind = "source"
[[rules]]
pattern = ".contextcord/generated/**"
kind = "generated"
[[rules]]
pattern = ".contextcord/receipts/**"
kind = "evidence"
[[rules]]
pattern = ".contextcord/dual-run/**"
kind = "evidence"
[[rules]]
pattern = "artifacts/**"
kind = "evidence"
[[rules]]
pattern = "backend/eval-results/**"
kind = "evidence"
[[rules]]
pattern = "backend/.local-evals/**"
kind = "generated"
[[rules]]
pattern = "storage/exports/**"
kind = "generated"
[[rules]]
pattern = "storage/backups/**"
kind = "generated"
[[rules]]
pattern = "frontend/dist/**"
kind = "generated"
[[rules]]
pattern = "frontend/node_modules/**"
kind = "ignore"
[[rules]]
pattern = "docs/PROJECT_MEMORY.md"
kind = "durable_memory"
[[rules]]
pattern = ".contextcord/*.toml"
kind = "source"
'''
MATERIAL_WORKFLOW = '''[[phases]]
id = "authority"
requires = []
[[phases]]
id = "implementation"
requires = ["authority"]
[[phases]]
id = "static_tests"
requires = ["implementation"]
[[phases]]
id = "integration_tests"
requires = ["static_tests"]
[[phases]]
id = "exact_sha_runtime"
requires = ["integration_tests"]
[[phases]]
id = "browser_uat"
requires = ["exact_sha_runtime"]
[[phases]]
id = "qualification"
requires = ["browser_uat"]
[[phases]]
id = "push_ci"
requires = ["qualification"]
[[phases]]
id = "deployment"
requires = ["push_ci"]

[scope_profiles.code]
required_phases = ["authority", "implementation", "static_tests", "integration_tests"]
[scope_profiles.uat]
required_phases = ["authority", "implementation", "static_tests", "integration_tests", "exact_sha_runtime", "browser_uat"]
[scope_profiles.release]
required_phases = ["authority", "implementation", "static_tests", "integration_tests", "exact_sha_runtime", "browser_uat", "qualification", "push_ci", "deployment"]

[phase_contracts.authority]
require_policy_stable = true
[phase_contracts.static_tests]
required_evidence = ["static-tests"]
[phase_contracts.integration_tests]
required_evidence = ["integration-tests"]
[phase_contracts.exact_sha_runtime]
required_runtime = ["backend", "frontend"]
[phase_contracts.browser_uat]
required_evidence = ["browser-uat"]
[phase_contracts.qualification]
require_qualification_profile = "candidate"
[phase_contracts.deployment]
require_qualification_profile = "deployed"

[operation_gates.push]
allowed_current_phases = ["push_ci"]
requires_completed = ["qualification"]
[operation_gates.release]
allowed_current_phases = ["deployment"]
requires_completed = ["push_ci"]
[operation_gates.deploy]
allowed_current_phases = ["deployment"]
requires_completed = ["push_ci"]
'''
MATERIAL_AUTHORITY = '''[[protected]]
path = ".git/**"
operations = ["write", "delete", "move"]
reason = "direct Git metadata mutation is forbidden"
[[protected]]
path = ".env"
operations = ["write", "delete", "move"]
reason = "secrets file is not an agent write target"
[[protected]]
path = "storage/backups/**"
operations = ["write", "delete", "move"]
reason = "backup artifacts require explicit release workflow"

[leases]
enforce_conflicts = true
require_for_mutation = false

[scopes.code]
allow_operations = ["read", "write", "delete", "move", "test", "git", "checkpoint"]
write_patterns = ["**"]
forbidden_patterns = [".git/**", ".env"]
allow_external = false

[scopes.uat]
allow_operations = ["read", "write", "delete", "move", "test", "git", "checkpoint"]
write_patterns = ["**"]
forbidden_patterns = [".git/**", ".env", "storage/backups/**"]
allow_external = false

[scopes.release]
allow_operations = ["read", "write", "delete", "move", "test", "git", "checkpoint", "push", "release", "deploy"]
write_patterns = ["**"]
forbidden_patterns = [".git/**", ".env"]
allow_external = false
'''
MATERIAL_RUNTIME = '''required_scopes = ["uat", "release"]
[[probes]]
id = "backend"
kind = "http_json"
url = "${MATERIALBRAIN_BASE_URL}/api/v1/runtime-info"
revision_field = "backend_build_sha"
expected = "HEAD"
required = false
timeout = 2.0
[[probes]]
id = "frontend"
kind = "http_json"
url = "${MATERIALBRAIN_BASE_URL}/build-info.json"
revision_field = "frontend_build_sha"
expected = "HEAD"
required = false
timeout = 2.0
'''
MATERIAL_QUALIFICATION = '''notes_ref = "refs/notes/contextcord"
default_profile = "current-records"
[profiles.candidate]
required = ["ci", "browser"]
[profiles.deployed]
required = ["ci", "browser", "deployment:production"]
'''

PROFILES = {
    "generic": (GENERIC_PROJECT, GENERIC_TRUTH, GENERIC_WORKFLOW, GENERIC_AUTHORITY, GENERIC_RUNTIME, GENERIC_EVIDENCE, GENERIC_QUALIFICATION),
    "carbon-bot": (CARBON_PROJECT, CARBON_TRUTH, CARBON_WORKFLOW, CARBON_AUTHORITY, CARBON_RUNTIME, GENERIC_EVIDENCE, CARBON_QUALIFICATION),
    "materialbrain": (MATERIAL_PROJECT, MATERIAL_TRUTH, MATERIAL_WORKFLOW, MATERIAL_AUTHORITY, MATERIAL_RUNTIME, GENERIC_EVIDENCE, MATERIAL_QUALIFICATION),
}


def write_profile(repo: Path, profile: str, *, force: bool = False, state_dir: str | Path = ".contextcord") -> list[Path]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile}")
    from .util import ensure_repo_path
    state = Path(state_dir)
    if state.is_absolute() or ".." in state.parts or len(state.parts) != 1:
        raise ValueError("state_dir must be a single repository-relative directory name")
    state_name = state.as_posix()
    root, _ = ensure_repo_path(repo, state, label="profile")
    root.mkdir(parents=True, exist_ok=True)
    names = ["project.toml", "truth.toml", "workflow.toml", "authority.toml", "runtime.toml", "evidence.toml", "qualification.toml"]
    for name in [*names, ".gitignore", ".gitattributes"]:
        p, _ = ensure_repo_path(repo, state / name, label="profile")
        if name in names and p.exists() and not force:
            raise FileExistsError(f"refusing to overwrite {p}; pass --force")
    written = []
    for name, text in zip(names, PROFILES[profile]):
        p = root / name
        if p.exists() and not force:
            raise FileExistsError(f"refusing to overwrite {p}; pass --force")
        text = text.replace(".contextcord", state_name)
        if name == "truth.toml" and 'pattern = "docs/generated/**"' not in text:
            text += '\n[[rules]]\npattern = "docs/generated/**"\nkind = "generated"\n'
        if name == "truth.toml" and state_name == ".contextcord":
            text += ('\n[[rules]]\npattern = ".contextcord/state.db*"\nkind = "ignore"\n'
                     '[[rules]]\npattern = ".contextcord/closeout/**"\nkind = "generated"\n'
                     '[[rules]]\npattern = ".contextcord/migrations/**"\nkind = "evidence"\n'
                     '[[rules]]\npattern = ".contextcord/*.lock"\nkind = "generated"\n')
        p.write_text(text, encoding="utf-8", newline="\n"); written.append(p)
    ignore = root / ".gitignore"
    ignore_text = "generated/\nreceipts/\ndual-run/\n"
    if state_name == ".contextcord":
        ignore_text += "state.db*\ncloseout/\nmigrations/\n*.lock\n"
    if not ignore.exists() or force:
        ignore.write_text(ignore_text, encoding="utf-8", newline="\n"); written.append(ignore)
    attributes = root / ".gitattributes"
    if not attributes.exists() or force:
        attributes.write_text("*.toml text eol=lf\n.gitignore text eol=lf\n.gitattributes text eol=lf\n", encoding="utf-8", newline="\n")
        written.append(attributes)
    return written
