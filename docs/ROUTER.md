# Adaptive Router

ContextCord's active router is Router v3. It produces a bounded advisory
route receipt from the closed `model × reasoning-effort × role` catalog;
policy, host permissions, budget and verification remain code-owned.

The deterministic planner is always available. Jev is an optional typed
provider used only for bounded semantic choices, and an unavailable or invalid
choice falls back to the planner without granting execution authority.

The analysis Catalog may contain external observations and CodexRadar priors.
The execution Catalog accepts only routes observed or explicitly configured on
the current host with authentication, permission, budget and non-fallback
evidence. A recommendation is never a host qualification.

Calibration and Local Outcome boundaries are documented in
[`ROUTER_ADAPTIVE_CALIBRATION_CN.md`](ROUTER_ADAPTIVE_CALIBRATION_CN.md).
This document is the active v3 receipt contract, and the optional semantic
provider is described in [`JEV_DECISION_FABRIC.md`](JEV_DECISION_FABRIC.md).
