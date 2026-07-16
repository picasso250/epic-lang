# Numeric X64 opcode ID experiment

本文记录把 self-hosted compiler 的 X64IR instruction opcode 从 `str` 改为 enum-like
`i64` ID 的实验。语言当前没有 scalar enum、全局 `let` 或 `const`，因此实现使用集中编号表，
并在数字使用点保留随行 mnemonic 注释；未来有 enum 后可机械迁移为 nominal type。

## 候选筛选

首先试验了 `Token.kind: str -> i64`。该版本完整通过测试，并将收敛 compiler 的
`.text` 从 669,702 B 降到 665,489 B、exe 从 709,120 B 降到 705,024 B；但 wall median
从 2012.244 ms 变为 2013.089 ms，性能变化不显著。因此按仓库性能规则回退，没有保留。

X64 opcode 是更热且边界更清晰的候选：每次 self-host compilation 会产生约 14.6 万个
X64IR item，machine encoder 原先会反复进行 mnemonic 字符串比较。符号名、寄存器名、
section 名和所有用户可见文本仍保持 `str`。

## Representation

`X64InstItem.op` 现在是 `i64`。完整 ID 到 mnemonic 映射集中在 `src/x64.ep`，范围按功能分组：

- `1..7`: move/address/call/return/stack/unconditional jump;
- `8..23`: canonical near-Jcc order，且 inverse condition 成对排列；
- `24..30`: integer ALU / compare / test;
- `31..43`: multiply/divide/shift/inc-dec/move-extension;
- `44..53`: setcc family。

生产代码中的数字 opcode 均带 `# x64 <mnemonic>` 随行注释，或者位于有明确范围注释的
family 判断中。`x64_opcode_text()` 是唯一的 ID -> text 边界，服务 pretty-print 和诊断。
MIR opcode 仍保持文本表示；`src/mir_to_x64.ep` 在 MIR -> X64IR 边界显式转换。

编号还编码了两项可读且直接的规律：

```text
8..23: near-Jcc opcode byte = 0x80 + (id - 8)
inverse Jcc ID = id ^ 1
```

这删除了两组重复字符串分派，同时让 machine encoding 直接使用整数。

## Validation

使用相同 frozen v0 seed、相同 compiler/runtime source workload、相同输出条件。每个变体先达到
fixed point，再由收敛 compiler 对同一 workload 测量三次，取 median。

| 指标 | string opcode baseline | numeric opcode | 变化 |
|---|---:|---:|---:|
| wall samples | 2009.718 / 2012.244 / 2016.610 ms | 1925.898 / 1928.679 / 1918.441 ms | — |
| wall median | 2012.244 ms | 1925.898 ms | -86.346 ms, -4.29% |
| X64 items | 146,864 | 145,786 | -1,078, -0.73% |
| `.text` bytes | 669,702 B | 663,851 B | -5,851 B, -0.87% |
| final exe size | 709,120 B | 703,488 B | -5,632 B, -0.79% |

三个 numeric-opcode wall samples 全部快于 baseline 最快样本，因此时间收益稳定且显著。
X64 item 数同时下降，是因为较短的 numeric dispatch implementation 自身产生更少代码。

验收入口：

```powershell
python tests/run.py
python tests/examples/run.py
python bootstrap_fixed_point.py
python benchmark_self_host.py --label x64-opcode-i64-final --refresh
```

## Decision

保留 numeric X64 opcode representation。它同时减少 self-host wall time、X64 item 数、`.text`
和最终 executable size；文本边界集中，源码中的数字由紧邻 mnemonic 注释及集中表解释，没有把
符号名或其他开放集合错误地整数化。
