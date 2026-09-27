# Jev Decision Fabric

Jev is an optional advisory provider for narrow semantic questions. The
production `DecisionFabric` evaluates deterministic gates first, sends a typed
decision bundle when required, and records a receipt. Provider-backed ranking
is used only when the effective provider is `jev_api` and no fallback occurred.

Jev never owns integrity, secret detection, permission grants, qualification,
frozen tests, release gates or destructive approval. If credentials, SDK or the
allowlisted endpoint are unavailable, the receipt is `PROVIDER_UNAVAILABLE` at
the benchmark selection boundary and the caller must not relabel it as Jev live.
