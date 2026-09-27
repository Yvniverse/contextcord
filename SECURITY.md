# Security Policy

ContextCord manages local engineering state, evidence and integrations with coding-agent hosts. Security issues that cross those boundaries are treated seriously.

## Supported versions

| Version | Security support |
| --- | --- |
| Current `0.6.x` Public Alpha line | Active |
| Legacy Project Harness / Agent-Nexus snapshots | Migration/read compatibility only |

Until a stable release exists, security fixes target the current Public Alpha line rather than maintaining every historical development snapshot.

## Report a vulnerability privately

Do **not** open a public issue containing an exploit, credential, private archive or sensitive project evidence.

When the repository is public, enable GitHub **Private vulnerability reporting** and use **Security → Report a vulnerability** as the preferred channel. While the repository is private or if private reporting is unavailable, contact the repository maintainer through a private contact method published by the `Yvniverse` GitHub account.

A useful report includes the affected ContextCord version/commit, operating system, host integration if relevant, minimal reproduction steps, expected/actual behavior, and sanitized logs or proof of impact.

## In scope

Examples include:

- secret or private-path leakage through receipts, portable bundles or host packets;
- path traversal or unsafe archive extraction;
- incorrect source-identity or evidence-integrity verification that enables stale/forged state to be accepted as current;
- permission or policy bypass in ContextCord-owned mutation paths;
- unsafe migration behavior that can overwrite or lose user state;
- MCP/adapter behavior that exposes more ContextCord authority than configured;
- security-sensitive process handling defects in ContextCord-owned runners.

## Security model boundaries

ContextCord is not an operating-system sandbox. Coding agents, project hooks, local commands and third-party host plugins run with the permissions provided by their host/environment. Use host-native approvals, isolated environments and protected branches for untrusted code.

Third-party host/provider vulnerabilities should be reported to that vendor unless ContextCord's integration creates or materially amplifies the issue.

## Disclosure and fixes

Please allow maintainers to investigate and prepare a fix before public disclosure. Security fixes should include regression tests where feasible and should preserve evidence/provenance needed to understand affected versions.
