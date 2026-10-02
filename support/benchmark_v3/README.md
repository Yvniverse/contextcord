# Live Benchmark v3 public fixture

This fixture is the public-synthetic task used by the Live Benchmark v3
runner. The runner copies only `starter/`, `TASK.md`, and the final bounded
context packet into a host trial workspace. It never copies the candidate pool
or raw archive into that workspace.

The hidden oracle is an external runner input. It is not stored here, copied
into a candidate checkout, included in a prompt, or recorded by path in trial
evidence.

The four arms are `NO_MEMORY`, `TEXT_HANDOFF`, `CONTEXTCORD_BM25`, and
`CONTEXTCORD_JEV`. BM25 selection and Jev Decision Fabric decisions happen
before the host turn; the host sees only the arm's final bounded packet.
