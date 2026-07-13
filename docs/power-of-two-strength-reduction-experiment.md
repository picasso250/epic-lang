# Power-of-two strength-reduction experiment

本文记录 `experiment/pow2-strength-reduction` 分支对常量二次幂乘除法的审计与实验。目标是判断：
既然 GC bitmap 热路径曾将 `udiv 8` / `urem 8` 手写为 `shr 3` / `and 7`，是否应在
MIR-to-X64 中普遍执行 strength reduction，或者至少把 `runtime/mir/gc.ir` 中同类操作
全部改写。

## 机会审计

使用临时 instrumented compiler 统计未修改 `dev@2f9c247` 的最终 self-host MIR。统计器只存在
于审计 compiler 中；编译该统计器后恢复原源码，再让它编译原始 `dev`，因此下表不包含正式
实现改动产生的额外 workload。

| MIR op | 常量 RHS 总数 | 二次幂 RHS |
|---|---:|---:|
| `mul` | 64 | 43 |
| `sdiv` | 63 | 63 |
| `srem` | 5 | 5 |
| `udiv` | 9 | 7 |
| `urem` | 5 | 3 |
| 总计 | 146 | 121 |

最集中的单项是 `sdiv 8`，共 43 处，主要来自 machine/backend 的寄存器编码、字节拆分和
alignment 计算。GC MIR 中另有 31 个可直接改写的正二次幂 RHS：21 `mul`、7 `udiv`、
3 `urem`。

## 语义边界

以下改写可直接保持 64-bit 位模式语义：

```text
mul  x, 2^k -> shl x, k
udiv x, 2^k -> shr x, k
urem x, 2^k -> and x, 2^k - 1
```

但 `sdiv x, 2^k -> sar x, k` 对负数不等价。`sdiv` 向零截断，`sar` 向负无穷取整。实验使用
branchless bias 公式保持语义：

```text
q = (x + ((x >> 63) & (2^k - 1))) >> k
```

对应 X64IR 使用 `cqo` 产生 sign mask，再执行 `and/add/sar`。`srem` 需要更长的修正序列，
且当前只有 5 个机会，因此未纳入正式候选。

## 基线

基线来自内容寻址缓存，对应相同 frozen v0 seed、compiler/runtime 输入和宿主：

| 指标 | 基线 |
|---|---:|
| wall median | 3174.657 ms |
| X64 items | 179,451 |
| `.text` bytes | 790,502 |
| exe size | 829,440 B |

所有 self-host 变体均先验证 fixed point，再由收敛 compiler 对同一 workload 运行 3 次。

## Generic MIR-to-X64 variants

### G1: `mul` + unsigned `div/rem`

G1 将 `mul/udiv/urem` 的正二次幂 RHS 改为 shift/mask；大于 signed imm32 的 mask 使用
register fallback。

| 指标 | G1 | 相对基线 |
|---|---:|---:|
| wall median | 3262.574 ms | +87.917 ms, +2.77% |
| X64 items | 180,135 | +684 |
| `.text` bytes | 793,348 | +2,846 B |
| exe size | 832,000 B | +2,560 B |

三个 G1 wall 样本全部慢于三个基线样本。当前 backend 已能把 `mul x, C` 生成为
`imul r64, r64, imm`，所以乘法替换的收益很小，不足以偿还识别代码。

### G2: 加入语义正确的 signed division

G2 在 G1 上加入上述 bias sequence，覆盖全部 63 个 `sdiv 2^k`。

| 指标 | G2 | 相对基线 |
|---|---:|---:|
| wall median | 3224.328 ms | +49.671 ms, +1.56% |
| X64 items | 180,367 | +916 |
| `.text` bytes | 794,293 | +3,791 B |
| exe size | 833,024 B | +3,584 B |

G2 比 G1 快，但仍然三个样本全部慢于基线。移除 `idiv` 的收益真实存在，但 signed 修正序列
以及 optimizer 自身源码成本仍占上风。

### G3: compact division-only

G3 删除乘法优化，并把识别、mask fallback 和 signed sequence 合并为单个 helper。

| 指标 | G3 | 相对基线 |
|---|---:|---:|
| wall median | 3218.417 ms | +43.760 ms, +1.38% |
| X64 items | 180,390 | +939 |
| `.text` bytes | 794,612 | +4,110 B |
| exe size | 833,536 B | +4,096 B |

紧凑源码没有改变结论。把逻辑内联进较大的 lowering function 反而扩大了该函数的生成代码。

## Fixed-source codegen check

为隔离 optimizer 自身源码成本，基线 compiler 和 G2 compiler 分别编译同一个 detached
`dev@2f9c247` worktree，再运行两个同源产物各 3 次。

G2 生成的同源 compiler 相对基线为：

```text
X64 items: 179451 -> 179495  (+44)
.text:      790502 -> 790517 (+15 B)
exe:        829440 -> 829440
```

运行时间 median 为 `3229.092 -> 3204.008 ms`（-0.78%），但样本明显重叠，且 G2 有一轮
慢于全部基线，结论为性能变化不显著。这表明消除 `idiv` 可能改善生成程序，但收益不足以证明
通用 optimizer 的 self-host 成本合理。

## Targeted GC MIR variants

### T1: 全部 31 个机会

直接在 `gc.ir` 中改写 21 `mul`、7 `udiv`、3 `urem`，不增加 compiler 识别逻辑。

| 指标 | T1 | 相对基线 |
|---|---:|---:|
| wall median | 3204.835 ms | +30.178 ms, +0.95% |
| X64 items | 179,428 | -23 |
| `.text` bytes | 790,388 | -114 B |
| exe size | 829,440 B | 0 |

wall 样本重叠，变化不显著。`mul -> shl` 不减少 X64 item，只略改编码大小。

### T2: 只改 7 `udiv` + 3 `urem`

T2 保持 `mul` 的直观表达，只改写真正会进入 x64 `div` 的十处。

| 指标 | T2 | 相对基线 |
|---|---:|---:|
| wall median | 3254.578 ms | +79.921 ms, +2.52% |
| X64 items | 179,428 | -23 |
| `.text` bytes | 790,409 | -93 B |
| exe size | 829,440 B | 0 |

三个 T2 样本全部慢于基线。虽然确定性产物略小，但没有 wall 收益，不足以支持把更多 GC
算术改写为较低层的 shift/mask 表达。

## 结论

本实验不保留代码改动：

- 不加入 generic power-of-two strength-reduction pass；
- 不批量改写 GC 的常量乘除法；
- `mul x, 2^k` 当前已有便宜的 `imul immediate`，不是高收益方向；
- signed division 只有在 range analysis 能证明 operand 非负时，才能用单条 `sar`，否则修正
  序列和 compiler 复杂度很容易抵消收益；
- 保留 bitmap 实验中已经由专项热路径数据支持的 `udiv 8 -> shr 3`、`urem 8 -> and 7`，
  但不把这个局部结论泛化为全局规则。

未来只有在出现 MIR optimization framework、非负 range information，或 profiler 明确定位新的
`idiv` 热点时，才值得重新开启此方向。
