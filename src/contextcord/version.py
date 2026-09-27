"""Canonical ContextCord product and release identities."""

PRODUCT_NAME = "ContextCord"
DISTRIBUTION_NAME = "contextcord"
IMPORT_PACKAGE = "contextcord"
CLI_NAME = "contextcord"
MCP_SERVER_ID = "contextcord"
MCP_TOOL_PREFIX = "contextcord_"
STATE_DIR_NAME = ".contextcord"

# Kept only for versioned compatibility readers and deprecated forwarding
# commands.  Historical schema IDs and raw evidence are intentionally not
# rewritten by the brand migration.
LEGACY_PRODUCT_NAME = "Agent-Nexus"
LEGACY_DISTRIBUTION_NAME = "project-operations-harness"
LEGACY_IMPORT_PACKAGE = "project_harness"
LEGACY_CLI_NAME = "project-harness"
LEGACY_MCP_SERVER_ID = "project-harness"
RELEASE_VERSION = "0.6.2a1"
RELEASE_LABEL = "0.6.2-alpha.1"

__version__ = RELEASE_VERSION
