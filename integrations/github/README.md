# GitHub integration

The Unified Project Harness keeps live SQLite state and generated closeout artifacts out of Source Truth. A fresh GitHub checkout therefore **cannot** honestly run `project-harness verify --ci` unless the closeout proof for that exact candidate is transported into the job.

## Portable Evidence Bundle

After a local or controlled-worker `finish --mode complete` succeeds, export a bundle **outside the repository**:

```bash
project-harness bundle export --path /tmp/project-harness-closeout.zip
```

The bundle contains the sealed receipt chain and the non-source Evidence referenced by the leaf receipt. Its manifest binds the bundle to the candidate SourceIdentity. Import rejects source-classified destinations and path/symlink escapes.

A real repository chooses its own trusted transport, for example a protected CI artifact, object store, or another reviewed handoff channel. The generic templates intentionally do not guess that authority.

## Shadow workflow

`project-harness-shadow.yml` always runs `doctor`, `identity`, and `release-identity` when the vendored wheel exists. If no portable bundle has been downloaded, it explicitly reports that closeout evidence was **not** certified. This is suitable while migrating a legacy Harness.

## Required workflow

`project-harness-enforce-vendored.yml` fails if the bundle is absent. Add a project-specific download step before the `Require and verify portable closeout evidence` step. The downloaded file must match the path in `PROJECT_HARNESS_BUNDLE`.

For qualification stored in Git Notes, the templates also attempt to fetch `refs/notes/project-harness`; projects using a custom notes ref should adjust that fetch to match `.harness/qualification.toml`.

## Important exact-commit rule

Do not commit a portable bundle after the candidate merely to make CI see it. In exact-commit mode, that would create a different candidate. Transport post-commit proof out-of-band instead.
