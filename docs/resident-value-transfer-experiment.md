# Resident value transfer experiment

本实验是单 `rax` result residency 的后续。已保留的实现仅在下一消费者从 operand 0 或
terminator 使用 `rax` 时跳过 result home。这里验证 resident value 是否也应直接转移到下一
消费者实际需要的寄存器。

## Hypothesis

当下一条 MIR instruction 从右 operand、store address 或 Windows x64 register argument 消费
单次使用值时，producer 可以继续省去 stack store。consumer 先执行 `mov target, rax`，再加载
会覆盖 `rax` 的其他 operand。与原有 store + reload 相比，每次应净减少一条 X64 instruction。

## Opportunity probe

统计版本在收敛 compiler 的 block-local、single-use、immediate-consumer values 上得到：

| Consumer shape | opportunities |
|---|---:|
| existing operand 0 residency | 7,759 |
| existing terminator residency | 1,253 |
| call register argument | 1,545 |
| store address | 939 |
| binary / compare right operand | 330 |
| call stack argument | 7 |
| other | 0 |

新增可覆盖机会共 2,814；7 个 stack argument 留在原路径，没有进入原型。

## Prototype

原型扩展 consumer 识别，并做三类转移：

- `call` 的前四个参数可从 resident `rax` 直接移动到 `rcx/rdx/r8/r9`；
- binary/compare 的右 operand 先移动到 `rcx`，再加载左 operand 到 `rax`；
- store address 先移动到 `rcx`，再加载 store value 到 `rax`。

为支持这些路径，`mir_to_x64_load_operand` 对所有目标寄存器检查 resident operand；binary、
compare 和 store lowering 增加加载顺序分支；producer 判断扫描下一 instruction 的 operand
位置和 consumer opcode。

bootstrap fixed point、完整 13 模块测试、examples 和 91 个 e2e 测试全部通过。

## A/B result

基线为 `dev@a38841c` 的单 `rax` residency。两边使用相同 v0 seed、compiler/runtime sources、
参数和输出位置，每边测量三次。

| 指标 | baseline | transfer prototype | 变化 |
|---|---:|---:|---:|
| wall samples | 1656.055 / 1650.591 / 1657.276 ms | 1777.767 / 1793.517 / 1802.310 ms | — |
| wall median | 1656.055 ms | 1793.517 ms | +137.462 ms, +8.30% |
| internal median | 1640 ms | 1781 ms | +141 ms, +8.60% |
| X64 items | 149,675 | 147,376 | -2,299, -1.54% |
| `.text` bytes | 692,903 B | 679,201 B | -13,702 B, -1.98% |
| `.data` bytes | 81,840 B | 81,840 B | 0 |
| compiler exe | 777,216 B | 763,904 B | -13,312 B, -1.71% |

三个 prototype samples 全部慢于 baseline 最慢样本。size 收益明确，time regression 同样明确。

## Diagnosis

单 `rax` residency 的命中判断只检查固定 operand 0。transfer 原型为了再覆盖 2,814 次，在约
46,700 条 MIR instruction 和所有 operand load 的热路径上新增了：

- 下一 instruction operand 线性扫描；
- call/store/binary/icmp 字符串分类；
- 每次 operand load 的 resident union match；
- binary、compare 和 store 的额外加载顺序分支。

这些检查由 self-host compiler 每次编译永久支付。目标程序少 2,299 条 X64 instruction，仍不
足以抵消 lowering 判断成本。结果再次说明 opportunity count 只能证明上限；判断是否命中的
动态成本同样需要进入假设。

## Decision

拒绝并完整移除 transfer prototype，保留 `a38841c` 的 operand-0/terminator residency。按照
串行实验规则，到此停止，不继续 stack argument 或第二寄存器 cache。

未来 codebase 演进后可以重新评估，但新实现需要避免在通用 `load_operand` 和每条 instruction
上重复分类。可行前提是利用既有 block scan 一次性生成紧凑 consumer kind，或让 MIR lowering
本身提供直接消费形状，再单独验证该 metadata 的构建成本。
