# Direct alloca memory lowering experiment

本文记录 `experiment/direct-alloca-memory` 分支。当前 MIR 为每个 `alloca` 分配固定的
`rbp`-relative address slot，但旧 lowering 仍先把该地址物化到寄存器，再执行内存访问：

```asm
lea rax, [rbp-slot]
mov rax, [rax]

lea rcx, [rbp-slot]
mov [rcx], rax
```

对当前函数自己的 `alloca`，地址在编译期已知，可直接使用：

```asm
mov rax, [rbp-slot]
mov [rbp-slot], rax
```

## Audit

对 `dev@3150ec0` 的收敛 compiler 反汇编，共有 169,329 条机器指令，其中：

```text
alloca load:  lea rax,[rbp+disp] + load [rax]    10,661
alloca store: lea rcx,[rbp+disp] + store [rcx]    4,405
total                                             15,066
```

这不是 alias analysis。只在 MIR operand 是 `MirValueOperand` 且对应
`lower.addr_slots[value_id]` 非零时触发；该表只为当前函数的 `alloca` result 填值。GEP、
parameter、global 和普通 pointer value 继续走原来的间接地址路径。

## Implementation

`mir_to_x64_alloca_offset` 查询已规划的 address slot。load/store 根据结果选择：

- alloca address：`x64_mem_base("rbp", slot, width)`；
- 其他 pointer：先加载到 `rax`/`rcx`，再访问 `[reg]`。

1/2/4/8-byte load/store 均保留原有符号扩展、零扩展和窄 store 语义。没有改变 MIR、ABI、
GC root 规则或 stack frame layout。

## Results

相同 frozen v0 seed、相同宿主。基线来自内容寻址缓存；变体先验证 fixed point，再复用
收敛 compiler 运行同一 self-host workload 3 次。

| 指标 | 基线 | Direct alloca | 变化 |
|---|---:|---:|---:|
| wall median | 3174.657 ms | 3124.265 ms | -50.392 ms, -1.59% |
| X64 items | 179,451 | 164,581 | -14,870, -8.29% |
| `.text` bytes | 790,502 | 746,157 | -44,345 B, -5.61% |
| exe size | 829,440 | 784,896 | -44,544 B, -5.37% |

基线 wall samples 为 `3191.673 / 3174.657 / 3160.164 ms`；变体为
`3142.243 / 3124.265 / 3122.841 ms`。三个变体样本均快于三个基线样本。

代表性 fixed-point run 的 peak working set 从约 94 MiB 降到约 90 MiB；GC allocation
profile 也下降，因为更小的 self-host compiler 生成和处理更少 X64IR item。该内存值只作为
诊断，不替代三次 wall 结论。

## Correctness

新增 targeted test 同时验证：

- i64 alloca 使用直接 qword load/store；
- i8 alloca 使用直接 byte load/store；
- 不再为 alloca load/store 发射 `lea [rbp+slot]`；
- pointer parameter 仍保持间接 load。

完整 13 个模块、81 个 e2e、8 个 examples、GC stress/tiny 和 bootstrap fixed point 均通过。

## Conclusion

保留。它是局部、可证明正确的 address-mode selection，不需要 register allocation、alias
analysis 或新的 MIR pass，却稳定减少约 8.3% X64 items 和 5.4% 最终 executable。
