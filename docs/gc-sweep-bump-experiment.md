# GC small-slab bump-bounded sweep experiment

## Question

small-object sweep 当前遍历每个已 commit slab 的完整 slot capacity。实验只将遍历上限
改为该页的 monotonic bump index，以跳过从未分配过的尾部 slot；capacity 仍用于 sweep
后的 active-page 选择。

这个变换不改变对象布局、allocation bitmap、free list 或 root 规则。所有曾经分配过的
slot 都位于 `[0, bump)`，复用的 slot 也来自这个范围，因此尾部不可能包含 live object。

## Validation

- bootstrap fixed point reached；
- 全部 13 个模块、88 个 e2e 和 9 个 examples 通过；
- GC stress 和 tiny-memory tests 通过。

## Three-sample benchmark

基线为 `dev@f1b7e6c`。两组使用相同 seed、compiler source、参数和输出位置；variant
只改变 embedded `runtime/mir/gc.mir`。结果均来自收敛编译器对相同 self-host workload
的三次等价测量。

| Metric | Baseline | Sweep to bump | Delta |
|---|---:|---:|---:|
| wall samples | 1608.754 / 1612.875 / 1593.561 ms | 1658.340 / 1670.464 / 1645.006 ms | |
| median wall | 1608.754 ms | 1658.340 ms | +49.586 ms (+3.08%) |
| median internal | 1594 ms | 1641 ms | +47 ms (+2.95%) |
| GC STW totals | 532 / 530 / 547 ms | 579 / 549 / 515 ms | |
| median GC STW total | 532 ms | 549 ms | +17 ms (+3.20%) |
| X64 items | 149,400 | 149,414 | +14 |
| `.text` | 681,184 B | 681,259 B | +75 B |
| `.data` | 90,243 B | 90,352 B | +109 B |
| executable | 774,144 B | 774,656 B | +512 B |

代表性 fixed-point peak working set 为 baseline 87.80 MiB、variant 87.79 MiB，没有内存
变化信号。

## Conclusion

不保留。当前 self-host workload 中，跳过从未使用的 slab 尾部没有带来可测量收益，新增
的 page-bump metadata loads 和较大的 runtime/compiler image 反而伴随稳定的 wall-time
回退。GC STW 样本也没有改善信号，因此没有理由用更多样本追逐噪声。

若以后 workload 显示大量部分使用的 slab，应先用临时统计量化每页 `bump / capacity`，
再重新评估；不要在缺少该证据时重复这一改动。
