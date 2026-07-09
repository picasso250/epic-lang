## 下一步（远期）

### 优先级 1：Helper 命名统一（已收敛，旧 Phase 2 计划废弃）

结论：不再把 helper 改成裸语义名 `bool_to_str` / `i64_to_str` / `arr_ptr_push`。
当前采用内部 ABI 命名：

| 语义 | 当前内部 helper |
|------|----------------|
| bool → str | `__ep_str_from_bool` |
| i64/u64 → str | migrated to `runtime/str.ep` |
| u8[] → str | `__ep_str_from_slice_u8` |
| str → u8[] | `__ep_slice_u8_from_str` |
| i64[] push | `__ep_slice_i64_push` |
| ptr[] push | `__ep_slice_ptr_push` |
| ptr[] get | `__ep_slice_ptr_get` |

旧计划中的 `str_bool` / `str_i64` / `str_arr_i8` / `bytes_str` / `__epic_arr_*` 已从实现层移除；旧目标名 `bool_to_str` / `i64_to_str` / `arr_ptr_*` 不再采用。

### 优先级 2：MIR helper 迁移（部分完成，剩余为底层 runtime glue）

语言层 helper 大多已迁移到 `bootstrap/mir_runtime_helpers.py`，并通过 `MirFunction` 注入：

- str/bytes：`__ep_str_from_bool`、`__ep_str_from_slice_u8`、`__ep_slice_u8_from_str`、`__ep_str_eq`、`__ep_str_cat`、`__ep_str_slice`、`__ep_str_get`、`__ep_str_find`
- slice：`__ep_slice_u8_*`、`__ep_slice_i64_*`、`__ep_slice_ptr_*`
- map：`__ep_map_str_i64_*`、`__ep_map_str_bool_*`、`__ep_map_str_str_*`

仍由 `bootstrap/x64_runtime.py` 直接发 x64 的是底层 runtime/OS glue；`bootstrap/mir_to_x64.py` 只负责 MIR -> X64IR lowering 并追加 runtime 片段：

- allocation / process args：`__epx_alloc`、`__epx_argv_init`
- OS-facing helpers：`__ep_*` semantic wrapper tail-jump 到对应 `__epx_*` primitive（如 cstr/read/write/system）
- printing / traps：`__ep_print_*` wrapper、`__epx_print_*` primitive、`__epx_slice_oob`、`__epx_null_deref`（`__epx_putc` 已删除）
结论：numeric formatting helper 已迁移到 `runtime/str.ep`；不要标成完成，下一步应考虑 `__ep_cstr` / file / argv / print 这类更贴近平台 ABI 的 helper。

### 优先级 3：str → u8[] 收敛（公共表面已完成，self-hosted 源码残留待清）

已完成：

- 文档层已定案 byte-buffer-first text model
- public str helper surface 已收缩：`str_new` / `itoa` / `str_find` / `str_starts_with` / `str_replace_char` / `str_trim` 不再作为公开内置使用
- `read_file` / `write_file` 已以 `u8[]` 为数据载体
- `str(u8[])` / `bytes(str)` 已是 zero-copy identity cast，并有 `examples/v5_zero_copy_str_bytes.ep` 覆盖共享 buffer 行为
- `extend` 已收敛为仅支持 `u8[]`

仍未完成：

- `src/codegen_support.ep` / `src/codegen.ep` 已删除（旧 NASM codegen 线）
- `src/link.ep` 已清理旧 helper 调用，并新增 `tests/link/run.py` 覆盖 Epic linker 路径
- `src/parser.ep` reserved-name list 中的 `str_new` 残留已清理

结论：Phase 3 的语言/文档/测试表面基本完成；不能标成全完成，因为 self-hosted compiler 源码迁移还没清完。
