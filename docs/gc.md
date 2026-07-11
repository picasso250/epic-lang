# Garbage Collector

Epic 当前使用单线程、non-moving、conservative mark-sweep GC。它是 runtime
内部能力，不增加公开 `gc()`、统计 builtin 或 CLI 参数。

## Allocation

所有 managed allocation 必须经过 `__ep_alloc`。payload 直接由 Win32 process
heap 分配，地址在生命周期内不移动。runtime 维护一个紧凑的 payload 指针数组；
正常分配路径只执行 HeapAlloc 和数组追加，不给每个对象增加 GC header。

冻结的 v0 seed 只读取 `runtime/mir/helpers.mir`，因此该文件保留 legacy
`__ep_alloc` 作为单代 bootstrap bridge。当前 compiler 先加载
`runtime/mir/gc.mir`，同名 GC allocator 优先，legacy 定义会被去重跳过。

## Collection

- 初始阈值为 256 MiB；每轮 collection 后使用
  `max(256 MiB, 2 * live_bytes)`。
- collection 临时建立 payload-address hash table、mark byte table 和迭代
  work stack，结束后立即释放。
- roots 包括活动线程栈和 `argv`。后端为非 `gep` 的 `ptr` 结果保留稳定栈槽，
  保证 allocation safepoint 上存在 managed object 基址。
- heap payload 按对齐的 8-byte word 保守扫描。随机整数可能造成 false
  retention，但不能造成活对象误回收。
- sweep 释放未标记 payload，并原地压紧 tracked-object array。

当前不支持多线程 roots、moving/compaction、generation、finalizer、weak
reference 或精确 stack map。公开 WinAPI 调用是同步的；runtime 不承诺管理由
外部线程持有且未出现在 Epic roots 中的引用。
