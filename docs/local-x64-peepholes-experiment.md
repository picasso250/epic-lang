# Local X64 lowering peephole experiments

本文记录 `experiment/local-x64-peepholes` 分支。该分支建立在
[`direct-alloca-memory-experiment.md`](direct-alloca-memory-experiment.md) 之上。目标不是引入
通用 register allocator 或 MIR optimization framework，而是寻找局部、可证明正确、能够直接
减少 X64 item 的 lowering 机会。

## Baseline and audit

原始基线为 `dev@3150ec0`，使用相同 frozen v0 seed 和宿主环境：

| 指标 | 原始基线 |
|---|---:|
| wall median | 3174.657 ms |
| X64 items | 179,451 |
| `.text` bytes | 790,502 |
| exe size | 829,440 B |

对该收敛 compiler 的 169,329 条机器指令做反汇编模式审计，发现：

| 模式 | 数量 |
|---|---:|
| alloca 地址先 `lea` 再 load/store | 15,066 |
| 相邻 result store 后，同寄存器 reload | 11,305 |
| `jmp` 到紧邻 label | 2,051 |
| `icmp` 物化 bool 后立即 cond-branch | 1,291 |

前三类不需要 alias analysis 或寄存器分配；第四类只需要证明比较结果没有其他 use。

## P0: direct alloca memory

P0 直接把当前函数 `alloca` 的 load/store 降为 `[rbp+addr_slot]`。完整实现和独立数据见
[`direct-alloca-memory-experiment.md`](direct-alloca-memory-experiment.md)。

| 指标 | P0 | 相对原始基线 |
|---|---:|---:|
| wall median | 3124.265 ms | -50.392 ms, -1.59% |
| X64 items | 164,581 | -14,870 |
| `.text` bytes | 746,157 | -44,345 B |
| exe size | 784,896 B | -44,544 B |

## P1: adjacent same-register reload

旧 lowering 为每个 MIR result 保留 stack home：

```asm
mov [rbp-slot], rax
mov rax, [rbp-slot]
```

如果两条 X64IR item 严格相邻，且 memory operand 的 base、displacement、width 与寄存器完全
一致，第二条 reload 不改变任何可观察值。P1 在 `x64_add_inst2` append 时删除 reload，但保留
store：

```asm
mov [rbp-slot], rax
```

只有以下条件全部成立才删除：

- 两条均为二 operand `mov`；
- 前一条是 `mov [base+disp], reg`；
- 当前条是 `mov reg, [base+disp]`；
- base、disp、width、reg 全部相同；
- 两者之间没有 label、call 或任何其他 X64IR item。

因此不需要追踪 register lifetime 或 memory alias。保留 store 也意味着 conservative GC 的
stack root 可见性不变。不同寄存器 reload、跨 label reload 和非相邻访问全部保留。

| 指标 | P1 | 相对 P0 |
|---|---:|---:|
| wall median | 2457.805 ms | -666.460 ms, -21.33% |
| X64 items | 153,032 | -11,549 |
| `.text` bytes | 693,482 | -52,675 B |
| exe size | 732,160 B | -52,736 B |

P1 的三个 wall samples 为 `2447.577 / 2457.805 / 2471.047 ms`，全部快于 P0 最快样本
`3122.841 ms`。优化后的反汇编中，同类安全模式从 12,108 个降到 5 个；剩余项在 X64IR
中被 label 隔开，因此正确保留。

## P2: unconditional fallthrough jump

旧 block lowering 经常产生：

```asm
jmp .Lnext
.Lnext:
```

`x64_bind_label` 绑定 label 时，如果最后一个 X64IR item 正是跳到该 label 的单 operand
`jmp`，直接 pop 掉该 jump。跳向其他 label 的 jump 保留。

| 指标 | P2 | 相对 P1 |
|---|---:|---:|
| wall median | 2442.209 ms | -15.596 ms, -0.63% |
| X64 items | 151,271 | -1,761 |
| `.text` bytes | 684,488 | -8,994 B |
| exe size | 723,456 B | -8,704 B |

wall 样本有重叠，结论为变化不显著；确定性指令数和代码大小收益明确。

## P3: terminal compare branch fusion

旧 lowering 把 comparison 当普通 bool value 物化，再由 terminator test：

```asm
cmp   rax, rcx
setl  al
movzx eax, al
mov   [rbp-slot], rax
test  rax, rax
jnz   .Lthen
jmp   .Lelse
```

当 block 最后一条 MIR instruction 是受支持的 `icmp`，且 condbr 正好使用该 result，P3
直接生成：

```asm
cmp rax, rcx
jl  .Lthen
jmp .Lelse
```

融合条件为：

- comparison 是 block 最后一条 instruction；
- terminator 是 `condbr`，condition value ID 等于 comparison result ID；
- `reusable_values[result_id] != 0`，即现有 use analysis 已证明它没有跨 block use；
- predicate 可由现有 machine branch subset 表达。

因为 definition 已是最后一条 instruction，同一 block 中不存在 definition 之后的第二个 use。
普通返回 bool、存储 bool 或作为其他表达式 operand 的 comparison 继续走 `setcc + movzx`。

当前融合 `eq/ne/slt/sle/sge`；`sgt` 使用等价的反向 `jle else`。unsigned branch 没有为了这项
优化扩张 machine ISA，因此仍物化 bool。

| 指标 | P3 | 相对 P2 |
|---|---:|---:|
| wall median | 2149.718 ms | -292.491 ms, -11.98% |
| X64 items | 147,385 | -3,886 |
| `.text` bytes | 672,612 | -11,876 B |
| exe size | 711,680 B | -11,776 B |

P3 wall samples 为 `2164.164 / 2149.719 / 2148.946 ms`，全部明显快于 P2。

## P4: conditional fallthrough inversion

P3 之后仍存在大量：

```asm
jnz .Lnext
jmp .Lother
.Lnext:
```

如果 condition inverse 已由 machine 支持，绑定 `.Lnext` 时可改写为：

```asm
jz .Lother
.Lnext:
```

当前只使用已有互反集合：

```text
jz  <-> jnz
jl  <-> jge
```

审计中 1,168 个候选有 1,162 个属于该集合；剩余 6 个 `jle` 需要尚未支持的 `jg`，原样保留。
该 peephole 只检查最后两个 X64IR item 与正在绑定的 label，不进行 CFG 重排。

| 指标 | P4 | 相对 P3 |
|---|---:|---:|
| wall median | 2063.102 ms | -86.616 ms, -4.03% |
| X64 items | 146,832 | -553 |
| `.text` bytes | 669,621 | -2,991 B |
| exe size | 708,608 B | -3,072 B |

净 X64 item 数小于理论删除数，是因为 self-host compiler 本身新增了 peephole helper；生成的
程序仍删除对应 trailing jump。P4 三个 wall samples 为
`2067.156 / 2053.531 / 2063.102 ms`，全部快于 P3。

## P5: complete canonical Jcc support

Machine originally encoded only `jz/jnz/jl/jle/jge`, even though MIR and `setcc` already represented the
full signed and unsigned integer comparison set. P5 adds the 16 canonical near-Jcc spellings:

```text
jo  jno  jb  jae  jz  jnz  jbe  ja
js  jns  jp  jnp  jl  jge  jle  jg
```

No aliases such as `je`, `jc`, or `jnae` are added. A single `machine_jcc_opcode` mapping is shared by
validation and encoding. The inverse mapping now covers all eight pairs, and terminal compare fusion directly
supports all ten integer MIR predicates:

```text
eq/ne
slt/sle/sgt/sge
ult/ule/ugt/uge
```

Exact opcode-byte tests cover `0F 80` through `0F 8F`; targeted MIR tests verify every predicate maps to its
canonical Jcc, while comparison results used as ordinary values still materialize `setcc + movzx`.

| 指标 | P5 | 相对 P4 |
|---|---:|---:|
| wall median | 2012.244 ms | -50.858 ms, -2.47% |
| X64 items | 146,864 | +32 |
| `.text` bytes | 669,702 | +81 B |
| exe size | 709,120 B | +512 B |

P5 wall samples 为 `2009.718 / 2012.244 / 2016.610 ms`，全部快于 P4 的三个样本。新增完整
encoder/helper 使确定性体积略增，但幅度很小；最终 exe 仍比 frozen v0 的 711,680 B 小
2,560 B。该结果满足“完整性收益且无明显 time/size 回退”的接受标准。

## Cumulative result

| 指标 | `dev@3150ec0` | P5 final | 累计变化 |
|---|---:|---:|---:|
| wall median | 3174.657 ms | 2012.244 ms | -1162.413 ms, -36.62% |
| X64 items | 179,451 | 146,864 | -32,587, -18.16% |
| `.text` bytes | 790,502 | 669,702 | -120,800 B, -15.28% |
| exe size | 829,440 B | 709,120 B | -120,320 B, -14.51% |

代表性 final fixed-point run 的 peak working set 约 88.6 MiB，原始基线约 94 MiB。内存值仅作
诊断，性能结论仍以 3 次等价 self-host wall samples 为准。

## Validation

最终版本通过：

- frozen v0 到 current bootstrap fixed point；
- 13/13 test modules；
- 81 e2e；
- 8 examples；
- GC stress/tiny；
- targeted direct-alloca、reload、fallthrough、all-predicate branch-fusion tests；
- exact byte tests for all 16 canonical Jcc opcodes and all eight inverse pairs；
- `git diff --check`。

## Conclusion

这组优化值得保留。它们共同特点是：

- 只依赖相邻 X64IR item、既有 slot metadata 或 block 最后一条 instruction；
- 不需要通用 dataflow、alias analysis 或 register allocator；
- safety predicate 不满足时保留旧 lowering；
- 同时产生显著 wall、instruction count 和 executable size 收益。

后续优先级已经明显下降：不同寄存器的 store/reload 只能把 memory reload 改成 register move，
不直接减少指令数；完整 register allocation 的历史实验则有明显 self-host complexity cost。

后续 direct alloca `load + ALU + store` 融合实验未能偿还 matcher 与 encoder 的 self-host 成本，
详见 [`direct-local-update-experiment.md`](direct-local-update-experiment.md)。
