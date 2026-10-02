# ContextCord interface migration

The installed CLI is contextcord, the import package is contextcord, and MCP servers and tools use the contextcord namespace. Retired CLI entrypoints, forwarding packages, MCP aliases and duplicate plugins have been removed. New schemas use contextcord IDs in both source and installed wheels.

Update host configuration with contextcord adapter config --host <host>, then remove previously installed duplicate server entries. Reinstall the package to refresh console scripts.

To recover an older repository state, run contextcord migrate --dry-run and contextcord migrate --apply. This explicit importer backs up the original state and verifies copy equality. Frozen receipts retain their original bytes and schema IDs; new receipts use the current schema generation.
