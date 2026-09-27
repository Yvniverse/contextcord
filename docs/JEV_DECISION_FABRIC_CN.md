# Jev Decision Fabric

Jev 是针对窄语义问题的可选 advisory provider。生产 `DecisionFabric` 先执行
确定性 gate，需要时发送 typed decision bundle，并记录 receipt。只有 effective
provider 为 `jev_api` 且没有 fallback 时，才使用 provider-backed ranking。

Jev 不负责完整性、secret 检测、权限授予、qualification、冻结测试、release
gate 或破坏性操作批准。如果 credential、SDK 或 allowlist endpoint 不可用，
benchmark selection boundary 会记录 `PROVIDER_UNAVAILABLE`，调用方不得把它
重新标记为 Jev live。
