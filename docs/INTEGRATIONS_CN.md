# Host 集成

ContextCord 提供 Codex、Cursor、Qoder、OpenCode、WorkBuddy 的 adapter/config contracts；
host qualification 与集成支持分别记录。[运行时清单](runtime_surface.json) 列出完整工具面。

```bash
contextcord adapter config --host codex
contextcord adapter config --host cursor
contextcord adapter config --host qoder
contextcord adapter config --host opencode
contextcord adapter config --host workbuddy
```

命令打印可复制的配置，不修改 host 文件。通过 host 的 working-directory 设置选择项目，
或在 MCP 配置中将 `--repo <project>` 放在 `mcp` 参数前。

```bash
contextcord mcp
contextcord mcp --allow-mutations
```

完整 runtime 声明 16 个工具；默认开放只读子集，实际工具由 capability 与 mutation flag
决定。Handoff confirmation、start、checkpoint、advance、finish 需要开启 mutation。

`minimal` 包含 core/evidence；`continuity` 包含工程连续性、memory、handoff、MCP、hosts
与 closeout；`decision` 包含确定性决策、router 与 model intelligence；`full` 含全部 12 项
runtime capabilities。依赖自动闭包。

Jev 需另行安装、启用并在本地配置 `TYPESAFE_API_KEY` 或项目 `.env`：

```bash
python -m pip install -e ".[jev]"
contextcord feature enable jev
contextcord provider jev status
contextcord handoff --assist --task-id <id> --provider jev_api
```

Provider status 不返回凭证值。Provider 不可用时，Handoff 记录 deterministic fallback。
Adapter 只翻译 host events 与配置；权限、evidence 与 lifecycle 规则由 core 管理，实际执行
受 host 与 OS 约束。使用 `adapter capabilities --host <host>` 与
`adapter check --host <host> --scope <scope>` 检查差异。

[BYOH manifests](ADAPTERS.md) · [Typed decisions](JEV_DECISION_FABRIC_CN.md)。
