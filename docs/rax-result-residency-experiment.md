# RAX result residency experiment

本实验针对 MIR lowering 的 eager result-home 约定：每条产生结果的指令都把 `rax` 写入
`[rbp+value_slot]`。已有 adjacent reload peephole 能删除紧随其后的同寄存器 reload，但仍保留
result store。

## Hypothesis

基本块内的非指针临时值大多只使用一次，并由下一条指令立即从 `rax` 消费。对这些值，lowering
可以让结果短暂驻留在 `rax`，同时省去 result store 和随后已经由 peephole 删除的 reload。

## Opportunity probe

在不改变 X64IR 的统计版本中，使用既有 `reusable_values` 和 block-local use count 对收敛编译器
的 MIR 做审计：

| 项目 | 数量 |
|---|---:|
| block-local reusable values | 14,182 |
| reusable value uses | 14,151 |
| single-use values | 13,998 |
| next semantic instruction immediately consumes | 11,820 |
| next consumer reads operand 0 through `rax` | 9,005 |
| calls with values live across them | 651 |
| live values crossing calls | 679 |

6,867 个基本块的活跃值峰值分布为：

| 峰值 | blocks |
|---:|---:|
| 0 | 2,076 |
| 1 | 4,319 |
| 2 | 436 |
| 3 | 25 |
| 4+ | 11 |

93.1% 的基本块峰值不超过一个，99.5% 不超过两个。因此第一版只追踪 `rax`，不引入完整
liveness 或多寄存器分配器。

## Selected implementation

每个 block 重新计算既有 block-local use count。一个 result 仅在以下条件全部成立时留在
`rax`：

- `reusable_values[result_id]` 已证明它不跨 block，且满足现有 GC stack-home 约束；
- result 只有一次使用；
- 下一条非 `alloca` MIR instruction 从 operand 0 加载 `rax`，或 terminator 将它加载到 `rax`；
- 下一消费者不是 call；
- result 不是已经由 terminal compare fusion 消除的 compare result。

`mir_to_x64_store_result` 对命中值记录 `rax_value_id` 并跳过 stack store。下一次
`mir_to_x64_load_operand("rax", value)` 命中同一 ID 时直接消费寄存器值。状态在消费、其他
`rax` load、函数开始和 block 边界清除。

非 GEP pointer result、跨 block value、多次使用 value、右 operand 消费和 call 参数仍使用
原有 stack home。第一版继续为命中值规划 slot，因此 frame size 暂不改变。

## A/B result

基线为本分支 `61fe03b`，两边使用相同 v0 seed、compiler/runtime sources、参数和输出位置。
wall time 使用外部 `perf_counter_ns()`，每边测量三次。

| 指标 | baseline | RAX residency | 变化 |
|---|---:|---:|---:|
| wall samples | 1750.798 / 1701.923 / 1675.479 ms | 1656.055 / 1650.591 / 1657.276 ms | — |
| wall median | 1701.923 ms | 1656.055 ms | -45.868 ms, -2.70% |
| internal median | 1687 ms | 1640 ms | -47 ms, -2.79% |
| X64 items | 157,479 | 149,675 | -7,804, -4.96% |
| `.text` bytes | 726,098 B | 692,903 B | -33,195 B, -4.57% |
| `.data` bytes | 81,840 B | 81,840 B | 0 |
| compiler exe | 810,496 B | 777,216 B | -33,280 B, -4.11% |

三个 residency samples 全部快于 baseline 最快样本。完整模块测试、examples、e2e 和 bootstrap
fixed point 均通过。

## Decision

保留单 `rax` result residency。它覆盖约九千个 self-host 热路径机会，并以较小的 block-local
状态替代 result store；time、X64 items、`.text` 和最终 exe size 同时改善。

右 operand 驻留、跨非 clobber instruction 的第二寄存器 cache，以及省去未物化 value slot
规划应作为独立后续实验，分别重新测量实现成本和收益。
