# ContextCord 快速开始

## 安装

```powershell
python -m pip install -e ".[dev]"
contextcord init --profile generic
contextcord doctor
```

使用 `contextcord resume --assist` 创建或继续任务。CLI 保留本地任务
状态，并为下一宿主生成有边界的接续上下文。

## 连接宿主

Codex、Qoder、Cursor、OpenCode、WorkBuddy 的配置见[集成指南](INTEGRATIONS_CN.md)。
其它 MCP 宿主使用 BYOH Adapter Manifest。Adapter 只翻译原生语法，不决定
策略、权限或证据是否有效。

## 验证接续

创建新会话前检查源码身份、新鲜度与证据。只有为当前任务选择的最终 packet
才应该跨过宿主边界。完成改动前运行：

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
```
