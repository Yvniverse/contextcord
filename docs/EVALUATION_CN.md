# Evaluation

公开 artifacts 描述两个机制测量：

| 数据 | 范围 | 重算 |
| --- | --- | --- |
| [Continuity](../evaluation/continuity/README.md) | 60 个 task-spec-derived fixtures；状态恢复、源码变化、对象完整性和 UTF-8 packet 大小 | `python evaluation/continuity/recompute.py --check` |
| [Typed decisions](../evaluation/typed_decisions/README.md) | 30 个 live batches 中的 300 项 synthetic judgments；typed agreement 和请求延迟 | `python evaluation/typed_decisions/recompute.py --check --replay` |

Continuity 恢复 5,040 条 notes，task fields 和无损 note sets 各保留 60/60。
Handoff payload 共 217,067 B，bounded-text baseline 共 1,440,000 B，缩减 84.9%；
每个 baseline 上限为 24,000 B。源码变化使 180 条依赖 notes 进入 revalidation，
stale notes 被选择数为零；60 个 tampered objects 全部被拒绝。

Typed judgments 有 299/300 与 frozen operational rubric 一致（99.7%）。
30 个已记录请求按 nearest-rank 计算 P95 为 453 ms。
随附的 300-case deterministic replay 中 observed bypass 为零。

Rows 保留公开 task ID、task-spec digest、已解码 prediction、reference label、延迟观察和
最小 gate 输入。各数据目录 README 说明单位与评分规则。重算无需模型调用；gate replay
使用安装的 ContextCord policy 执行全部 cases。

当前 runtime tests 分别覆盖 BM25 selection、dependency drift、deterministic fallback、
event integrity 和并发 Handoff confirmation。
