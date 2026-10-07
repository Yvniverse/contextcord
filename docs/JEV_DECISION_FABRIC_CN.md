# Typed decisions

Decision Plane 的初始 typed bundle 由 `decision_fabric.py` 的 `QUESTION_SPECS` 派生，
包含十类判断。[运行时清单](runtime_surface.json)。

Gate 0 根据候选歧义、源码变化、预算压力、archive 与 route 不确定性决定是否需要语义调用。
清晰的本地情形使用确定性策略；可选 Jev 返回有界 boolean/ordinal scores 和 enum choices。
深层阶段可请求 relevance scores，selection API 只返回候选池内的 ID。

Receipt 关联 state hash、Gate 0、typed answers、thresholds、provider/fallback 状态与
code actions。完整性、secret、permission、qualification、test、release、破坏性操作
失败均产生确定性 block actions；被 hard gate 阻止的 selection 为空。

Handoff 默认使用 BM25 和最多三条记录的本地选择。`--provider jev_api` 允许在有歧义的
候选池上执行可选语义选择。Provider 延迟加载；不可用或建议无效时记录 BM25 fallback。

[Synthetic typed evaluation](../evaluation/typed_decisions/README.md)。
