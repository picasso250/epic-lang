# AST-informed residency experiments

本组实验验证 typed AST lowering 是否应把已知的 producer/consumer 关系保留到 MIR，避免
MIR-to-X64 在热路径重新扫描和分类。实验按 binary shaping、call hint、store-address hint 的顺序
串行进行；任一阶段出现不可接受的正确性、time 或 size 结果，就停止后续阶段。

## Binary MIR shaping

### Hypothesis

普通二元表达式先按源码顺序求值 left、再求值 right。若 right 是当前 block 最新产生的 result，
则交换可交换运算的 MIR operands，或交换有序比较 operands 并反转 predicate，可以让现有
operand-0 `rax` residency 直接消费 right，同时保持源码副作用顺序不变。

统计中 327 个 single-use immediate RHS 机会里，169 个属于可交换运算，126 个属于可交换并
反转 predicate 的比较；共 295 个，占 90.2%。其余 32 个非交换运算保持原顺序。

### Implementation

AST-to-MIR 只在 right operand 等于当前 block 最新 result 时 shaping：

- `add`、`mul`、`and`、`or`、`xor`、`icmp.eq`、`icmp.ne` 交换 operands；
- signed/unsigned ordered compare 交换 operands，并互换 `lt/gt`、`le/ge` predicate；
- string、shift、subtract、divide 和 remainder 保持原 lowering。

left 和 right 的 AST 求值顺序没有改变。实现没有增加 MIR metadata，也没有扩展后端通用 operand
load 路径。

### Correctness

Bootstrap fixed point、完整 13 模块测试、10 个 examples 和 91 个 e2e 测试全部通过。

### A/B result

基线为 `a38841c` 的单 `rax` residency。两边使用相同 v0 seed、compiler/runtime sources、参数和
输出位置；同日分别测量三个等价样本。

| metric | baseline | binary shaping | change |
|---|---:|---:|---:|
| wall samples | 1720.976 / 1731.198 / 1731.726 ms | 1664.294 / 1648.861 / 1613.927 ms | — |
| wall median | 1731.198 ms | 1648.861 ms | -82.337 ms, -4.76% |
| internal median | 1719 ms | 1640 ms | -79 ms, -4.60% |
| X64 items | 149,675 | 149,764 | +89, +0.06% |
| `.text` bytes | 692,903 B | 692,736 B | -167 B, -0.02% |
| `.data` bytes | 81,840 B | 81,840 B | 0 |
| compiler exe | 777,216 B | 777,216 B | 0 |

三个 shaping samples 全部快于 baseline 最快样本。辅助判断增加少量 X64IR items，但最终
`.text` 略小，data 和 exe 不变；time 改善稳定且显著。

### Decision

接受 binary MIR shaping，继续独立验证 call immediate-use hint。

## Call immediate-use hint

### Hypothesis

AST-to-MIR 在求值 call arguments 时已经知道当前 block 最新 result 属于哪个参数。把这个关系
编码为 target-neutral 的 operand index，可以让后端直接决定 Windows x64 register argument，
避免重新扫描下一 instruction、分类 consumer，或在通用 operand load 路径增加 resident 检查。

当前统计的 1,534 个 call immediate-use 机会里，1,528 个属于前四个 register arguments，只有
6 个属于 stack arguments。第一版只覆盖 register arguments。

### Implementation

`MirInst.immediate_operand_hint` 使用 0 表示无 hint，其他值编码 operand index + 1。AST-to-MIR
构造 call 时，仅当最新 MIR result 是前四个 operands 之一才设置 hint。

MIR-to-X64 的 single-use residency 判断先验证该固定 index 是否消费 producer result。call lowering
命中时直接把 resident `rax` 移到 `rcx`、`rdx`、`r8` 或 `r9`，跳过 result home store 和 argument
reload。通用 `mir_to_x64_load_operand` 没有新增分支或 union match。

Hint 不参与程序语义；MIR text 未携带 hint 时继续走原 lowering。

### Correctness

Bootstrap fixed point、完整 13 模块测试、10 个 examples 和 91 个 e2e 测试全部通过。

### A/B result

基线为上一阶段接受的 binary MIR shaping。两边使用相同 v0 seed、compiler/runtime sources、参数
和输出位置；每边三个等价样本。

| metric | binary shaping | call hint | change |
|---|---:|---:|---:|
| wall samples | 1664.294 / 1648.861 / 1613.927 ms | 1594.980 / 1603.465 / 1590.432 ms | — |
| wall median | 1648.861 ms | 1594.980 ms | -53.881 ms, -3.27% |
| internal median | 1640 ms | 1578 ms | -62 ms, -3.78% |
| X64 items | 149,764 | 149,111 | -653, -0.44% |
| `.text` bytes | 692,736 B | 688,372 B | -4,364 B, -0.63% |
| `.data` bytes | 81,840 B | 81,840 B | 0 |
| compiler exe | 777,216 B | 772,608 B | -4,608 B, -0.59% |

三个 call-hint samples 全部快于 binary-only 最快样本，且 time、X64 items、`.text` 和最终 exe
同时改善。

### Decision

接受 call immediate-use hint。它验证了上次 resident-transfer 失败的核心复盘：producer/consumer
关系在 AST-to-MIR 直接编码后，后端无需为所有 instruction 和 operand 支付动态扫描成本。继续
独立验证 store-address hint。

## Store-address hint

### Hypothesis

Store-address 候选集中在 typed AST 已知的字段写入和聚合初始化。对紧邻 store 产生的 field
`gep`，把 address operand index 编码到同一个 `immediate_operand_hint`，可以让 store lowering
先把 resident `rax` 转移到 `rcx`，再把 value 加载到 `rax`，从而省去 address result home 和
reload。

### Implementation

AST-to-MIR 只在四个静态明确的位置使用 immediate-address store constructor：

- field assignment；
- struct field initialization；
- union tag initialization；
- union payload initialization。

这些位置覆盖统计中约 97% 的 store-address 候选。数组 store、compound field assignment 和 MIR
text runtime 保持原路径。后端只在 store hint 非零且 resident value ID 匹配时转移寄存器；hint
失效时自动回退到原有 address load。

### Correctness

Bootstrap fixed point、完整 13 模块测试、10 个 examples 和 91 个 e2e 测试全部通过。

### A/B result

基线为上一阶段接受的 call hint。两边使用相同 v0 seed、compiler/runtime sources、参数和输出
位置；每边三个等价样本。

| metric | call hint | store-address hint | change |
|---|---:|---:|---:|
| wall samples | 1594.980 / 1603.465 / 1590.432 ms | 1592.260 / 1573.192 / 1608.256 ms | — |
| wall median | 1594.980 ms | 1592.260 ms | -2.720 ms, -0.17% |
| internal median | 1578 ms | 1578 ms | 0 |
| X64 items | 149,111 | 148,461 | -650, -0.44% |
| `.text` bytes | 688,372 B | 684,786 B | -3,586 B, -0.52% |
| `.data` bytes | 81,840 B | 81,840 B | 0 |
| compiler exe | 772,608 B | 769,024 B | -3,584 B, -0.46% |

三个 wall samples 的区间重叠，按性能测量规则判定 time 变化不显著，不增加样本追逐噪声。
X64 items、`.text` 和最终 exe 的确定性下降明确。

### Decision

接受 store-address hint：没有可确认的 time 收益或回退，size 收益稳定。

## Cumulative result

最终实现相对原始 `a38841c` baseline：

| metric | original baseline | final | change |
|---|---:|---:|---:|
| wall median | 1731.198 ms | 1592.260 ms | -138.938 ms, -8.03% |
| internal median | 1719 ms | 1578 ms | -141 ms, -8.20% |
| X64 items | 149,675 | 148,461 | -1,214, -0.81% |
| `.text` bytes | 692,903 B | 684,786 B | -8,117 B, -1.17% |
| `.data` bytes | 81,840 B | 81,840 B | 0 |
| compiler exe | 777,216 B | 769,024 B | -8,192 B, -1.05% |

本组实验保留 binary MIR shaping、call operand hint 和 store-address hint。核心结论是：typed AST
和 AST-to-MIR 已知的 immediate-use 关系值得显式保留；target-neutral operand index 足以让后端
做局部寄存器决策，同时避免通用热路径扫描。
