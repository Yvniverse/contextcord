# Contributing to ContextCord

Thanks for helping improve ContextCord. Contributions are welcome across code, documentation, tests, host adapters, reproducible bug reports and research fixtures.

## Before you start

Small bug fixes, documentation improvements and focused tests can go straight to a pull request. For a new public API, storage/schema change, security-sensitive behavior, major host integration or product feature, open an issue first so the direction can be agreed before implementation work begins.

If an issue is already being worked on, coordinate there to avoid duplicate effort.

## Development setup

ContextCord supports Python 3.11+.

```bash
git clone https://github.com/Yvniverse/contextcord.git
cd contextcord
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
```

Before submitting a change, run the repository's current contract, brand/bilingual and package smoke checks in addition to the unit suite. Use the commands documented by the current `AGENTS.md` / release tooling instead of copying stale counts into a PR.

## What a good change includes

- A clear problem statement and focused scope.
- Tests for behavior changes, especially path handling, integrity, concurrency, migration and policy decisions.
- Documentation updates when a public command, schema or integration changes.
- No secrets, local databases, raw provider transcripts, `.work/` contents or machine-specific paths.
- Evidence that distinguishes config/contract validation from a real end-to-end host observation.

## Host adapters

Adapters stay thin: translate a host's real configuration and tool contract into ContextCord's MCP boundary; do not duplicate policy logic.

A new or changed adapter should include:

- an official host documentation reference;
- a version probe when the host exposes one;
- a copyable configuration template;
- required ContextCord tool names;
- validation/config-render tests;
- live evidence only when a real host was actually run.

`BUILT_IN` product status does not imply benchmark qualification. Never inherit another host's evidence.

## Schemas and compatibility

New active formats use ContextCord schema IDs. Retired command and schema aliases are removed. Use the explicit state importer for older on-disk state. Do not rewrite preserved historical evidence simply to make old names disappear.

Schema changes need an explicit version and compatibility tests when backward reading is supported.

## AI-assisted contributions

AI-assisted development is welcome — ContextCord exists for coding-agent workflows. The contributor still owns the submission. Review generated code and prose, run the tests, remove fabricated claims, and do not submit private model transcripts or credentials. If a model/tool behavior is material to reproducing a host experiment, record the observable version/model information in the evidence rather than in marketing copy.

## Pull requests

Keep pull requests reviewable. Explain what changed, why it changed, how it was tested, and any compatibility or evidence-boundary impact. The repository PR template contains the final checklist.

Security fixes should follow [SECURITY.md](SECURITY.md) instead of first disclosing exploitable details in a public pull request.

## Community

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Unless stated otherwise, contributions accepted into this repository are distributed under the project's [MIT License](LICENSE). Do not remove or rewrite legacy provenance in [NOTICE](NOTICE) without an ownership/provenance review.
