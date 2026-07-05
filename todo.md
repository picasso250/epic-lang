## 当前 Status

- ✅ Python reference compiler 主线健康：`python tests/run.py` 全绿（10/10 模块）
- ✅ `python test_examples_py.py` 全绿（64 passed）
- ✅ ADT 已从 Python reference compiler 移除
- ✅ `self-hosted` lexer 比较变为 opt-in（`--self-hosted`）
- ✅ ADT 文档残留已清除

## ✅ Str Surface Contraction（已全部完成，含 review fix）

### Commit A：Define zero-copy str/bytes surface（文档定案）
- [x] 文档定案（design.md, self-host-core.md, builtin-inventory.md, impl.md）
- [x] 确认 str 只读表面语义 + shared buffer 警告

- [x] `docs/design.md` — 更新 str 类型描述、删除 public str builtin 列表、删除 `str + str`、zero-copy cast 语义、shared buffer 文档
- [x] `docs/self-host-core.md` — 更新决策模型、builtin 表、migration strategy（Phase 0）
- [x] `docs/builtin-inventory.md` — 标记 str_* 为已删除 public surface
- [x] `docs/impl.md` — 更新 lowering 表、string layout 说明
- [x] `todo.md` — 记录 commit 范围与后续 plan

### Commit B：sema 删除 public str helper 调用

- [x] `bootstrap/sema.py` — 删除 str_slice/str_replace_char/str_starts_with/str_find/str_trim handler
- [x] `bootstrap/mir_codegen.py` — 删除对应 codegen dispatch
- [x] `src/codegen.ep` — 删除 type checking + emit blocks
- [x] `src/parser.ep` — 删除 reserved name checks
- [x] `tests/mir/test_mir.py` — 删除 4 个 test case
- [x] `examples/v1_str_helpers.ep` — 删除
- [x] `examples/m31_str_tools.ep` — 重写为 u8[] byte ops
- [x] `examples/v4_str_eq.ep` — str_slice → s[start:end]

### Commit C：删除 `str + str`

- [x] `bootstrap/sema.py` — str + str 和 str += str → fail 含错误信息
- [x] `bootstrap/mir_codegen.py` — 删除 str_cat lowering
- [x] `src/codegen.ep` — 删除 binary `+` 和 `+=` 的 codegen
- [x] `tests/mir/test_mir.py` — 删除 concat test case
- [x] `examples/m30_str_cat.ep` — 重写为 u8[] + extend
- [x] `examples/v4_str_eq.ep` — 删除 concat 测试片段
- [x] `examples/v4_itoa_stable.ep` — 重写为 u8[] + extend + push
- [x] `examples/v1_compound_assign.ep` — s += "bc" → let s = "abc"

### Commit D：确认 zero-copy `str(bytes)` / `bytes(str)`

- [x] 确认 `str_arr_i8` 是 identity（纯指针重解释）
- [x] 确认 `bytes_str` 分配新 descriptor 但共享 data 指针
- [x] `examples/v5_zero_copy_str_bytes.ep` — 正向测试：修改 bytes(str) 后原 str 可见

---

## 下一步（远期）

### 优先级 1：Helper 命名统一（已收敛，旧 Phase 2 计划废弃）

结论：不再把 helper 改成裸语义名 `bool_to_str` / `i64_to_str` / `arr_ptr_push`。
当前采用内部 ABI 命名：

| 语义 | 当前内部 helper |
|------|----------------|
| bool → str | `__ep_str_from_bool` |
| i64 → str | `__ep_str_from_i64` |
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

仍由 `bootstrap/mir_lower.py` 直接发 x64 的是底层 runtime/OS glue：

- allocation / process args：`__epx_alloc`、`__epx_argv_init`
- OS-facing helpers：`__ep_cstr`、`__ep_read_file`、`__ep_write_file`、`__ep_system_cmd`
- printing / traps：`__ep_print_str`、`__ep_print_newline`、`__epx_putc`、`__epx_slice_oob`、`__epx_null_deref`
- numeric formatting：`__ep_str_from_i64`

结论：不要标成完成；下一步应优先迁移 `__ep_str_from_i64`，再考虑 `__ep_cstr` / file / argv / print 这类更贴近平台 ABI 的 helper。

### 优先级 3：str → u8[] 收敛（公共表面已完成，self-hosted 源码残留待清）

已完成：

- 文档层已定案 byte-buffer-first text model
- public str helper surface 已收缩：`str_new` / `itoa` / `str_find` / `str_starts_with` / `str_replace_char` / `str_trim` 不再作为公开内置使用
- `read_file` / `write_file` 已以 `u8[]` 为数据载体
- `str(u8[])` / `bytes(str)` 已是 zero-copy identity cast，并有 `examples/v5_zero_copy_str_bytes.ep` 覆盖共享 buffer 行为
- `extend` 已收敛为仅支持 `u8[]`

仍未完成：

- `src/codegen_support.ep` / `src/codegen.ep` 已删除（旧 NASM codegen 线）
- `src/link.ep` 已清理旧 helper 调用，并新增 `tests/link_ep/run.py` 覆盖 Epic linker 路径
- 保留的 `src/*.ep` 工具源码仍有旧 helper 残留：`src/parser.ep` 的 `str_new` reserved name
- 下一步应清理 `src/parser.ep` reserved-name list 中的 `str_new` 残留

结论：Phase 3 的语言/文档/测试表面基本完成；不能标成全完成，因为 self-hosted compiler 源码迁移还没清完。
