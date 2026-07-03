## 当前 Status

- ✅ Python reference compiler 主线健康：`python tests/run.py` 全绿（10/10 模块）
- ✅ `python test_examples_py.py` 全绿（62 passed）
- ✅ ADT 已从 Python reference compiler 移除
- ✅ `self-hosted` lexer 比较变为 opt-in（`--self-hosted`）
- ✅ ADT 文档残留已清除
-   `src/*.ep` 自举线含 ADT 残留 —— **战略放弃，暂不处理**

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

### 优先级 1：Helper 命名统一（Phase 2 of self-host-core.md）

| 旧名 | 新名 |
|------|------|
| `str_bool` | `bool_to_str` |
| `str_i64` | `i64_to_str` |
| `str_arr_i8` | `bytes_to_str` |
| `bytes_str` | `str_to_bytes` |
| `__epic_arr_i64_push` | `arr_i64_push` |
| `__epic_arr_ptr_push` | `arr_ptr_push` |
| `__epic_arr_qword_extend` | `qword_extend` |
| `__epic_arr_ptr_get` | `arr_ptr_get` |

### 优先级 2：MIR helper 迁移（从 x64 backend → MIR functions）

- `str_new`, `cstr`, `itoa`, `str_cat` 等仍在 `mir_lower._emit_*()` 中
- 逐步迁移到 `mir_runtime_helpers.py` 中的 `MirFunction`

### 优先级 3：str → u8[] 收敛（Phase 3 of self-host-core.md）

- 文档层先标记方向
- 逐步加 byte-oriented helper
- 最后移除 str helper public surface

## 已归档

- ADT 已从自举核心移除（`self-host-core.md` 定案）
- 自举测试 `test_*bootstrap*.py` 战略性放弃
- `bootstrap.py` bootstrap 链不再维护
- Python asm backend 归档在 tag `python-asm-archive-2026-07-02`
- 旧目录化 v0/v1/v2 代码保存在 tag `staged-bootstrap-archive-2026-06-30`
