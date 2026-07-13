# Match dispatch experiments

本组实验验证 typed AST 中的 ADT variant/tag 结构是否应直接影响 MIR 控制流。实验按删除重复
match materialization、平衡完整 ADT tag dispatch 的顺序串行进行；任一阶段出现不可接受结果就
停止后续阶段。

## Opportunity audit

Canonical self-host compiler 包含 129 个 ADT match、347 个 ADT case arms。其中 79 个 match 只有
一个显式 case；22 个 match 有至少四个 cases，并包含 200 个 arms。最大的 match 分别包含 45、
19、19、14 和 14 个 cases。

Literal match 只有四个，case 数分别为 11、12、20 和 11，而且全部匹配字符串 token kind；当前
self-host workload 没有值得优先优化的 integer match。

## Hoist ADT tag/payload and remove match slots

### Hypothesis

原 lowering 为每个 match 创建人工 `__match` local，先 store scrutinee，再在每个 dispatch block
重新 load scrutinee。ADT match 还会为每个 case 重复计算并加载 tag，进入 case 后再次加载
scrutinee 和 payload。

MIR value 本身已经有跨 block stack home，因此人工 local 不提供额外语义。ADT wrapper 的 tag 和
payload 布局固定，可以在 dispatch 入口各加载一次并让后续 blocks 直接使用对应 MIR values。

### Implementation

- 普通 literal match 直接在各 compare block 使用 `scrutinee_flow.value`；
- ADT match 删除 `__match` alloca/store；
- 非空 ADT case 集合在入口各加载一次 tag 和 payload；
- dispatch compares 复用 tag，case binding 复用 payload；
- case 顺序和线性 equality dispatch 保持不变。

### Correctness

Bootstrap fixed point、完整 13 模块测试、10 个 examples 和 91 个 e2e 测试全部通过。

### A/B result

基线为 `dev@42e2f1b`。两边使用相同 v0 seed、compiler/runtime sources、参数和输出位置，每边
三个等价样本。

| metric | baseline | match hoist | change |
|---|---:|---:|---:|
| wall samples | 1592.260 / 1573.192 / 1608.256 ms | 1565.912 / 1538.281 / 1548.795 ms | — |
| wall median | 1592.260 ms | 1548.795 ms | -43.465 ms, -2.73% |
| internal median | 1578 ms | 1516 ms | -62 ms, -3.93% |
| X64 items | 148,461 | 145,208 | -3,253, -2.19% |
| `.text` bytes | 684,786 B | 666,821 B | -17,965 B, -2.62% |
| `.data` bytes | 81,840 B | 81,808 B | -32 B, -0.04% |
| compiler exe | 769,024 B | 751,104 B | -17,920 B, -2.33% |

三个 hoist samples 全部快于 baseline 最快样本，time 和所有 size 指标同时改善。

### Decision

接受 match hoist，继续独立验证完整且至少四个 variants 的平衡 ADT tag tree。

## Balanced full ADT tag dispatch

### Hypothesis

对至少四个 cases 且显式覆盖 union 全部 variants 的 match，先按实际 tag 排序，再用
`icmp.ule` 生成平衡决策树。完整 match 不需要失败出口，因此 N 个 cases 只需 N-1 次比较；
最坏路径由线性的 O(N) 降为 O(log N)。小 match 和部分 match 仍保留线性 dispatch。

### Correctness

候选实现通过 bootstrap fixed point、完整 13 模块测试、10 个 examples 和 91 个 e2e 测试。

### A/B result

基线为上一阶段已接受的 match hoist。两边使用相同 v0 seed、compiler/runtime sources、参数和
输出位置，每边三个等价样本。

| metric | match hoist | balanced tags | change |
|---|---:|---:|---:|
| wall samples | 1565.912 / 1538.281 / 1548.795 ms | 1569.979 / 1539.210 / 1557.428 ms | — |
| wall median | 1548.795 ms | 1557.428 ms | +8.633 ms, +0.56% |
| internal median | 1516 ms | 1547 ms | +31 ms, +2.04% |
| X64 items | 145,208 | 146,185 | +977, +0.67% |
| `.text` bytes | 666,821 B | 671,774 B | +4,953 B, +0.74% |
| `.data` bytes | 81,808 B | 81,842 B | +34 B, +0.04% |
| compiler exe | 751,104 B | 756,224 B | +5,120 B, +0.68% |

wall samples 重叠，无法证明时间收益；median 反而略慢。候选实现的排序和建树逻辑也进入
self-host compiler，本身的代码成本超过了少数大型完整 match 减少的比较。

### Decision

拒绝并撤回平衡 tag tree。它没有显著时间收益，同时所有 size 指标均回退。按串行实验约束，
停止后续 integer binary search / jump-table 实验；保留已成功的 match hoist。
