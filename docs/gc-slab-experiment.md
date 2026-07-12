# GC small-object slab experiment

本文记录 `experiment/gc-small-object-slabs` 分支的第一版实验。目标是验证：将高频固定尺寸
对象移出 `HeapAlloc + gc_objects + gc_sizes + collection hash` 后，能否显著降低自举的
allocation 和 stop-the-world 成本。

## Implementation

分配按请求大小分流：

```text
0–8B   ->  8B slab class
9–16B  -> 16B slab class
17–24B -> 24B slab class
25–32B -> 32B slab class
>32B   -> existing process-heap large-object path
```

small arena 一次 reserve 1 GiB 连续虚拟地址空间，划分为 16,384 个 64 KiB slab，并在
首次使用 slab 时通过 `VirtualAlloc(MEM_COMMIT)` commit。reserve 不等于 1 GiB 物理内存
占用。每个 slab 固定属于一个 class，slot 覆盖整个 slab。

第一版将 metadata 放在始终可读的 side tables：

```text
page state / class
bump index
free-list head
allocated count
allocation byte map
mark byte map
```

allocation/mark map 当前每 slot 使用一 byte，优先保持 MIR 实现直接。dead slot 的前 8 bytes
保存下一个 free slot 的 `index + 1`；slot 分配或复用时按完整 class size 清零。

conservative candidate lookup 的检查顺序为：

```text
arena range -> committed slab index -> class -> exact slot base -> allocation byte
```

因此保留原有 exact-base 语义，拒绝 interior pointer、未 commit slab 和 dead slot。small
object 不进入 large-object arrays 或 collection hash。mark work stack 仍只有一份：large item
编码为 `object_index << 1`，small item 编码为 `(slab_index * 8192 + slot_index) << 1 | 1`。

sweep 遍历已 commit slab 的 slot map，清除 dead allocation byte、重建 free list，并重新选择
每个 class 的 active slab。当前不 decommit 空 slab，也不回收 slab 的 side maps。

## Results

基线是 `dev@710f6f1` 的收敛自举编译器：

```text
exe size:          828,416 B
wall time:         4.49 / 4.43 / 4.42s, median 4.43s
GC STW total:      about 1.9s over 9 collections
```

slab 分支的收敛编译器：

```text
exe size:          836,096 B
wall time:         3.326 / 3.331 / 3.367s, median 3.331s
GC STW total:      858 / 843 / 828ms, median 843ms
peak working set:  97.02–97.16 MiB in final fixed-point runs
```

对比结果：

```text
wall time:  -1.099s / -24.8%
exe size:   +7,680 B / +0.93%
GC STW:     approximately -56%
```

slab 版本的 runtime MIR 增量约 550 行，另增加一个 encoded `VirtualAlloc` extern。该 workload
也包含变大的 runtime MIR，因此 slab 分支实际处理的 managed allocation 数略高于原基线；
三次直接测量均为 3,095,425 次、118,159,605 请求字节。

验证结果：bootstrap fixed point、全部 13 个模块、79 个 e2e、8 个 examples，以及 GC stress
和 tiny-memory tests 全部通过。

## Interpretation and remaining work

实验已经验证 fixed-size small-object path 是当前 GC 性能的高收益方向。wall time 改善明显
超过 basic-block register cache 和 block-local linear scan 两个寄存器实验的噪声水平。

若将实验升级为正式实现，优先处理：

1. 将 allocation/mark map 压为 bitmap，降低每 slab side metadata 和 sweep 流量。
2. 只扫描 bump 范围或维护更紧凑的 occupied range，避免遍历从未使用的尾部 slot。
3. 回收完全空闲 slab，必要时 decommit，并让 class ownership 可复用。
4. 在 allocator 决策完成后移除详细 allocation-profile 热路径计数。
5. 增加 small slab committed/live/empty 统计，量化 slab 利用率和内部碎片。
