# MIR module-name index experiment

本文记录在 `dev@a1746e7` 上对 compiler 内部字符串表示与名字查找的审计。目标不是把所有
名字改成整数，而是区分封闭集合、开放符号名和重复查找三类问题。

## Baseline

基线已经包含 numeric X64 opcode。使用同一 frozen v0 seed、canonical compiler/runtime
输入和宿主环境：

| 指标 | baseline |
|---|---:|
| wall samples | 1837.088 / 1842.764 / 1835.743 ms |
| wall median | 1837.088 ms |
| X64 items | 145,786 |
| `.text` bytes | 663,851 B |
| compiler exe | 703,488 B |

收敛 compiler 每次处理约 42,844 条 MIR instruction、145,786 个 X64 item 和 15,840 个
text relocation。`prepare MIR` 通常约 484–500 ms；machine symbol-table 构建约 31 ms。

## Rejected candidate: numeric MIR opcode

`MirInst.op: str -> i64` 的完整原型通过测试和 fixed point，并将 compiler exe 降至
699,904 B；但简单 text-to-ID mapping 的 wall median 为 1906.389 ms，较基线慢 3.77%。

原因是默认编译路径会从 committed runtime MIR text 解析约 1,153 条 helper instruction。
原实现直接保存解析得到的 mnemonic；numeric representation 反而新增 text-to-ID conversion。
长度/字节分派 decoder 虽减少字符串相等比较，却把 compiler 增至 706,560 B，仍不值得保留。

MIR opcode numericization 应等待以下任一条件成立：runtime helpers 不再通过默认热路径解析
text MIR；语言提供 scalar enum 和高效 `match`/switch；或者测量证明 text boundary
conversion 不再主导收益。

## Rejected candidate: numeric X64 registers

第一版保持调用点 `x64_reg("rax")`，在 X64IR 构造时转换为 packed register ID。machine
阶段明显变快，但转换成本移动到更早、更热的 MIR-to-X64 阶段，最终 wall median 为
2144.381 ms，慢 16.7%。

第二版让 packed register ID 从 MIR-to-X64 一直传到 machine，不再进行热路径字符串转换：

| 指标 | direct register IDs | 相对基线 |
|---|---:|---:|
| wall median | 1834.904 ms | -2.184 ms, -0.12%；不显著 |
| X64 items | 144,140 | -1,646 |
| `.text` bytes | 656,115 B | -7,736 B |
| compiler exe | 694,784 B | -8,704 B |

这是明确的 size-only 收益，但当前源码会出现 `x64_reg(48) # rax`。没有 enum 或 global const
时，可读性损失不足以换取时间中性的结果，因此不保留。未来 scalar enum 可把 packed encoding
封装为 nominal `X64Register` 后重新评估。

## Selected candidate: index names, keep strings

真正的 symbol 热点不在 COFF relocation：machine 已使用 hash index，symbol-table 构建只有
约 31 ms。热点是 MIR 对约 650 个函数进行的重复线性字符串扫描：

- runtime helper function/extern injection；
- unresolved-call extern declaration；
- call signature validation；
- reachable-function traversal and pruning；
- referenced-extern collection and retention。

实现保留 `MirFunction.name`、`MirExtern.name` 和 `MirInst.callee` 的原始 `str`。每个阶段只为
当前数组建立临时 `NameIndex`，查找返回原数组 index；MIR text、诊断和 COFF symbol spelling
不变。这避免了全局 interner、ID lifetime、重编号和额外 reverse table。

共享 `NameIndex` 位于 `src/util.ep`，使用 power-of-two capacity、FNV hash 和线性探测。
索引只保存 `-2` 或非负值，因此用 `value + 3` 编码：零槽表示 empty，省去独立 occupancy
数组。动态插入路径按可证明的最终上界预分配；容量耗尽时明确 panic，不能无限探测。
Machine symbol resolution 也复用同一实现，但保留自己的 duplicate/unknown-name 诊断 wrapper。

## Final result

| 指标 | baseline | indexed names | 变化 |
|---|---:|---:|---:|
| wall samples | 1837.088 / 1842.764 / 1835.743 ms | 1694.956 / 1691.047 / 1694.347 ms | — |
| wall median | 1837.088 ms | 1694.347 ms | -142.741 ms, -7.77% |
| X64 items | 145,786 | 146,734 | +948, +0.65% |
| `.text` bytes | 663,851 B | 668,445 B | +4,594 B, +0.69% |
| compiler exe | 703,488 B | 707,584 B | +4,096 B, +0.58% |

三个 indexed-name samples 全部快于基线最快样本。收敛代 `prepare MIR` 约从 484–500 ms
降到 250–281 ms。4 KiB compiler-size 成本来自索引使用逻辑；共享实现已删除 machine/MIR
两份重复 hash-table code。

## Decision

推荐保留 MIR name indexing：它不改变 symbol representation，不降低 call-site 或诊断文本的
清晰度，并取得稳定约 7.8% self-host wall-time 收益。不要把该结论推广为“所有 symbol 都应
换成整数”；只有重复查找需要索引，名称本身仍是开放文本集合。

验收入口：

```powershell
python tests/run.py
python tests/examples/run.py
python bootstrap_fixed_point.py
python benchmark_self_host.py --label mir-name-index-final --refresh
```
