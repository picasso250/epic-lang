# GC allocation profile

本文记录自举编译器在引入自动 GC 后的 managed allocation 请求分布，为 small-object
allocator 和 GC 优化提供基线。数据来自提交 `443d05c` 加入的 allocation profile；它是
一次代表性的收敛自举结果，不是语言 ABI 或长期性能承诺。

## Workload

使用已经收敛的 Epic 编译器再次编译当前 Epic 编译器。该次运行共请求
`2,995,296` 次 managed allocation，逻辑请求总量为 `113,375,492 B`。

| 请求区间 | 分配次数 | 次数占比 | 请求字节 | 字节占比 |
|---|---:|---:|---:|---:|
| `<=8B` | 625,468 | 20.88% | 4,006,770 B | 3.53% |
| `9–16B` | 1,176,454 | 39.28% | 18,823,264 B | 16.60% |
| `17–24B` | 690,360 | 23.05% | 16,568,640 B | 14.61% |
| `25–32B` | 406,355 | 13.57% | 13,003,360 B | 11.47% |
| `33–64B` | 69,490 | 2.32% | 3,956,368 B | 3.49% |
| `>64B` | 27,169 | 0.91% | 57,017,090 B | 50.29% |
| 总计 | 2,995,296 | 100% | 113,375,492 B | 100% |

累计次数占比：

```text
<=16B: 60.16%
<=24B: 83.21%
<=32B: 96.78%
<=64B: 99.09%
```

## Fixed-size shapes

精确尺寸计数为：

```text
exact 16B = 1,176,454
exact 24B =   690,360
exact 32B =   406,355
```

它们分别等于 `9–16B`、`17–24B`、`25–32B` 三个区间的全部请求数。因此这三个
区间没有 9B、12B、20B、28B 等中间尺寸；16B、24B、32B 请求由固定对象布局主导，
不是连续尺寸分布。

尺寸本身不能唯一确定对象类型。16B 可以是 `{tag, payload}`，也可以是普通两字段
struct；24B 可以是 `{data, len, cap}`，也可以是其他三 word 布局。若需要按对象类型
归因，应另加 allocation-site 或 type profile，不能从尺寸计数反推唯一来源。

## Allocator implications

单一 32B small-object class 会覆盖 `2,898,637` 次 `<=32B` 请求，但需要约
`88.46 MiB` slot payload；这些请求的实际逻辑大小约为 `49.97 MiB`，class rounding
会浪费约 `38.5 MiB`。

当前数据更支持 word-sized classes：

```text
size <=  8 ->  8B class
size <= 16 -> 16B class
size <= 24 -> 24B class
size <= 32 -> 32B class
size >  32 -> large allocation
```

16B、24B、32B class 在该 workload 下没有 rounding waste。`<=8B` 桶的内部形状
仍未知，因此四级 size class 是候选设计方向，不是已经确认的实现合约。

若 small-object allocator 使用 Windows reserved virtual address arena，应区分系统页
大小和 allocation granularity，并通过 `GetSystemInfo` 读取两者。`VirtualAlloc` reserve
地址按 allocation granularity 对齐，已 reserve 区域可以分段 commit，首次 commit 的
内存保证为零。详见 Microsoft Learn 的
[`VirtualAlloc`](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualalloc)
和 [`SYSTEM_INFO`](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/ns-sysinfoapi-system_info)。

## Remaining measurement

下一次有价值的 size profile 是拆分唯一仍不明确的 `<=8B` 桶：

```text
0B
1B
2–4B
5–8B
exact 8B
```

allocation profile 属于诊断设施。完成 allocator 决策后不应让详细累计桶永久留在
正常分配热路径；后续基准也应同时报告总运行时间、GC STW 时间和峰值内存。
