from __future__ import annotations

import json
from pathlib import Path


CODEX_HOOKS = {
    "description": "ContextCord lifecycle guard. Review before trusting repository hooks.",
    "hooks": {
        "SessionStart": [{
            "matcher": ".*",
            "hooks": [{
                "type": "command",
                "command": "python3 -m contextcord hook-start --host codex",
                "commandWindows": "python -m contextcord hook-start --host codex",
            }],
        }],
        "PreToolUse": [{
            "matcher": "Bash|shell_command|exec_command",
            "hooks": [{
                "type": "command",
                "command": "python3 -m contextcord host-event --host codex --event pre-tool-use",
                "commandWindows": "python -m contextcord host-event --host codex --event pre-tool-use",
            }],
        }],
        "Stop": [{
            "hooks": [{
                "type": "command",
                "command": "python3 -m contextcord hook-stop --host codex",
                "commandWindows": "python -m contextcord hook-stop --host codex",
            }],
        }],
    },
}


QODER_SETTINGS = {
    "hooks": {
        "SessionStart": [{
            "hooks": [{"type": "command", "command": "python -m contextcord hook-start --host qoder"}],
        }],
        "PreToolUse": [{
            "matcher": "Bash|Write|Edit|Delete|Move|Rename|read|write|edit|bash|shell",
            "hooks": [{"type": "command", "command": "python -m contextcord host-event --host qoder --event pre-tool-use"}],
        }],
        "Stop": [{
            "hooks": [{"type": "command", "command": "python -m contextcord hook-stop --host qoder"}],
        }],
    }
}


OPENCODE_PACKAGE = {
    "name": "contextcord-opencode-local",
    "private": True,
    "type": "module",
    "dependencies": {"@opencode/plugin": "2.0.4"},
}


OPENCODE_PLUGIN = r'''import { Plugin } from "@opencode/plugin"
import { execFileSync } from "node:child_process"

function contextcord(args, cwd, payload) {
  const bin = process.env.CONTEXTCORD_BIN || process.env.POH_BIN || "contextcord"
  const out = execFileSync(bin, args, {
    cwd,
    input: payload === undefined ? undefined : JSON.stringify(payload),
    encoding: "utf8",
    env: process.env,
  })
  return JSON.parse(out || "{}")
}

export default Plugin.define({
  id: "contextcord",
  async setup(ctx) {
    const cwd = ctx.location.directory

    // Inject live project state before every primary agent model call. This is
    // model-visible context; hard enforcement remains in tool/permission hooks.
    await ctx.session.hook("context", (event) => {
      try {
        const value = contextcord(["context", "--json"], cwd)
        event.system.push({ type: "text", text: `CONTEXTCORD LIVE CONTEXT\n${JSON.stringify(value, null, 2)}` })
      } catch (error) {
        event.system.push({ type: "text", text: `ContextCord unavailable: ${String(error)}` })
      }
    })

    await ctx.tool.hook("execute.before", (event) => {
      const scope = process.env.CONTEXTCORD_SCOPE || process.env.HARNESS_SCOPE
      const task = process.env.CONTEXTCORD_TASK_ID || process.env.HARNESS_TASK_ID
      const args = ["host-event", "--host", "opencode", "--event", "pre-tool-use"]
      if (scope) args.push("--scope", scope)
      if (task) args.push("--task-id", task)
      try {
        contextcord(args, cwd, { tool_name: event.tool, tool_input: event.input, session_id: event.sessionID })
      } catch (error) {
        const stdout = error?.stdout?.toString?.() || ""
        let reason = stdout
        try { reason = JSON.parse(stdout).reason || stdout } catch {}
        throw new Error(`ContextCord denied tool call: ${reason || String(error)}`)
      }
    })

    // OpenCode v2 has no blockable session-stop hook equivalent. CI/qualification
    // remains the hard closeout boundary; this subscription records drift quickly.
    const controller = new AbortController()
    void (async () => {
      for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
        if (event.type === "session.idle") {
          try { contextcord(["drift"], cwd) } catch {}
        }
      }
    })()
    return () => controller.abort()
  },
})
'''


DEEPSEEK_PACKAGE = {
    "name": "dsh-contextcord",
    "version": "0.3.0-alpha.1",
    "type": "module",
    "main": "index.js",
    "files": ["index.js", "cordis.patch.yml"],
    "dsh": {"bundle": {"patch": "./cordis.patch.yml"}},
    "dependencies": {
        "@deepseek-ai/cordis": "*",
        "@deepseek-ai/dsh-tools": "*",
    },
}


DEEPSEEK_PLUGIN = r'''import { execFileSync } from "node:child_process"

export const name = "contextcord"
export const inject = ["tools"]

function contextcord(exec) {
  const bin = process.env.CONTEXTCORD_BIN || process.env.POH_BIN || "contextcord"
  const args = ["host-event", "--host", "deepseek", "--event", "pre-tool-use"]
  if (process.env.CONTEXTCORD_SCOPE || process.env.HARNESS_SCOPE) args.push("--scope", process.env.CONTEXTCORD_SCOPE || process.env.HARNESS_SCOPE)
  if (process.env.CONTEXTCORD_TASK_ID || process.env.HARNESS_TASK_ID) args.push("--task-id", process.env.CONTEXTCORD_TASK_ID || process.env.HARNESS_TASK_ID)
  try {
    const stdout = execFileSync(bin, args, {
      cwd: process.cwd(),
      input: JSON.stringify({ tool_name: exec.name, tool_input: exec.arguments, session_id: String(exec.callId) }),
      encoding: "utf8",
      env: process.env,
    })
    return { allowed: true, detail: JSON.parse(stdout || "{}") }
  } catch (error) {
    const stdout = error?.stdout?.toString?.() || ""
    let reason = stdout || String(error)
    try { reason = JSON.parse(stdout).reason || reason } catch {}
    return { allowed: false, reason }
  }
}

export function apply(ctx) {
  // `tools/pre-execute` is the native reorderable policy gate documented by
  // DeepSeek Harness. Existing sandbox/approval policy remains enabled.
  ctx.on("tools/pre-execute", async (exec, next) => {
    const decision = contextcord(exec)
    if (!decision.allowed) return { kind: "deny", reason: `ContextCord: ${decision.reason}` }
    return next()
  })
}
'''

DEEPSEEK_PATCH = '''- insert:\n    - id: contextcord\n      name: dsh-contextcord\n'''

GENERIC_README = '''# ContextCord generic adapter\n\nAny coding agent can use the CLI without a native plugin:\n\n1. At session start: `contextcord doctor && contextcord context`.\n2. Start/handoff a task with `contextcord start --task-id <id> --scope <scope>`.\n3. Before high-risk actions call `contextcord authorize --scope <scope> --operation <op> --target <target>`.\n4. Before lifecycle handoff or stop, run `contextcord finish --mode handoff ...`; complete CI closeout is a separate workflow/evidence gate.\n5. CI runs `contextcord verify --ci`.\n'''


CAPABILITIES = {
    "codex": {
        "session_context": True,
        "pretool_policy": True,
        "pretool_file_mutation": False,
        "pretool_shell": True,
        "stop_block": True,
        "lifecycle_observer": True,
        "notes": "SessionStart/Stop plus conservative shell-focused PreToolUse; native sandbox/permissions remain required for non-shell file mutation.",
    },
    "qoder": {
        "session_context": True,
        "pretool_policy": True,
        "pretool_file_mutation": True,
        "pretool_shell": True,
        "stop_block": True,
        "lifecycle_observer": True,
        "notes": "SessionStart, broad PreToolUse matcher, and blockable Stop hook.",
    },
    "opencode": {
        "session_context": True,
        "pretool_policy": True,
        "pretool_file_mutation": True,
        "pretool_shell": True,
        "stop_block": False,
        "lifecycle_observer": True,
        "notes": "Context and tool.execute.before enforcement; no equivalent hard Stop gate is claimed.",
    },
    "deepseek": {
        "session_context": False,
        "pretool_policy": True,
        "pretool_file_mutation": True,
        "pretool_shell": True,
        "stop_block": False,
        "lifecycle_observer": False,
        "notes": "Native tools/pre-execute gate; complete closeout remains CI/Trust-Plane authoritative.",
    },
    "generic": {
        "session_context": False,
        "pretool_policy": False,
        "pretool_file_mutation": False,
        "pretool_shell": False,
        "stop_block": False,
        "lifecycle_observer": False,
        "notes": "CLI-only integration; caller must invoke authorization/checkpoint/closeout explicitly.",
    },
}


# MCP is portable context/verification, not interception of host tools.
CAPABILITIES['cursor'] = {**CAPABILITIES['generic'], 'mcp': True,
                          'notes': 'Repository-scoped MCP; native tool interception is not claimed.'}
CAPABILITIES['claude'] = {**CAPABILITIES['qoder'], 'mcp': True,
                          'notes': 'Claude Code SessionStart/PreToolUse/Stop hooks plus MCP; contract-tested, live certification pending.'}
for _caps in CAPABILITIES.values():
    _caps['certification'] = 'contract-tested; live-host validation pending'


def capabilities(host: str | None = None):
    if host is None:
        return {name: dict(value) for name, value in sorted(CAPABILITIES.items())}
    if host not in CAPABILITIES:
        raise ValueError(f"unknown host: {host}")
    return dict(CAPABILITIES[host])


def check_requirements(host: str, requirements: dict[str, object]) -> dict[str, object]:
    caps = capabilities(host)
    missing = []
    for key, expected in requirements.items():
        if isinstance(expected, bool) and expected and not bool(caps.get(key)):
            missing.append(key)
    return {"status": "PASS" if not missing else "BLOCKED", "host": host, "capabilities": caps, "requirements": requirements, "missing": missing}


def render(host: str, destination: Path) -> list[Path]:
    if destination.is_symlink():
        raise ValueError("adapter_destination_symlink")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("adapter_destination_must_be_empty_review_before_merge")
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if host in {"claude", "cursor"}:
        mcp = {"mcpServers": {
            "contextcord": {"command": "contextcord", "args": ["mcp"]},
        }}
        p = destination / (".mcp.json" if host == "claude" else "mcp.json")
        p.write_text(json.dumps(mcp, indent=2) + "\n", encoding="utf-8"); written.append(p)
        if host == "claude":
            hooks = json.loads(json.dumps(QODER_SETTINGS).replace("--host qoder", "--host claude"))
            p = destination / "settings.json"
            p.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8"); written.append(p)
        p = destination / "README.md"
        p.write_text("# " + host + " adapter\n\nMerge reviewed configuration into " +
                     ("`.claude/settings.json` and repository `.mcp.json`." if host == "claude" else "`.cursor/mcp.json`.") +
                     " Set MCP args to `[\"--repo\", \"/absolute/repository\", \"mcp\"]` when the host does not set repository cwd. "
                     "MCP defaults to inspection; `--allow-mutations` enables workflow tools. It never executes arbitrary commands. "
                     "Keep native host permissions enabled.\n", encoding="utf-8"); written.append(p)
    elif host == "codex":
        p = destination / "hooks.json"
        p.write_text(json.dumps(CODEX_HOOKS, indent=2) + "\n", encoding="utf-8")
        written.append(p)
    elif host == "qoder":
        p = destination / "settings.json"
        p.write_text(json.dumps(QODER_SETTINGS, indent=2) + "\n", encoding="utf-8")
        written.append(p)
        r = destination / "README.md"
        r.write_text(
            "# Qoder adapter\n\nMerge `settings.json` into `.qoder/settings.json`. "
            "The common adapter intentionally uses SessionStart, PreToolUse, and Stop so the same project config works across Qoder surfaces; "
            "SessionStart also refreshes context after handoff/compact where supported. "
            "Set `HARNESS_TASK_ID` and `HARNESS_SCOPE` for deterministic project-specific mutation authorization. "
            "Keep Qoder native permissions enabled.\n",
            encoding="utf-8",
        )
        written.append(r)
    elif host == "opencode":
        (destination / "plugins").mkdir(exist_ok=True)
        p = destination / "package.json"
        p.write_text(json.dumps(OPENCODE_PACKAGE, indent=2) + "\n", encoding="utf-8")
        written.append(p)
        p = destination / "plugins" / "contextcord.js"
        p.write_text(OPENCODE_PLUGIN, encoding="utf-8")
        written.append(p)
        r = destination / "README.md"
        r.write_text(
            "# OpenCode adapter\n\nCopy/merge this directory into `.opencode/`. "
            "This targets the current OpenCode V2 plugin API: live context injection plus `tool.execute.before` enforcement. "
            "Keep OpenCode native permissions enabled.\n",
            encoding="utf-8",
        )
        written.append(r)
    elif host == "deepseek":
        p = destination / "package.json"
        p.write_text(json.dumps(DEEPSEEK_PACKAGE, indent=2) + "\n", encoding="utf-8")
        written.append(p)
        p = destination / "index.js"
        p.write_text(DEEPSEEK_PLUGIN, encoding="utf-8")
        written.append(p)
        p = destination / "cordis.patch.yml"
        p.write_text(DEEPSEEK_PATCH, encoding="utf-8")
        written.append(p)
        r = destination / "README.md"
        r.write_text(
            "# DeepSeek Harness adapter\n\nOut-of-tree `dsh.bundle` plugin using the native `tools/pre-execute` policy gate. "
            "Install it into a reviewed DeepSeek Harness profile and keep the native sandbox/approval layers enabled.\n",
            encoding="utf-8",
        )
        written.append(r)
    elif host == "generic":
        p = destination / "README.md"
        p.write_text(GENERIC_README, encoding="utf-8")
        written.append(p)
    else:
        raise ValueError(f"unknown host: {host}")
    return written
