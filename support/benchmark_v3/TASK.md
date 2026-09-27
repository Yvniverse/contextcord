# Benchmark v2 task — relay continuation

You are continuing an unfinished Python SDK task in `starter/`.

Goal: harden the retry/resume behavior without changing the public API.

Current contract visible to every arm:
- retry only HTTP 429 and 503;
- at most 4 attempts total;
- total scheduled delay must not exceed 1.2 seconds;
- preserve a server-provided checkpoint exactly when it is reusable;
- produce a deterministic report describing attempts and total scheduled delay;
- do not edit tests.

The repository intentionally contains an older partial implementation. Some production behavior was learned in a previous engineering session and is available only through the arm-specific handoff/memory/archive context. The independent oracle is hidden from the coding agent.

Do not invent results from the hidden oracle. Implement the best continuation you can from the information actually available to your arm.
