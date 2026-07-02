# MIR Runtime Helper Plan

## Goal

把 runtime helper 从「x64 lower 阶段无条件注入」逐步迁移到「MIR 层按需注入」。

## Why

当前链路 `mir_codegen.py` → `mir_lower.py` 的做法是：

1. `mir_codegen.emit_program()` **无条件注册全部 extern**（~40 个），不管用户代码实际用到了几个。
2. `mir_lower.lower()` → `append_runtime_helpers()` → `_emit_runtime_helpers()` **无条件生成全部 x64 标签、全部 x64 helper 函数体**，不管用户代码是否调用。

这意味着：
- **编译所有程序都携带了全套 helper**。`print("hello")` 也会生成 `__epic_arr_ptr_push`、`map_repr`、`str_find` 等无关代码。
- **MIR 层对 x64 层有隐式依赖**：MIR 只是记录了 extern 声明，真正有没有实现要到 x64 lower 阶段才确定。
- **未来自举编译器要通过自身编译器 .ep 源码生成这些 helper**，但目前全部在 Python x64 汇编器里手写，迁移路径不清晰。

## Non-goals

本计划**不**覆盖：

- `bytes_to_str` copy 语义修正（有据可查的疑似 bug，但不在本阶段修）
- `u64_to_str` 缺位（`str_i64` 只支持 i64，不支持 u64；后续补）
- 删除 `public builtin`（`exit`、`system`、`read_file` 等保持不动）
- `__epic_alloc` 由 x64 primitive 迁移为 MIR helper（它依赖 `_heap` 全局变量，是 platform primitive；保持不动）
- 引入 `.ep` runtime 源码（中期用 Python builder 注入 MIR helper，不急着自举）

## Layering

```
┌──────────────────────────────────────┐
│  1. Public builtins                  │
│     println, print, exit, system,    │
│     str, len, push, read_file, …     │
│     Known to the Epic language spec. │
│     Resolved by sema, emitted by     │
│     mir_codegen as MIR call.         │
├──────────────────────────────────────┤
│  2. MIR helpers                      │
│     str_i64, str_bool, str_arr_i8,   │
│     str_cat, str_eq, str_slice, …    │
│     arr_i8_push, arr_i64_get, …      │
│     map_new, map_get, …              │
│     print_str, print_newline, …      │
│     Not directly callable from Epic. │
│     Called by mir_codegen when       │
│     lowering a builtin call.         │
│     Injected as MIR functions.       │
├──────────────────────────────────────┤
│  3. x64/platform primitives          │
│     __epic_alloc (HeapAlloc wrapper) │
│     __epic_arr_qword_new (core arr)  │
│     _heap, _argv, _str_i64_buf, …    │
│     Less than 10 items.              │
│     Still emitted in x64 lower.      │
└──────────────────────────────────────┘
```

### Key boundary

- **MIR helper** = x64 function that exists only because some MIR `call` references it. Future self-hosted compiler would emit these as MIR functions (lowered to x64 by generic lowering).
- **x64 primitive** = x64 function/data that requires Windows API knowledge or x64-specific setup. These stay in the x64 backend and are **not** MIR externs (they don't appear in the MIR program; they're injected only in x64 lower).

Currently both categories are lumped together in `_emit_runtime_helpers()`.

## Current State

### 1. `mir_codegen.py` unconditionally registers all externs

File: `bootstrap/mir_codegen.py` lines 85–124

```python
self.program.externs.append(MirExtern("str_i64", MirSignature([I64], ptr_str())))
self.program.externs.append(MirExtern("str_new", MirSignature([I64, I64], ptr_str())))
# … 40 externs total, ALL unconditionally registered
```

This happens in `emit_program()`, before any function is lowered. No tracking of which externs are actually referenced.

### 2. `mir_lower.py` unconditionally lowers all helpers

File: `bootstrap/mir_lower.py` line 36

```python
append_runtime_helpers(self)   # called unconditionally
```

File: `x64_runtime.py` lines 37–38

```python
def append_runtime_helpers(lower, policy=FULL_RUNTIME):
    if policy != FULL_RUNTIME:
        raise RuntimeError(...)   # no partial support!
```

File: `bootstrap/mir_lower.py` lines 298–340 (`_emit_runtime_helpers`)

```python
def _emit_runtime_helpers(self):
    self._emit_epic_alloc()
    self._emit_epic_arr_qword_new()
    self._emit_epic_arr_qword_push("__epic_arr_i64_push")
    self._emit_epic_arr_qword_push("__epic_arr_ptr_push")
    self._emit_epic_arr_qword_extend()
    self._emit_epic_arr_qword_get("__epic_arr_i64_get", "array_oob")
    self._emit_epic_arr_qword_get("__epic_arr_ptr_get", "array_oob")
    self._emit_bytes_str()
    self._emit_str_arr_i8()
    # … 35+ helpers, ALL unconditionally emitted
```

### 3. `__epic_alloc` already works as MIR-callable extern

It's registered in `mir_codegen.py` line 119 and emitted in `mir_lower.py` line 350.

```python
self.program.externs.append(MirExtern("__epic_alloc", MirSignature([I64], ptr())))
```

### 4. Helper naming still has historical artifacts

- `str_i64` — converts i64 to string (name suggests it's about string→i64, but it's actually i64→str)
- `str_arr_i8` — converts `u8[]` to string (string→array→string naming tangle)
- `bytes_str` — converts string to bytes (reversed naming: it's actually `str→bytes` but legacy name)
- `__epic_cstr` — string to C-style null-terminated (naming ok but mixed underscore styles)
- `__epic_arr_i64_push` — push i64 to array (ok but belongs in MIR helpers, not x64 primitives)
- Many `__epic_` prefixed names that aren't true x64 primitives

### 5. `x64_runtime.py` has explicit OWNERSHIP split

`append_runtime_helpers()` already calls `_emit_runtime_start()` (platform primitive) then delegates to `lower._emit_runtime_helpers()` (the rest).

This is the first split — the next step is to further split `_emit_runtime_helpers()` into MIR helpers vs x64 primitives.

## Target State

### MIR layer

- `mir_codegen.py` tracks `required_helpers: set[str]` during function lowering.
- Only referenced helpers are registered as externs in the MIR program.
- After all functions are lowered, required MIR helpers are injected as MIR functions (with MIR instruction bodies, not as externs to x64 labels).
- `mir_lower.py` sees only the externs actually used + the injected MIR helper function definitions.

### x64 layer

- `_emit_runtime_helpers()` splits into:
  - `_emit_x64_primitives()` — only `__epic_alloc`, `__epic_arr_qword_new`, `_heap`, `_argv`, `array_oob`, data globals.
  - Everything else becomes a **MIR helper** and is generated by a Python builder in `mir_runtime_helpers.py`.

### Separation of concerns

```
mir_codegen.py                         mir_runtime_helpers.py
  │                                        │
  │  1. Lower function → track req         │
  │  2. required_helpers → resolve         │
  │  3. For each req, inject MIR fn ──────►│  builder.emit_<helper>() returns
  │                                        │  MIR function definition
  ▼                                        │
mir_lower.py                               │
  │                                        │
  │  4. Lower MIR (externs + helpers)      │
  │  5. Append x64 primitives only         │
  ▼                                        │
x64_runtime.py                             │
  │                                        │
  │  emit_runtime_data()                   │
  │  __epic_alloc, __epic_arr_qword_new    │
  │  _heap, _argv, data globals            │
  ▼                                        │
x64.py                                     │
```

### Naming convention

After renaming, MIR helpers follow the pattern:

| Category | Pattern | Example | Currently named |
|----------|---------|---------|-----------------|
| String | `str_<op>` | `str_i64`, `str_bool`, `str_cat` | `str_i64` ✓, `str_bool` ✓, `str_cat` ✓ |
| u8[] | `arr_i8_<op>` | `arr_i8_get`, `arr_i8_push` | `arr_i8_get` ✓, `arr_i8_push` ✓ |
| i64[] | `arr_i64_<op>` | `arr_i64_get`, `arr_i64_set` | `arr_i64_get` ✓, `arr_i64_set` ✓ |
| ptr[] | `arr_ptr_<op>` | `arr_ptr_push` | `__epic_arr_ptr_push` → `arr_ptr_push` |
| map | `map_<op>` | `map_new`, `map_get` | `map_new` ✓, `map_get` ✓ |
| I/O | `print_<op>` | `print_str`, `print_newline` | `print_str` ✓, `print_newline` ✓ |
| Array core | `qword_<op>` | `qword_new`, `qword_push` | `__epic_arr_qword_new` → `qword_new` |

True x64 primitives keep the `__epic_` prefix: `__epic_alloc`.

## Migration Plan

### Phase 1: Docs and inventory cleanup

This commit.

- [x] Write `docs/mir-runtime-helper-plan.md`

Also need:
- [ ] Update `docs/builtin-inventory.md` to note the MIR helper layer (not just public builtins)
- [ ] Add a comment block in `mir_codegen.py` and `mir_lower.py` pointing to this plan

### Phase 2: Helper naming rename only

Rename MIR extern declarations and x64 labels **without changing any logic**.

Files affected:
- `bootstrap/mir_codegen.py` — rename extern names in `emit_program()`
- `bootstrap/mir_lower.py` — rename labels in each `_emit_*()` method
- `docs/builtin-inventory.md` — reflect new names

Rename map (Phase 2):

| Old | New | Reason |
|-----|-----|--------|
| `str_i64` | unchanged | already correct |
| `str_bool` | unchanged | already correct |
| `str_arr_i8` | `arr_i8_str` | "array i8 to string" is semantically clear |
| `str_cat` | unchanged | already correct |
| `str_eq` | unchanged | already correct |
| `str_slice` | unchanged | already correct |
| `str_replace_char` | unchanged | already correct |
| `str_get` | unchanged | already correct |
| `str_starts_with` | unchanged | already correct |
| `str_find` | unchanged | already correct |
| `str_trim` | unchanged | already correct |
| `bytes_str` | `str_bytes` | "string to bytes" — function implements `str→u8[]` |
| `__epic_cstr` | `str_cstr` | MIR helper, not x64 primitive |
| `new_arr_i8` | unchanged | already correct |
| `new_arr_i8_empty` | unchanged | already correct |
| `arr_i8_get` | unchanged | already correct |
| `arr_i8_set` | unchanged | already correct |
| `arr_i8_push` | unchanged | already correct |
| `arr_i8_slice` | unchanged | already correct |
| `arr_i64_get` | unchanged | already correct |
| `arr_i64_set` | unchanged | already correct |
| `extend_i8` | unchanged | already correct |
| `__epic_arr_qword_new` | `qword_new` | MIR helper, not x64 primitive |
| `__epic_arr_i64_push` | `arr_i64_push` | MIR helper, not x64 primitive |
| `__epic_arr_ptr_push` | `arr_ptr_push` | MIR helper, not x64 primitive |
| `__epic_arr_qword_extend` | `qword_extend` | MIR helper, not x64 primitive |
| `__epic_arr_i64_get` | `arr_i64_get` | MIR helper, not x64 primitive |
| `__epic_arr_ptr_get` | `arr_ptr_get` | MIR helper, not x64 primitive |

Kept `__epic_` prefix (x64 primitives):

| Name | Reason |
|------|--------|
| `__epic_alloc` | Windows API wrapper, platform data dependent |
| `__epic_runtime_start` | x64 entry hook, internal |
| `array_oob` | x64-level abort, internal |

### Phase 3: `required_helpers` plumbing

Add tracking in `mir_codegen.py` to record which externs each function actually uses.

Implementation sketch:

```python
class MirCodegen:
    def __init__(self):
        # …
        self.required_helpers: set[str] = set()

    def _emit_call(self, name, args, target_type):
        self.required_helpers.add(name)
        # … emit call inst as before

    def emit_program(self, ast):
        # Remove unconditional extern registration
        # After all functions lowered, register only required_helpers as externs
```

Details:
- `_emit_call` is called for builtin lowering, so `required_helpers` naturally accumulates.
- The unconditional `self.program.externs.append(MirExtern(...))` block in `emit_program()` is replaced with:
  ```python
  for name in sorted(self.required_helpers):
      sig = HELPER_SIGNATURES[name]
      self.program.externs.append(MirExtern(name, sig))
  ```
- `HELPER_SIGNATURES` is a dict mapping helper name → MirSignature, defined once.
- After Phase 3, MIR programs only declare externs that are actually used.

### Phase 4: Python builder injects MIR helpers

Create `bootstrap/mir_runtime_helpers.py` that provides Python functions to emit MIR-level function definitions for each helper.

This is the **core migration**: instead of emitting x64 asm directly (`_emit_str_i64()` in `mir_lower.py`), the builder emits MIR `MirFunction` objects that go through the standard MIR→x64 lowering.

```python
# mir_runtime_helpers.py

def emit_str_i64(module: MirProgram) -> MirFunction:
    """Inject str_i64 as an MIR function.
    
    Returns a MirFunction with MIR instructions (call to __epic_alloc,
    div/mod loop, store chars, etc.)
    """
    # … MIR instruction bodies, lowered via standard path
```

After Phase 4:
- `mir_lower.py` no longer calls `_emit_str_i64()` etc.
- MIR functions are injected into the program before lowering.
- `x64_runtime.append_runtime_helpers()` only emits `__epic_alloc`, `__epic_arr_qword_new`, and data globals.

This can be done **helper-by-helper** to keep commits small. A single helper migration per commit:

```
Commit 1: mir_runtime_helpers.py structure + str_cat as MIR helper
Commit 2: str_slice as MIR helper
Commit 3: str_replace_char, str_starts_with, str_find as MIR helpers
…
```

### Phase 5: Migrate `bytes_to_str` / `str_to_bytes`

After Phase 4, these two helpers still have the known copy-semantics issue. Phase 5 addresses them.

Currently `bytes_str` (which will be renamed to `str_bytes` in Phase 2) has:
- Current behaviour: copies string data into a fresh `u8[]` via `HeapAlloc` + memcpy loop
- Expected behaviour if copy is needed: same as current
- Question to resolve: should `bytes(s)` return a zero-copy view or a copy?

This requires a separate investigation and is a **language semantics decision**, not just a code rearrangement. It's in Phase 5 because by then the helper boundary is clean and the copy issue can be discussed in isolation.

### Phase 6: Future TODO

- `u64_to_str`: implement `str_u64` helper (currently only `str_i64` exists)
- Remove unreferenced helpers: `putc` label, `_putc_buf` data
- Move `array_oob` from x64 primitive to MIR helper (it's a print+exit, could be MIR)
- When self-hosted compiler is ready: rewrite `mir_runtime_helpers.py` in Epic as `.ep` source files

## Open Questions (for discussion, not blocking)

1. **Q: Should `str_bytes` (`str→u8[]`) return a copy or a view?**  
   A: Deferred to Phase 5. Currently it copies. If zero-copy, lifecycle management needs attention.

2. **Q: Should `__epic_arr_qword_new` remain an x64 primitive?**  
   A: Currently yes — it's a core array allocation primitive. But it could become a MIR helper in Phase 6 if the `__epic_alloc` boundary is clean enough.

3. **Q: How fine-grained should the Phase 4 commits be?**  
   A: One helper per commit, or one family per commit (e.g., all `map_*` helpers in one commit). The granularity is a process choice.

4. **Q: Should `required_helpers` Phase 3 come before or after Phase 2 rename?**  
   A: Before. Renames touch many lines; `required_helpers` is a focused code change. Doing Phase 3 first minimizes merge/conflict surface.

## Progress Tracking

| Phase | Status |
|-------|--------|
| Phase 1: Docs and inventory cleanup | **This commit** |
| Phase 2: Helper naming rename | ❌ |
| Phase 3: `required_helpers` plumbing | ❌ |
| Phase 4: Python builder injects MIR helpers | ❌ |
| Phase 5: Migrate str↔bytes | ❌ |
| Phase 6: Future TODO | ❌ |
