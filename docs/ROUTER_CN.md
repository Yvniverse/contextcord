# Decision Plane 路由规划

可选路由规划从合格的 `model × reasoning-effort × role` catalog 中选择，并返回 receipt。
Host execution 为独立操作。确定性规则负责 eligibility、失败预算与 effective route；
外部 Model Intelligence 和可选 Jev 提供建议性数值。

```bash
contextcord feature profile decision
contextcord router shadow --input decision-state.json
contextcord route discover
contextcord router outcomes summary
```

`route discover` 默认不执行 probes。Capability states 区分已确认执行身份、显式配置、
unknown 和 unavailable；unknown/fallback 身份不会成为 execution evidence。
Local outcomes 关联实际身份与 verifier results。

Routing 与外部 Model Intelligence 为可选 alpha capabilities。
[公开 evaluation](EVALUATION_CN.md) 测量 continuity 和 typed decisions。
使用 `contextcord router --help` 查看预算与输出选项。
