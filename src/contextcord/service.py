"""Transport-neutral application boundary shared by MCP and integrations.

All operations call the same CLI handlers used by humans and CI. There is no
separate policy engine in adapters and no arbitrary command tool on this surface.
"""
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from jsonschema import Draft202012Validator

from .capabilities import (
    RUNTIME_CAPABILITIES,
    CapabilityConfigError,
    enabled as capability_enabled,
    resolve_features,
)


def object_schema(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {}, 'required': list(required),
            'additionalProperties': False}


TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
TOOLS = {
    'contextcord_context': ('Current project workflow, sessions and next actions.', object_schema({'task_id': TEXT})),
    'contextcord_memory': ('Read bounded portable Task, Session, Note, dependency and historical evidence memory.', object_schema({'task_id': TEXT})),
    'contextcord_memory_recheck': ('Recheck imported relative dependencies without upgrading historical evidence.', object_schema({'task_id': TEXT}, ('task_id',))),
    'contextcord_handoff': ('Preview a bounded Assisted Handoff for one unfinished task; this is read-only.', object_schema({'task_id': TEXT, 'host': TEXT, 'provider': {'enum': ['deterministic', 'jev_api']}})),
    'contextcord_handoff_confirm': ('Confirm a bounded Assisted Handoff and create one local session plus context job.', object_schema({'task_id': TEXT, 'host': TEXT, 'provider': {'enum': ['deterministic', 'jev_api']}, 'session_id': TEXT}, ('task_id',))),
    'contextcord_decision_fabric': ('Evaluate Gate 0 and an optional typed Jev Decision Bundle; code retains hard-gate authority.', object_schema({'state': {'type': 'object', 'additionalProperties': True}, 'provider': {'enum': ['deterministic', 'jev_api']}} , ('state',))),
    'contextcord_identity': ('Content, policy and Git identity of this repository.', object_schema()),
    'contextcord_verify': ('Require a complete, current local closeout and valid evidence.', object_schema()),
    'contextcord_authorize': ('Evaluate policy for an operation; this does not execute it.', object_schema(
        {'scope': TEXT, 'operation': TEXT, 'target': TEXT, 'task_id': TEXT, 'session_id': TEXT}, ('scope', 'operation'))),
    'contextcord_replay': ('Verify and page the local audit timeline; never reruns commands.', object_schema(
        {'task_id': TEXT, 'after': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 10000}})),
    'contextcord_start': ('Start a task session in a configured scope.', object_schema({'task_id': TEXT, 'scope': TEXT}, ('task_id','scope'))),
    'contextcord_checkpoint': ('Record a checkpoint for an open session.', object_schema({'session_id': TEXT, 'summary': TEXT}, ('session_id','summary'))),
    'contextcord_advance': ('Advance a workflow phase after core evidence checks.', object_schema(
        {'task_id': TEXT, 'session_id': TEXT, 'phase': TEXT, 'next_action': TEXT}, ('task_id','session_id','phase','next_action'))),
    'contextcord_finish': ('Close a session; completion requires evidence and workflow gates.', object_schema(
        {'session_id': TEXT, 'summary': TEXT, 'mode': {'enum': ['complete','handoff']}}, ('session_id','summary','mode'))),
    'contextcord_route_model': ('Build a closed model x reasoning-effort route decision; this never executes a host.', object_schema(
        {'state': {'type': 'object', 'additionalProperties': True}, 'task': {'type': 'object', 'additionalProperties': True}})),
    'contextcord_model_intelligence_snapshot': ('Read the derived CodexRadar model-intelligence snapshot; raw provider payloads remain local-only.', object_schema(
        {'refresh': {'type': 'boolean'}})),
}
MUTATIONS = {'contextcord_start','contextcord_checkpoint','contextcord_advance','contextcord_finish','contextcord_handoff_confirm'}

TOOL_CAPABILITIES = {
    'contextcord_context': 'continuity',
    'contextcord_memory': 'memory',
    'contextcord_memory_recheck': 'memory',
    'contextcord_handoff': 'handoff',
    'contextcord_handoff_confirm': 'handoff',
    'contextcord_decision_fabric': 'decision',
    'contextcord_identity': 'core',
    'contextcord_verify': 'evidence',
    'contextcord_authorize': 'core',
    'contextcord_replay': 'evidence',
    'contextcord_start': 'continuity',
    'contextcord_checkpoint': 'continuity',
    'contextcord_advance': 'continuity',
    'contextcord_finish': 'continuity',
    'contextcord_route_model': 'router',
    'contextcord_model_intelligence_snapshot': 'model_intelligence',
}


class HarnessService:
    def __init__(self, repo: Path, *, allow_mutations=False):
        from .gitops import repo_root
        self.repo = repo_root(repo.resolve())
        self.allow_mutations = allow_mutations

    def _effective_capabilities(self) -> set[str]:
        try:
            from .config import ConfigError, discover
            cfg = discover(self.repo)
            return set(resolve_features(cfg.project).get('effective') or ())
        except CapabilityConfigError:
            # A malformed/contradictory feature table must not widen the
            # surface as a recovery path.  The MCP server will expose no
            # capability-owned tools until the config is repaired.
            return set()
        except ConfigError:
            # Uninitialized/legacy programmatic fixtures retain the old full
            # surface. A configured project never takes this fallback.
            return set(RUNTIME_CAPABILITIES)

    def tools(self):
        result = []
        effective = self._effective_capabilities()
        # MCP is a transport capability, not an individual tool capability.
        # A configured profile without it must expose no active MCP surface,
        # even when that profile enables otherwise valid application features.
        if "mcp" not in effective:
            return result
        for name, (description, schema) in TOOLS.items():
            if TOOL_CAPABILITIES.get(name, 'core') not in effective:
                continue
            if not self.allow_mutations and name in MUTATIONS:
                continue
            result.append({'name': name, 'description': description, 'inputSchema': schema,
                           'annotations': {'readOnlyHint': name not in MUTATIONS and name != 'contextcord_authorize',
                                           'destructiveHint': name in MUTATIONS, 'openWorldHint': False}})
        return result

    def call(self, name, arguments):
        effective = self._effective_capabilities()
        if "mcp" not in effective or name not in TOOLS or TOOL_CAPABILITIES.get(name, 'core') not in effective or name in MUTATIONS and not self.allow_mutations:
            raise ValueError('tool_not_available')
        errors = sorted(Draft202012Validator(TOOLS[name][1]).iter_errors(arguments), key=lambda e: str(e.path))
        if errors:
            raise ValueError('invalid_arguments: ' + errors[0].message)
        if name in {'contextcord_memory', 'contextcord_memory_recheck'}:
            from .config import discover
            from .memory import memory_context
            value = memory_context(discover(self.repo), task_id=arguments.get('task_id'))
            # MCP is an inspection surface: cap repeated records and keep full
            # objects recoverable through the local CLI/bundle by stable IDs.
            for key in ('sessions', 'notes', 'evidence', 'context_jobs', 'imported_events'):
                if isinstance(value.get(key), list):
                    value[key] = value[key][-100:]
            if name == 'contextcord_memory_recheck':
                value = {
                    'status': value.get('status'), 'task_id': arguments.get('task_id'),
                    'current_qualification': value.get('current_qualification'),
                    'notes': [{'note_id': row.get('note_id'), 'dependency_status': row.get('dependency_status', [])} for row in value.get('notes', [])],
                }
            return value
        if name in {'contextcord_handoff', 'contextcord_handoff_confirm'}:
            from .config import discover
            from .handoff import assist_handoff
            return assist_handoff(discover(self.repo), task_id=arguments.get('task_id'), host=arguments.get('host'),
                                 provider=arguments.get('provider', 'deterministic'), confirm=name == 'contextcord_handoff_confirm',
                                 session_id=arguments.get('session_id'))
        if name == 'contextcord_decision_fabric':
            from .decision_fabric import evaluate_decision_fabric
            return evaluate_decision_fabric(arguments['state'], provider=arguments.get('provider', 'deterministic'), project_root=str(self.repo))
        if name == 'contextcord_route_model':
            from .config import ConfigError, discover
            from .jev_provider import JevApiDecisionProvider
            from .router import model_route_decision_v3
            from .store import StateStore
            state = arguments.get('state') or arguments.get('task')
            if not isinstance(state, dict):
                raise ValueError('route_state_must_be_object')
            state = dict(state)
            jev_provider = None
            try:
                cfg = discover(self.repo)
                resolved = resolve_features(cfg.project)
                with StateStore(self.repo) as store:
                    state.setdefault('local_routes', store.model_outcome_summary())
                providers = cfg.project.get('providers', {}) if isinstance(cfg.project.get('providers', {}), dict) else {}
                jev = providers.get('jev', {}) if isinstance(providers.get('jev', {}), dict) else {}
                if capability_enabled(resolved, 'jev') or str(state.get('provider') or '').casefold() == 'jev_api':
                    jev_provider = JevApiDecisionProvider(
                        project_root=self.repo,
                        model=str(state.get('jev_model') or jev.get('model') or 'jev-latest'),
                        endpoint=str(state.get('jev_endpoint') or jev.get('endpoint') or 'https://api.typesafe.ai'),
                        max_retries=0,
                    )
                radar = providers.get('codexradar', {}) if isinstance(providers.get('codexradar', {}), dict) else {}
                if bool(radar.get('enabled', False)) and capability_enabled(resolved, 'model_intelligence'):
                    from .model_intelligence import load_codexradar_prior
                    prior = load_codexradar_prior(
                        self.repo,
                        enabled=True,
                        url=str(radar.get('source_url') or 'https://api.codexradar.com/api/v1/table?benchmark=deep-swe'),
                        ttl_seconds=int(radar.get('ttl_seconds', 600)),
                        max_stale_seconds=int(radar.get('max_stale_seconds', 86400)),
                        timeout_seconds=float(radar.get('timeout_seconds', 3)),
                    )
                    prior.pop('payload', None)
                    state['codexradar_prior'] = prior
                    state.setdefault('external_prior_status', prior.get('status', 'UNAVAILABLE'))
            except ConfigError:
                pass
            state.setdefault('router_version', 'v3')
            return model_route_decision_v3(state, mode=state.get('mode', 'SHADOW'), jev_provider=jev_provider)
        if name == 'contextcord_model_intelligence_snapshot':
            from .config import discover
            from .model_intelligence import load_codexradar_prior
            cfg = discover(self.repo)
            resolved = resolve_features(cfg.project)
            providers = cfg.project.get('providers', {}) if isinstance(cfg.project.get('providers', {}), dict) else {}
            radar = providers.get('codexradar', {}) if isinstance(providers.get('codexradar', {}), dict) else {}
            return load_codexradar_prior(
                self.repo,
                enabled=bool(radar.get('enabled', False)) and capability_enabled(resolved, 'model_intelligence'),
                refresh=bool(arguments.get('refresh', False)),
                url=str(radar.get('source_url') or 'https://api.codexradar.com/api/v1/table?benchmark=deep-swe'),
                ttl_seconds=int(radar.get('ttl_seconds', 600)),
                max_stale_seconds=int(radar.get('max_stale_seconds', 86400)),
                timeout_seconds=float(radar.get('timeout_seconds', 3)),
            )
        if name == 'contextcord_replay':
            from .replay import replay
            return replay(self.repo, **arguments)
        from .cli import main
        commands = {'contextcord_context': ['context','--json'], 'contextcord_identity': ['identity'],
                    'contextcord_verify': ['verify','--ci'], 'contextcord_authorize': ['authorize'],
                    'contextcord_start': ['start','--json'], 'contextcord_checkpoint': ['checkpoint'],
                    'contextcord_advance': ['state','advance'], 'contextcord_finish': ['finish']}
        argv = ['--repo', str(self.repo), *commands[name]]
        for key, value in arguments.items():
            option = 'summary-text' if key == 'summary' and name == 'contextcord_finish' else key.replace('_','-')
            # Equals form prevents values beginning with '-' from becoming options.
            argv.append(f'--{option}={value}')
        output = io.StringIO()
        with redirect_stdout(output):
            rc = main(argv)
        value = json.loads(output.getvalue())
        if rc and value.get('status') not in {'FAIL','BLOCKED','ERROR'}:
            value['status'] = 'BLOCKED'
        return value
