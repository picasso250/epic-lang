## 当前 Status

- ✅ Python reference compiler 主线健康：`python tests/run.py` 全绿（10/10 模块）
- ✅ `python test_examples_py.py` 全绿（62 passed）
- ✅ ADT 已从 Python reference compiler 移除
- ✅ `self-hosted` lexer 比较变为 opt-in（`--self-hosted`）
- ✅ ADT 文档残留已清除
-   `src/*.ep` 自举线含 ADT 残留 —— **战略放弃，暂不处理**

## Commit A（已完成，文档定案）

**Define zero-copy str/bytes surface**

- [x] `docs/design.md` — 更新 str 类型描述、删除 public str builtin 列表、删除 `str + str`、zero-copy cast 语义、shared buffer 文档
- [x] `docs/self-host-core.md` — 更新决策模型、builtin 表、migration strategy（Phase 0）
- [x] `docs/builtin-inventory.md` — 标记 str_* 为已删除 public surface
- [x] `docs/impl.md` — 更新 lowering 表、string layout 说明
- [x] `todo.md` — 记录 commit 范围与后续 plan

## 后续 Commits

### Commit B：sema 删除 public str helper 调用

删除用户可调用：`str_get`、`str_slice`、`str_find`、`str_starts_with`、`str_trim`、`str_replace_char`、`str_cat`、`str_eq`。
保留 compiler internal lowering。
examples 中直接调用这些 builtin 的改为 `bytes(...)` + `u8[]` helper 或直接删除该 example。

### Commit C：删除 `str + str`

sema 拒绝 `str + str`。
MIR codegen 删除对应 lowering。
examples 中 concat 示例改为 `u8[]` + `extend` 写法。

### Commit D：确认 zero-copy `str(bytes)` / `bytes(str)`

如果当前实现已经 zero-copy，加正向测试锁定行为。
测试包括修改 `bytes(str)` 结果后原 `str` 可见。

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
