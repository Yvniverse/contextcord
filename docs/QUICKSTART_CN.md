# 快速开始

使用 Python 3.11+ 从源码安装：

```bash
python -m pip install -e .
```

下列命令在你自己的 Git 项目中运行；项目需有至少一个 commit 和 `AGENTS.md` 策略文件。
`init` 写入可编辑的 `.contextcord` TOML；使用前检查 scope 权限和 evidence 要求。

```bash
contextcord init --profile generic
contextcord doctor
contextcord feature profile continuity
contextcord start --task-id retry-policy --scope code --json
contextcord memory note add --task-id retry-policy --text "Retry budget is bounded; add timeout tests." --depends-on src/client.py
contextcord handoff --assist --task-id retry-policy
```

替换为项目中存在的 dependency path。Note 保存当前内容 hash；文件变化后，note 会变为
stale。Handoff 预览显示所选记录、源码身份和需要 revalidation 的记录。

保存 `start` 返回的 `session_id`。切换 session 前：

```bash
contextcord finish --session-id <session_id> --mode handoff --summary-text "Continue timeout tests."
contextcord handoff --assist --task-id retry-policy --yes
```

确认后创建一个 session 和一个 archived context job。已有 open session 或并发确认返回
`OPEN_SESSION_EXISTS`。`finish --mode complete` 单独检查 workflow 和 evidence gates；
`verify --profile handoff` 检查交接状态，`verify --ci` 检查完成状态。

导出及恢复 task state：

```bash
contextcord memory export --task-id retry-policy --out task-state.zip
contextcord memory import --bundle task-state.zip --dry-run
contextcord memory import --bundle task-state.zip
contextcord memory show --task-id retry-policy
```

在目标项目中执行 import。导入前验证对象与 source event chain；导入 evidence 保持
historical 分类。相同内容的重复导入具有幂等性。

[Host 配置](INTEGRATIONS_CN.md) · [架构](ARCHITECTURE_CN.md)。
