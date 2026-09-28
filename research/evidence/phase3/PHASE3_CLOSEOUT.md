# ContextCord Phase3 Live Closeout

## Scope

This closeout records the locked Phase3 live-execution result and makes the
reviewable evidence portable. It does not add product capabilities, change
the benchmark design, or rerun S0, S1, S2, or the formal Pilot.

## Environment

- Model: `gpt-5.6-luna`
- Reasoning effort: `max`
- Pier adapter: `0.3.1` Windows adapter
- Docker client/server: `29.6.1`
- Carbon-Transformer production: `4/4 running and healthy throughout`
- Execution source identity: private canonical internal main at start,
  `59787b82838178e26615557e239d7821a7d59aba`

## Preflight

Deterministic preflight and suite validation passed. The Docker preflight used
the locked address pools and a disposable Ubuntu smoke container. Benchmark
resource deltas were zero after cleanup.

## Provider and authentication

- Jev minimal provider smoke: `JEV_LIVE_PASS`.
- Host Codex model authentication: `PASS`.
- Pier sandbox Codex authentication: `MODEL_PROVIDER_UNAVAILABLE`.
- The Pier retry reached the sandbox, but the provider returned HTTP `401`
  and the sandbox observed an empty API credential.
- No secret value, raw provider payload, or sensitive credential material is
  included in this evidence.

## S0 first attempt

The first Phase A attempt was an infrastructure failure before model execution:
the Windows-launched Pier egress proxy bootstrap used CRLF line endings and
did not start correctly. No model completion or official verifier result was
produced.

## One permitted infrastructure retry

The single permitted retry used the environment-only line-ending remediation.
The proxy started and the task reached the Pier sandbox, where Codex returned
HTTP `401 Unauthorized` because the sandbox credential was empty. No valid
prefix, trial JSONL, model completion, or official verifier result was
produced.

## Final Phase3 status

- S0: `MODEL_PROVIDER_UNAVAILABLE`; valid trials: `0`; valid arms: none.
- S1 DeepSWE: `NOT_RUN`.
- S1 CCBench: `NOT_RUN`.
- S2: `NOT_RUN`; five locked tasks were not started.
- Formal Pilot: `NOT_RUN`.
- Performance conclusion: none.

S1, S2, and Pilot were not run because the provider blocker prevented a valid
S0 starting point. No result is inferred from the failed or unavailable
provider path.

## Regression summary

- `compileall`: `PASS`
- unittest: `168` tests, `8` skipped, `PASS`
- pytest: `160` passed, `8` skipped, `15` subtests, `PASS`
- Overlay regression: `3` tests, `PASS`
- Suite validation: `PASS`

## Docker and resource cleanup

The four production containers remained online and healthy. Benchmark network,
container, and running-resource deltas were all `0`; no benchmark resources
remained after cleanup.

## Limitations and next step

This closeout is a readiness and integrity record, not a benchmark result. A
future round may resume with a valid Pier sandbox model credential, beginning
with a new clean Phase-A generation. Provider qualification must pass before
formal S0 is restarted.
