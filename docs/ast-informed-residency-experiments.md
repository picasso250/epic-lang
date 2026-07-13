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
