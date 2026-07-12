# GC small-object bitmap experiment

本文记录 `experiment/gc-small-object-bitmaps` 分支的实验。它基于
`experiment/gc-small-object-slabs@35f3e18`，只将每个 slab 的 allocation/mark metadata
从每 slot 一 byte 压缩为每 slot 一 bit。

## Representation

每个 slot index 的 metadata 定位为：

```text
byte_index = slot_index >> 3
bit_index  = slot_index & 7
mask       = 1 << bit_index
```

allocation、candidate lookup、mark 和 sweep 都直接使用这个表示。bitmap 大小为
`ceil(slot_capacity / 8)` bytes。两个 map 的理论占用如下：

| Class | Slots/slab | Byte maps | Bitmaps | 每 slab 节省 |
|---|---:|---:|---:|---:|
| 8B | 8,192 | 16,384 B | 2,048 B | 14,336 B |
| 16B | 4,096 | 8,192 B | 1,024 B | 7,168 B |
| 24B | 2,730 | 5,460 B | 684 B | 4,776 B |
| 32B | 2,048 | 4,096 B | 512 B | 3,584 B |

## Strength reduction

初版 MIR 使用 `udiv 8` 和 `urem 8` 计算 byte/bit index。当前后端不会自动将常数除法
strength-reduce；这些操作会进入真正的 x64 division path。该版本三次 wall-time 中位数为
`3.427s`，比 byte-map 的 `3.331s` 慢约 `2.9%`。

最终版本明确使用：

```text
udiv 8 -> shr 3
urem 8 -> and 7
```

这消除了可避免的除法成本。下述结果均来自最终版本。

## Results

同一自举 workload 的三次稳定测量：

| 指标 | Byte maps | Bitmaps | 变化 |
|---|---:|---:|---:|
| Wall time | 3.326 / 3.331 / 3.367s | 3.397 / 3.334 / 3.331s | median 3.331 -> 3.334s, +0.09% |
| GC STW total | 858 / 843 / 828ms | 891 / 859 / 842ms | median 843 -> 859ms, +1.9% |
| Compiler exe | 836,096 B | 836,608 B | +512 B, +0.06% |
| Fixed-point peak working set | 97.02–97.16 MiB | 92.62–92.75 MiB | about -4.4 MiB, -4.5% |

GC 专项测试的 peak working set：

| Test | Byte maps | Bitmaps | 变化 |
|---|---:|---:|---:|
| stress | 67.0 MiB | 61.7 MiB | -5.3 MiB, -7.9% |
| tiny | 78.0 MiB | 65.0 MiB | -13.0 MiB, -16.7% |

bitmap 分支的 runtime MIR 相对 byte-map 增加 21 条收敛后 MIR instruction，managed
allocation workload 也因此略有增加。最终正确性验证包括 bootstrap fixed point、全部 13 个
模块、79 个 e2e、8 个 examples，以及 GC stress/tiny tests。

## Conclusion

bitmap 没有可测量的 wall-time 收益；优化后 `+0.09%` 的差异属于噪声量级。STW 有很小的
回退信号，但不足以抵消明确的内存收益。对于 tiny-object 密集 workload，peak working set
下降达到 16.7%。

因此 bitmap 值得保留，主要理由是 metadata 内存和 cache footprint，而非当前 wall time。
实验也确认：在当前简单后端下，热路径中的二次幂常数除法应直接表达为 shift/mask。
