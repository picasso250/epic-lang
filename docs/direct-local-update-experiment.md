# Direct local update fusion experiment

本文记录在当前 self-host compiler 上尝试把 direct alloca 的局部更新：

```text
%old = load i64, ptr %local
%new = add %old, 1
store %new, ptr %local
```

直接降为：

```asm
add qword [rbp-local], 1
```

实验只接受 64-bit direct alloca、`add/sub/and/or/xor`、signed-imm32，以及能够证明两个
中间 result 没有其他 use 的模式。间接地址、窄整数、非立即数和不满足证明条件的序列保持
原 lowering。machine 层为此临时加入 Group-1 memory/immediate 编码。

## Baseline

基线为 `dev@036d87b` 的未修改 compiler/runtime，使用相同 v0 seed、输入、参数和输出位置：

| 指标 | Baseline |
|---|---:|
| wall samples | 1600.586 / 1618.137 / 1604.069 ms |
| wall median | 1604.069 ms |
| internal median | 1594 ms |
| GC STW median total | 563 ms |
| X64 items | 149,400 |
| `.text` bytes | 681,184 |
| `.data` bytes | 90,231 |
| exe size | 774,144 B |

## V1: general block-local single-use matching

V1 在 lowering 每个 instruction 时检查三条 MIR 窗口，并扫描当前 block，证明 load result 与
update result 都只有一个 use。语义验证通过：

- 13/13 test modules；
- 88 e2e；
- 9 examples；
- GC stress/tiny；
- bootstrap fixed point；
- memory/immediate exact-byte test；
- single-use fusion与 multi-use fallback targeted test。

| 指标 | Baseline | V1 | 变化 |
|---|---:|---:|---:|
| wall median | 1604.069 ms | 1639.271 ms | +35.202 ms, +2.19% |
| internal median | 1594 ms | 1625 ms | +31 ms, +1.94% |
| GC STW median total | 563 ms | 532 ms | -31 ms, -5.51% |
| X64 items | 149,400 | 149,801 | +401, +0.27% |
| `.text` bytes | 681,184 | 683,698 | +2,514 B, +0.37% |
| `.data` bytes | 90,231 | 90,293 | +62 B |
| exe size | 774,144 B | 776,704 B | +2,560 B |

三个 V1 wall samples 为 `1655.390 / 1633.533 / 1639.271 ms`，全部慢于 baseline 最慢样本。
局部更新本身更短，但逐 instruction matcher、block use scan 和 encoder 扩张增加了更大的
self-host workload。

## V2: whole-block three-instruction matching

V2 删除 use scan，只接受整个 block 恰好由 `load + update + store` 三条 instruction 组成的
模式；这覆盖 AST-to-MIR 自动生成的 `for.inc` block。现有 cross-block reuse metadata 继续排除
跨 block use。matcher 只在三 instruction block 上调用。

| 指标 | Baseline | V2 | 变化 |
|---|---:|---:|---:|
| wall median | 1604.069 ms | 1668.878 ms | +64.809 ms, +4.04% |
| internal median | 1594 ms | 1656 ms | +62 ms, +3.89% |
| GC STW median total | 563 ms | 515 ms | -48 ms, -8.53% |
| X64 items | 149,400 | 149,897 | +497, +0.33% |
| `.text` bytes | 681,184 | 684,084 | +2,900 B, +0.43% |
| `.data` bytes | 90,231 | 90,293 | +62 B |
| exe size | 774,144 B | 777,216 B | +3,072 B |

V2 wall samples 为 `1668.878 / 1668.196 / 1720.080 ms`。targeted machine/lowering tests 与
bootstrap fixed point 通过，但结果已明确回退，因此没有重复完整 suite。

## Conclusion

两个版本都不保留。这个 peephole 能把单个命中从约五个 X64 item 缩为一个，但当前 workload
中的命中数量不足以偿还：

- MIR pattern matching 与 safety proof 的 self-host 代码；
- memory/immediate ALU encoder 能力；
- lowering 主循环中的额外分支或 helper call。

GC STW 样本下降没有转化为总 wall 收益，且三个 wall 样本均稳定回退，不能作为保留理由。
后续不应重新尝试通用 direct local update fusion；只有已有 machine 能力、无需新增 use analysis，
或 profile 指向单个极热的固定 lowering 模式时才值得重开。

