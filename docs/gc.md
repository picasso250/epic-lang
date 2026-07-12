# Garbage Collector

Epic 当前使用单线程、non-moving、conservative mark-sweep GC。它是 runtime
内部能力，不增加公开 `gc()`、统计 builtin 或 CLI 参数。

## Allocation

所有 managed allocation 必须经过 `__ep_alloc`。`<=32B` 请求进入 8/16/24/32B
四级 small-object slab；`>32B` payload 由 Win32 process heap 分配。两条路径地址均在
生命周期内不移动，也都不给每个对象增加 GC header。

small allocator reserve 1 GiB 连续虚拟地址 arena，并将它划分为 64 KiB slab，使用
`VirtualAlloc` 按需 commit。slab class、bump/free-list 状态和 allocation/mark bitmap
保存在常驻 side table；slot 每次分配和复用时按 class size 清零。large allocator 继续
长期维护紧凑的 payload 基址和请求大小并行数组。

冻结的 v0 seed 只读取 `runtime/mir/helpers.mir`，因此该文件保留 legacy
`__ep_alloc` 作为单代 bootstrap bridge。当前 compiler 先加载
`runtime/mir/gc.mir`，同名 GC allocator 优先，legacy 定义会被去重跳过。

## Collection

- 初始 heap-pressure 阈值为 8 MiB；达到即触发 collection。每轮 collection 后使用
  `max(8 MiB, 2 * live_bytes)`。small object 按实际 slab class 的 8/16/24/32B slot
  大小计入 `live_bytes`，因此该阈值同时反映 small arena 的实际 committed payload
  压力；不再维护独立对象数量阈值。
- collection 只为 large objects 临时建立 payload-address hash table 和 mark byte table；
  small candidate 通过 arena range、slab class、slot alignment 和 allocation bitmap
  直接识别。两条路径共用 tagged integer work stack，结束后释放临时 metadata。
- roots 包括活动线程栈和 `argv`。后端为非 `gep` 的 `ptr` 结果保留稳定栈槽，
  保证 allocation safepoint 上存在 managed object 基址。
- heap payload 按对齐的 8-byte word 保守扫描。natural struct layout 保证所有 managed
  reference 字段仍按 8 字节对齐；窄 scalar 字段和清零 padding 只可能造成 conservative
  false retention，不会隐藏活引用。
- large sweep 直接按 object index 读取 mark，并原地压紧 payload/size 记录。small sweep
  清理 allocation/mark bitmap、重建 dead-slot free list，并选择各 class 的 active slab。
  对象大小均来自 side metadata，不调用 `HeapSize`。
- 每次 stop-the-world collection 完成后向 stderr 输出 `gc stw: <ms> ms`；计时不包含日志写出本身。
- 正常退出时，若进程至少发生过一次 collection，则向 stderr 输出一次累计 allocation profile，
  包含总请求数/字节数、`<=8/16/24/32/64B` 累计桶，以及精确 `16/24/32B` 计数。

当前自举 workload 的 allocation size 分布、固定尺寸结论和 allocator 启示记录在
[`gc-allocation-profile.md`](gc-allocation-profile.md)。
slab 实验的具体实现边界和性能结果记录在
[`gc-slab-experiment.md`](gc-slab-experiment.md)。
byte-map 到 bitmap 的后续实验记录在
[`gc-bitmap-experiment.md`](gc-bitmap-experiment.md)。
对象数量触发器在 slab allocator 上的删除实验记录在
[`gc-object-threshold-experiment.md`](gc-object-threshold-experiment.md)。

当前不支持多线程 roots、moving/compaction、generation、finalizer、weak
reference 或精确 stack map。公开 WinAPI 调用是同步的；runtime 不承诺管理由
外部线程持有且未出现在 Epic roots 中的引用。
