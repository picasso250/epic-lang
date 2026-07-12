# Garbage Collector

Epic 当前使用单线程、non-moving、conservative mark-sweep GC。它是 runtime
内部能力，不增加公开 `gc()`、统计 builtin 或 CLI 参数。

## Allocation

所有 managed allocation 必须经过 `__ep_alloc`。payload 直接由 Win32 process
heap 分配，地址在生命周期内不移动。runtime 长期维护紧凑的 payload 基址和请求大小
并行数组；正常分配路径只执行 HeapAlloc 和记录追加，不给每个对象增加 GC header。

冻结的 v0 seed 只读取 `runtime/mir/helpers.mir`，因此该文件保留 legacy
`__ep_alloc` 作为单代 bootstrap bridge。当前 compiler 先加载
`runtime/mir/gc.mir`，同名 GC allocator 优先，legacy 定义会被去重跳过。

## Collection

- 初始 payload 阈值为 8 MiB，对象数量阈值为 262,144；任一达到即触发
  collection。每轮 collection 后分别使用 `max(8 MiB, 2 * live_bytes)` 和
  `max(262,144, 2 * live_objects)`。
- collection 临时建立 payload-address hash table、mark byte table 和迭代 work stack，
  结束后立即释放。hash slot 保存 `object_index + 1`，因此 mark、work 和 sweep 共享
  同一对象索引；lookup 先以历史 `low_addr/high_addr` 快速拒绝。
- roots 包括活动线程栈和 `argv`。后端为非 `gep` 的 `ptr` 结果保留稳定栈槽，
  保证 allocation safepoint 上存在 managed object 基址。
- heap payload 按对齐的 8-byte word 保守扫描。natural struct layout 保证所有 managed
  reference 字段仍按 8 字节对齐；窄 scalar 字段和清零 padding 只可能造成 conservative
  false retention，不会隐藏活引用。
- sweep 直接按 object index 读取 mark，并原地压紧 payload/size 记录。对象大小来自长期
  side metadata，不调用 `HeapSize`。
- 每次 stop-the-world collection 完成后向 stderr 输出 `gc stw: <ms> ms`；计时不包含日志写出本身。
- 正常退出时，若进程至少发生过一次 collection，则向 stderr 输出一次累计 allocation profile，
  包含总请求数/字节数以及 `<=32B`、`<=64B` 两个累计桶。

当前不支持多线程 roots、moving/compaction、generation、finalizer、weak
reference 或精确 stack map。公开 WinAPI 调用是同步的；runtime 不承诺管理由
外部线程持有且未出现在 Epic roots 中的引用。
