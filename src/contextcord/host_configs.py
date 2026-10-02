"""Versioned, copyable host configuration templates.

The generator only produces configuration.  A generated snippet is
``CONFIG_TEMPLATE_ONLY`` until the named host actually starts the local MCP
server and reads a real Task/Note through it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


HOSTS = ("codex", "claude", "cursor", "opencode", "qoder", "workbuddy", "generic")


def _repo_value(repo_path: str | Path | None) -> str:
    if repo_path is None:
        return "."
    return Path(repo_path).resolve().as_posix()


def _shell_quote(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def generate_host_config(host: str, *, repo_path: str | Path | None = None) -> dict[str, Any]:
    host = str(host).casefold()
    if host not in HOSTS:
        raise ValueError(f"unknown host: {host}")
    repo = _repo_value(repo_path)
    args = ["--repo", repo, "mcp"] if repo != "." else ["mcp"]
    server = {"command": "contextcord", "args": args}
    if repo != ".":
        server["cwd"] = repo
    if host == "codex":
        content = "[mcp_servers.contextcord]\ncommand = \"contextcord\"\n"
        content += "args = [" + ", ".join(json.dumps(value) for value in args) + "]\n"
        if repo != ".":
            content += f"cwd = {json.dumps(repo)}\n"
        return {
            "host": host, "status": "CONFIG_TEMPLATE_ONLY", "format": "toml",
            "target_path": "~/.codex/config.toml or .codex/config.toml",
            "content": content,
            "verify": "codex mcp list (then call contextcord_memory and contextcord_memory_recheck)",
        }
    if host == "claude":
        command = "claude mcp add contextcord -- contextcord"
        if repo != ".":
            command += f" --repo {_shell_quote(repo)}"
        command += " mcp"
        return {
            "host": host, "status": "CONFIG_TEMPLATE_ONLY", "format": "shell",
            "target_path": "terminal command",
            "content": command,
            "verify": "claude mcp list, reload the project, then call contextcord_memory",
        }
    if host == "cursor":
        return {
            "host": host, "status": "CONFIG_TEMPLATE_ONLY", "format": "json",
            "target_path": ".cursor/mcp.json or ~/.cursor/mcp.json",
            "content": json.dumps({"mcpServers": {"contextcord": server}}, ensure_ascii=False, indent=2) + "\n",
            "verify": "cursor-agent mcp list-tools contextcord or open Cursor MCP and call contextcord_memory",
            "official_docs": "https://docs.cursor.com/context/model-context-protocol",
        }
    if host == "opencode":
        opencode_server = {"type": "local", "command": ["contextcord", *args]}
        if repo != ".":
            opencode_server["cwd"] = repo
        return {
            "host": host, "status": "CONFIG_TEMPLATE_ONLY", "format": "json",
            "target_path": "opencode.json or opencode.jsonc (project config)",
            "content": json.dumps({"$schema": "https://opencode.ai/config.json", "mcp": {"servers": {"contextcord": opencode_server}}}, ensure_ascii=False, indent=2) + "\n",
            "verify": "opencode mcp list, then call contextcord_memory",
            "official_docs": "https://opencode.ai/v2/docs/mcp-servers",
        }
    if host == "qoder":
        command = "qoder mcp add contextcord -- contextcord"
        if repo != ".":
            command += f" --repo {_shell_quote(repo)}"
        command += " mcp"
        return {
            "host": host, "status": "CONFIG_TEMPLATE_ONLY", "format": "shell",
            "target_path": "terminal command or project .mcp.json",
            "content": command,
            "verify": "qoder mcp list or /mcp reload, then call contextcord_memory",
            "official_docs": "https://docs.qoder.com/cli/mcp-servers",
        }
    if host == "workbuddy":
        workbuddy_server = {"type": "stdio", "command": "contextcord", "args": args}
        return {
            "host": host, "status": "CONFIG_TEMPLATE_ONLY", "format": "json",
            "target_path": ".mcp.json (project) or ~/.codebuddy/.mcp.json (user)",
            "content": json.dumps({"mcpServers": {"contextcord": workbuddy_server}}, ensure_ascii=False, indent=2) + "\n",
            "verify": "codebuddy mcp list or reload CodeBuddy MCP and call contextcord_memory",
            "official_docs": "https://www.codebuddy.ai/docs/cli/mcp",
        }
    return {
        "host": host, "status": "CONFIG_TEMPLATE_ONLY", "format": "json",
        "target_path": "host-specific MCP settings",
        "content": json.dumps({"mcpServers": {"contextcord": server}}, ensure_ascii=False, indent=2) + "\n",
        "verify": "start the host's MCP client and call contextcord_memory",
    }
