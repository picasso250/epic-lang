# MIR Runtime Helper Plan

## Goal

把 runtime helper 从「x64 lower 阶段无条件注入」逐步迁移到「MIR 层注入」。
当前策略是全量注入所有已实现的 MIR helper，暂不维护 required-helper
依赖图。

## Why

当前链路 `mir_codegen.py` → `mir_lower.py` 的做法是：

1. `mir_codegen.emit_program()` **无条件注册全部 extern**（~40 个），不管用户代码实际用到了几个。
2. `mir_lower.lower()` → `append_runtime_helpers()` → `_emit_runtime_helpers()` **无条件生成全部 x64 标签、全部 x64 helper 函数体**，不管用户代码是否调用。

这意味着：
- **编译所有程序都携带了全套 helper**。`print("hello")` 也会生成 `__epic_arr_ptr_push`、`str_find` 等无关代码。
- **MIR 层对 x64 层有隐式依赖**：MIR 只是记录了 extern 声明，真正有没有实现要到 x64 lower 阶段才确定。
- **未来自举编译器要通过自身编译器 .ep 源码生成这些 helper**，但目前全部在 Python x64 汇编器里手写，迁移路径不清晰。

## Non-goals

本计划**不**覆盖：

- `bytes_to_str` copy 语义修正（有据可查的疑似 bug，但不在本阶段修）
- `u64_to_str` 缺位（`str_i64` 只支持 i64，不支持 u64；后续补）
- 删除 `public builtin`（`exit`、`system`、`read_file` 等保持不动）
- `__epic_alloc` 由 x64 primitive 迁移为 MIR helper（它依赖 `_heap` 全局变量，是 platform primitive；保持不动）
- 引入 `.ep` runtime 源码（中期用 Python builder 注入 MIR helper，不急着自举）

## Current Python implementation status

As of the current Python backend, runtime helpers are split into two implementation paths.

### MIR-implemented helpers

These helpers are emitted as normal `MirFunction`s by `bootstrap/mir_runtime_helpers.py`.
`bootstrap/mir_codegen.py` calls `inject_all_mir_helpers(program)` after user
functions are emitted. This injects every implemented MIR helper.

Implemented MIR helpers:

| helper | current trigger | implementation |
|---|---|---|
| `bytes_str` | `bytes(str)` conversion | `bootstrap/mir_runtime_helpers.py` |
| `str_arr_i8` | `str(u8[])` conversion | `bootstrap/mir_runtime_helpers.py` |
| `str_bool` | `str(bool)` conversion | `bootstrap/mir_runtime_helpers.py` |
| `str_eq` | string equality | `bootstrap/mir_runtime_helpers.py` |
| `str_cat` | string concatenation | `bootstrap/mir_runtime_helpers.py` |
| `str_slice` | string slice copy | `bootstrap/mir_runtime_helpers.py` |
| `str_starts_with` | string prefix check | `bootstrap/mir_runtime_helpers.py` |
| `str_find` | substring search | `bootstrap/mir_runtime_helpers.py` |
| `new_arr_i8` | `new u8[] { ... }` | `bootstrap/mir_runtime_helpers.py` |
| `new_arr_i8_empty` | `new u8[](n)` / empty-capacity byte arrays | `bootstrap/mir_runtime_helpers.py` |
| `arr_i8_get` | `u8[]` subscript read | `bootstrap/mir_runtime_helpers.py` |
| `arr_i8_set` | `u8[]` subscript write | `bootstrap/mir_runtime_helpers.py` |
| `arr_i8_push` | `push(u8[], value)` | `bootstrap/mir_runtime_helpers.py` |
| `arr_i8_slice` | `u8[]` slice copy | `bootstrap/mir_runtime_helpers.py` |
| `extend_i8` | `extend(u8[], u8[])` | `bootstrap/mir_runtime_helpers.py` |

Injection rules:

1. `inject_all_mir_helpers()` removes matching `MirExtern`s for every
   implemented helper.
2. It appends deterministic `MirFunction` bodies using `IMPLEMENTED_MIR_HELPERS`.
3. Runtime string globals such as `@str.runtime.bool.true` and
   `@str.runtime.bool.false` are injected idempotently before helper functions.
4. The normal MIR validator then sees these helpers as ordinary functions.

### Still x64-backed helpers

Most runtime helpers still live as `_emit_*` methods on `MirLower` in
`bootstrap/mir_lower.py`. `bootstrap/x64_runtime.py` owns the runtime append policy,
but most helper bodies have not moved into that module yet.

Important x64-backed families include:

| family | current owner |
|---|---|
| heap allocation primitive | `MirLower._emit_epic_alloc` |
| qword array primitives | `MirLower._emit_epic_arr_qword_*` |
| remaining string helpers (`str_i64`) | `MirLower._emit_str_i64` |
| i64-array helpers | `MirLower._emit_arr_i64_set` (`arr_i64_get` is now a MIR helper) |
| map helpers | `MirLower._emit_map_*` |
| file/process helpers | `MirLower._emit_read_file`, `_emit_write_file`, `_emit_system_cmd` |
| argv helper | `MirLower._emit_argv_init` |
| printing helpers | `MirLower._emit_print_str`, `_emit_print_newline`, `_emit_putc` |
| error helpers | `MirLower._emit_array_oob` |

### Duplicate-emission policy

Implemented MIR helpers are always present as `MirFunction`s, so their legacy
x64 fallback bodies have been deleted. `MirLower.lower()` now simply appends the
remaining full x64 runtime:

```python
append_runtime_helpers(self)
```

The current bridge is therefore:

```text
MIR helper present as MirFunction
  -> normal function lowering emits x64
  -> no same-named legacy x64 helper exists
```

### Current boundary

The current ownership boundary is:

| responsibility                                  | owner                    |
| ----------------------------------------------- | ------------------------ |
| Building MIR helper bodies                      | `mir_runtime_helpers.py` |
| Removing externs and injecting all implemented helper functions | `mir_runtime_helpers.py` |
| Runtime data emission                           | `x64_runtime.py`         |
| Startup hook call                               | `x64_runtime.py`         |
| Runtime append policy                           | `x64_runtime.py`         |
| Most x64 helper bodies                          | `mir_lower.py`           |

The next migration step should move one helper family at a time from x64-backed
`MirLower._emit_*` methods into MIR helper implementations.

Latest migration note: `extend_i8` now uses a small MIR loop that snapshots
`src.len`, calls `arr_i8_get`, then calls `arr_i8_push`. This intentionally
prioritizes code clarity over the previous specialized copy path; the current
`extend(xs, xs)` behaviour is preserved by the length snapshot.

`str_eq` is now a MIR helper as well. It compares string lengths first, then
loads and compares one byte at a time with no allocation and no WinAPI calls.

`str_starts_with` is now a MIR helper too. It checks the prefix length, then
compares prefix bytes directly and returns the existing `i64` truth value.

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
│     __epic_alloc (MIR-callable)      │
│     _heap, _argv, _str_i64_buf, …    │
│     __epic_runtime_start (internal)  │
│     Less than 10 items.              │
│     Still emitted in x64 lower.      │
├──────────────────────────────────────┤
│  3b. x64-backed runtime helpers      │
│     (transitional category)          │
│     __epic_arr_qword_new             │
│     array_oob                        │
│     These are callable from MIR but  │
│     currently have x64-only impls.   │
│     Future: migrate to MIR helper.   │
└──────────────────────────────────────┘
```

### Key boundary

**Current x64-backed runtime helper:**
  X64 label/function emitted by `mir_lower` / `x64_runtime` — **currently emitted unconditionally**,
  regardless of whether user code references it.
  MIR only declares the extern; the implementation lives in x64 asm generation.

**Target MIR helper:**
  `MirFunction` injected into `MirProgram` and lowered by the **normal MIR→X64 path**.
  The helper's body is composed of standard MIR ops (`call`, `load`, `store`, `gep`, arithmetic, `br`, etc.) — it goes through the same lowering as user code.
  Injected **on demand** based on `required_helpers` tracking.

- **x64 primitive** = x64 function/data that requires Windows API knowledge or x64-specific setup. These stay in the x64 backend.
  x64 primitives divide into two subcategories:

  1. **MIR-callable x64 primitive** — appears in MIR `call` / `extern`. E.g. `__epic_alloc`.
     It must be visible in the MIR program as an extern so that other MIR functions can call it,
     but its implementation stays in x64 backend because it depends on Windows API or platform data.

  2. **x64-internal primitive/data/startup** — not exposed to MIR at all.
     E.g. `_heap`, `_argv`, `__epic_runtime_start`, `argv_init`, `_str_i64_buf`.
     These are generated by `x64_runtime.py` in the data section or as startup hooks;
     no MIR function should directly reference them.

Currently the first category (x64-backed helpers) is the only category that exists. The target is to migrate as many as possible into the second category, leaving only true platform primitives as x64-specific.

Both categories are currently lumped together in `_emit_runtime_helpers()`.

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
    # … remaining x64-backed helpers, ALL unconditionally emitted
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
  │  __epic_alloc (MIR-callable)           │
  │  __epic_arr_qword_new (x64-backed)     │
  │  _heap, _argv, _startup (internal)     │
  │  data globals                          │
  ▼                                        │
x64.py                                     │
```

### Naming convention

After renaming, MIR helpers follow the pattern:

| Category | Pattern | Example | Currently named |
|----------|---------|---------|-----------------|
| Type→str | `<type>_to_str` | `i64_to_str`, `bool_to_str`, `bytes_to_str` | `str_i64`, `str_bool`, `str_arr_i8` → rename needed |
| str→type | `str_to_<type>` | `str_to_bytes` | `bytes_str` → rename needed |
| Raw str ctor | `raw_to_str` | `raw_to_str` | `str_new` — internal alias |
| u8[] operations | `arr_i8_<op>` | `arr_i8_get`, `arr_i8_push` | `arr_i8_get` ✓, `arr_i8_push` ✓ |
| i64[] operations | `arr_i64_<op>` | `arr_i64_get`, `arr_i64_set` | `arr_i64_get` ✓, `arr_i64_set` ✓ |
| ptr[] operations | `arr_ptr_<op>` | `arr_ptr_push` | `__epic_arr_ptr_push` → `arr_ptr_push` |
| map | `map_<op>` | `map_new`, `map_get` | `map_new` ✓, `map_get` ✓ |
| I/O | `print_<op>` | `print_str`, `print_newline` | `print_str` ✓, `print_newline` ✓ |
| Array core | `qword_<op>` | `qword_new`, `qword_push` | `__epic_arr_qword_new` → `qword_new` |
| str ops | `str_<op>` (lowercase) | `str_cat`, `str_eq`, `str_slice` | `str_cat` ✓, `str_eq` ✓, `str_slice` ✓ |

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
| `str_i64` | `i64_to_str` | "i64 to string" — reflects actual direction |
| `str_bool` | `bool_to_str` | "bool to string" |
| `str_arr_i8` | `bytes_to_str` | "u8[] to string" — `bytes` 比 `arr_i8` 更像语言层概念 |
| `str_new` | `raw_to_str` | "raw pointer+len to string" — 语义更清晰 |
| `bytes_str` | `str_to_bytes` | "string to bytes" — 方向明确 |
| `str_cat` | unchanged | already correct |
| `str_eq` | unchanged | already correct |
| `str_slice` | unchanged | already correct |
| `str_starts_with` | unchanged | already correct |
| `str_find` | unchanged | already correct |
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
| `__epic_arr_qword_extend` | ~~`qword_extend`~~ (removed) | MIR helper, not x64 primitive |
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
Commit 3: str_starts_with, str_find as MIR helpers
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
|---|---|
| Phase 1: Write plan | ✅ done |
| Phase 2: Helper naming cleanup | not done |
| Phase 3: `required_helpers` plumbing | ✅ partially done |
| Phase 4: Python builder injects MIR helpers | ✅ partially done |
| Phase 5: migrate remaining x64-backed helpers | in progress |
