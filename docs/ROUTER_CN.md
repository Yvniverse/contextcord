# Adaptive Router

ContextCord 当前活动 Router 为 v3。它从闭集的
`model × reasoning-effort × role` Catalog 生成有界 advisory route receipt；
策略、宿主权限、预算与验证仍由代码拥有最终边界。

确定性 planner 始终可用。Jev 是可选 typed provider，只参与有界语义选择；
缺少 SDK、key、网络或返回非法选择时回退到 planner，不授予执行权限。

analysis Catalog 可以包含外部观测与 CodexRadar prior；execution Catalog
只有在当前宿主具备认证、权限、预算、非 fallback，并且 route 被观察或显式
配置时才可进入。推荐结果不等于宿主 qualification。

Calibration 与 Local Outcome 边界见
[`ROUTER_ADAPTIVE_CALIBRATION_CN.md`](ROUTER_ADAPTIVE_CALIBRATION_CN.md)。
本文件即当前 v3 receipt 契约；可选语义 Provider 见
[`JEV_DECISION_FABRIC_CN.md`](JEV_DECISION_FABRIC_CN.md)。
