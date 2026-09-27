# 研究边界

## Context Sufficiency Test

确定性的四臂 fixture 使用相同源码和 runner 拥有的 oracle，测试不同 context
变体是否足够。它不是 live agent、宿主、模型、ranking 或 release claim。

## Live Benchmark v3

每个 trial 都创建新的 workspace。宿主只能看到 `TASK.md`、starter source、
tests 和一个最终的 `context/bounded_context.md`。candidate pool、raw archive
与 hidden oracle 留在宿主 workspace 外。BM25 运行真实的 Okapi selector；Jev
运行生产 Decision Fabric，并记录 provider 是否可用，不把 fallback 变成成功。

Qualification 需要独立 trials、visible/hidden tests、tests/context 不可变，以及
Jev arm 的 live provider。本地执行不代表 hosted CI。
