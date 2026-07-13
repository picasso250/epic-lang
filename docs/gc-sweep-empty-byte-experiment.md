# GC small-slab empty-byte sweep experiment

## Question

small-object sweep 已经为当前 slot 加载 allocation bitmap byte。实验在逐 bit 测试前先检查
整个 byte 是否为零；若为空，则一次前进 `8 - (slot_index & 7)` 个 slot 到下一个 byte
边界，否则保持原有逐-slot mark/sweep 路径。

该 fast path 不增加 metadata load。跳过量也允许控制流从 byte 中间进入，不会越过下一
byte 中可能已分配的 slot。代价是每个访问到的 allocation byte 多一次条件分支；收益取决于
sweep 时空 byte 是否足够多。

## Validation

- bootstrap fixed point reached；
- 全部 13 个模块、88 个 e2e 和 9 个 examples 通过；
- GC stress 和 tiny-memory tests 通过。

## Three-sample benchmark

基线为 `dev@f1b7e6c`。两组使用相同 seed、compiler source、参数和输出位置；variant
只改变 embedded `runtime/mir/gc.mir`。结果均来自收敛编译器对相同 self-host workload
的三次等价测量。

| Metric | Baseline | Empty-byte skip | Delta |
|---|---:|---:|---:|
| wall samples | 1608.754 / 1612.875 / 1593.561 ms | 1677.198 / 1665.526 / 1678.086 ms | |
| median wall | 1608.754 ms | 1677.198 ms | +68.444 ms (+4.25%) |
| median internal | 1594 ms | 1656 ms | +62 ms (+3.89%) |
| GC STW totals | 532 / 530 / 547 ms | 531 / 563 / 562 ms | |
| median GC STW total | 532 ms | 562 ms | +30 ms (+5.64%) |
| X64 items | 149,400 | 149,415 | +15 |
| `.text` | 681,184 B | 681,252 B | +68 B |
| `.data` | 90,243 B | 90,475 B | +232 B |
| executable | 774,144 B | 774,656 B | +512 B |

代表性 fixed-point peak working set 为 baseline 87.80 MiB、variant 87.93 MiB，没有内存
收益。

## Conclusion

不保留。当前 self-host workload 的 allocation bitmap 足够密，空 byte fast path 节省的
slot iterations 无法抵消非空路径上的额外条件分支。wall time 和 GC STW median 都出现
清晰回退，按三样本规则不继续增加样本。

若未来 workload 的 slab occupancy 明显降低，应先用临时诊断统计 sweep 访问的 zero/nonzero
allocation bytes，再根据证据重新评估。
