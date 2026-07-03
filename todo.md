## 当前 Status

- ✅ Python reference compiler 主线健康：`python tests/run.py` 全绿（10/10 模块）
- ✅ `python test_examples_py.py` 全绿（62 passed）
- ✅ ADT 已从 Python reference compiler 移除
- ✅ `self-hosted` lexer 比较变为 opt-in（`--self-hosted`）
- ✅ ADT 文档残留已清除
-   `src/*.ep` 自举线含 ADT 残留 —— **战略放弃，暂不处理**

## 下一步

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
