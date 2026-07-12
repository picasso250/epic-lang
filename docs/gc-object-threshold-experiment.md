# GC object-count threshold removal experiment

本文记录 `experiment/remove-gc-tiny-count-check` 分支的实验。目标是验证：small-object
allocator 已改为固定尺寸 slab 后，是否仍需要独立的 live-object 数量阈值触发 GC。

## 原机制

GC 原本维护两套自适应阈值：

```text
bytes:   max(8 MiB, 2 * live_bytes)
objects: max(262,144, 2 * live_objects)
```

任一阈值达到即收集。small allocation 的 `live_bytes` 已按实际 8/16/24/32B slab class
slot 大小累计，而不是只按逻辑请求大小累计。因此 byte threshold 已能表示 small arena
的实际 payload 压力；object count 只把所有对象等价看待，无法区分 8B slot 和大对象。

一次临时触发原因探针显示，当前 self-hosted compile 的 9 次 GC 中，6 次由 byte threshold
触发，3 次由 object threshold 单独触发。探针只用于诊断，未保留在实现中。

## 变更

删除：

- `gc_object_threshold` global；
- allocation hot path 上 large/small object count 的加载、相加、比较和 `or`；
- collection 后 `2 * live_objects` 的阈值更新分支。

保留 large/small live-object count 本身，因为 mark/sweep、metadata 压紧和诊断仍需要它们。
small arena 耗尽和 large allocation 失败仍会强制 collection 并重试。

## Self-hosted compiler

先从冻结 v0 验证 fixed point，再复用收敛编译器对同一 workload 测 3 次 wall time。

| 指标 | 基线 | 删除数量阈值 | 变化 |
|---|---:|---:|---:|
| wall median | 3339.326 ms | 3296.094 ms | -43.232 ms, -1.29% |
| X64 items | 179,511 | 179,451 | -60 |
| `.text` bytes | 790,742 | 790,502 | -240 |
| exe size | 829,440 | 829,440 | 0 |

wall 样本有明显重叠，且删除后有一轮慢于全部基线，因此按项目规则结论为：**自举 wall
变化不显著**。确定性后端规模略有下降。

代表性 fixed-point run 中，GC collection 从 9 次降至 8 次，STW total 从 923 ms 降至
约 780 ms；peak working set 从 92.39 MiB 升至约 94.37 MiB。它们是单轮诊断值，不作为
独立性能结论。

## Tiny-object workload

`tests/gc/tiny.ep` 连续分配 8,000,000 个 8B `TinyBox`。两种 runtime 分别编译为独立
可执行文件，各运行 3 次：

| 指标 | 基线 | 删除数量阈值 | 变化 |
|---|---:|---:|---:|
| wall median | 1546.965 ms | 836.085 ms | -710.880 ms, -46.0% |
| collections | 30 | 7 | -23 |
| STW total median | 938 ms | 264 ms | -674 ms, -71.9% |
| peak working set median | 64.97 MiB | 66.44 MiB | +1.47 MiB, +2.3% |

三个新 wall 样本都快于三个基线样本，变化稳定且显著。slab 使分配和 metadata 成本按页摊薄，
但 object threshold 仍按对象个数过早触发 sweep；对于 8B class，它在约 2 MiB slot payload
时就触发，而 byte threshold 允许约 8 MiB。删除后用很小的内存增量换来了显著更少的
collection 和 STW。

## 结论

保留删除。slab allocator 之后，按 class-rounded live bytes 触发比独立 object count 更能
表达真实内存压力；数量阈值主要制造 tiny-object 过度收集。完整模块测试、81 个 e2e、8 个
examples、GC stress/tiny tests 和 bootstrap fixed point 均通过。
