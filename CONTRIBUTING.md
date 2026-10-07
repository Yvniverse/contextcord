# Contributing

Focused fixes, reproducible bug reports, documentation and host adapter contracts
are welcome. Discuss new public APIs, storage formats and major host integrations
in a project issue before implementation.

## Development setup

Python 3.11+ is required. From a source checkout:

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m pytest -q
python scripts/check_contracts.py
python scripts/check_product_surface.py
python scripts/check_readme_metrics.py
python scripts/mcp_smoke.py
python -m build
```

On Windows use the virtual environment's `Scripts/python` when necessary.
Changes to integrity, path handling or concurrency require regression tests.
Keep adapter policy in core code and document public command/schema changes.

## Release inventory

`support/public_release_allowlist.json` is the exact release file inventory.
New files require an explicit inventory entry; `scripts/stage_public_release.py`
is the sole exporter. The two Git attribute/ignore templates are explicit
source mappings. The sidecar content manifest describes every emitted file.

```bash
python scripts/stage_public_release.py --destination .work/candidate --manifest .work/content-manifest.json
python scripts/check_public_release.py .work/candidate --manifest .work/content-manifest.json
```

Keep credentials, local state, provider transcripts and machine-specific paths
out of contributions. Evaluation changes must preserve recorded rows and provide
recomputation. Host support changes should include config/render checks;
qualification requires separately recorded execution evidence.

Explain the problem, resulting behavior and validation in pull requests.
[SECURITY.md](SECURITY.md) describes vulnerability reporting, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) governs participation.

Contributions use [Apache-2.0](LICENSE). Preserve existing attribution and notices.
