# Self-Hosting Core Language Surface

This document defines the **self-hosting core** of Epic — the minimal language
surface that the Epic self-hosted compiler (`src/`) is allowed to rely on.
Everything outside this core is either **removed** from the self-hosting path
or **deferred** for later decision.

> **Purpose**: A single source of truth for what the language is allowed to be,
> so that every removal, renaming, or simplification commit can reference this
> document instead of starting a new debate each time.

---

## Decision Model

```
ADT:            remove (not in core)
match:          keep literal switch only; remove ADT match
str:            public surface contracted (see below); zero-copy str/bytes
naming:         unify, but only after ADT removal
required_helpers: defer; unconditional injection stays for now
```

---

## Retained (in core)

### Scalar Types

| Type   | Notes |
|--------|-------|
| `bool` | Logical true/false |
| `u8`   | Byte |
| `i32`  | Signed 32-bit, stored in 8-byte slot |
| `u32`  | Unsigned 32-bit, stored in 8-byte slot |
| `i64`  | Signed 64-bit |
| `u64`  | Unsigned 64-bit |

### Compound Types

| Type     | Notes |
|----------|-------|
| `struct` | Heap-allocated reference; named fields, 8-byte slot layout |
| `T[]`    | Heap-allocated dynamic array descriptor |
| `str`    | Kept for now; see Deferred |

### Control Flow

| Construct   | Notes |
|-------------|-------|
| `if`/`else if`/`else` | Boolean condition required |
| `while`     | Boolean condition required |
| `for i in start:end` | Half-open increasing range |
| `break`/`continue` | Bound to innermost `while`/`for` |
| `return`    | With or without expression |

### Functions

| Feature | Notes |
|---------|-------|
| `fun name(params): ret { body }` | Max 4 parameters |
| `main` entry | `fun main(): void` |
| Recursion | Allowed |

### Expressions

| Feature | Notes |
|---------|-------|
| Integer literals | Type-adaptive |
| `true`/`false` | Bool literals |
| String literals | Produce `str` (temporary) |
| Char literals | Produce `u8` |
| Arithmetic | `+` `-` `*` `/` `%` checked |
| Comparison | `==` `!=` `<` `<=` `>` `>=` |
| Logical | `&&` `||` `!` |
| Bitwise | `~` `&` `|` `^` |
| Shift | `<<` `>>` `>>>` |
| Compound assignment | `+=` `-=` `*=` `/=` `%=` `<<=` `>>=` `>>>=` `&=` `|=` `^=` |
| Explicit integer conversion | `i32(x)` `u32(x)` `i64(x)` `u64(x)` `u8(x)` `bool(x)` |

### Builtins

| Builtin      | Notes |
|--------------|-------|
| `print`/`println` | String output |
| `read_file`   | Returns `u8[]` |
| `write_file`  | Writes `u8[]`, returns `i64` |
| `exit`        | Terminate process |
| `len`/`cap`   | Length and capacity |
| `push`        | Array append |
| `extend`      | u8[] only; use for + push for other types |
| `str(bytes)`  | `u8[]` to `str` (kept for now) |
| `bytes(s)`    | `str` to `u8[]` (kept for now) |
| `cstr`        | NUL-terminated C string (kept for WinAPI interop) |
| `str_new`     | 🚫 Removed from public surface; use `str(bytes)` |
| `itoa`        | 🚫 Removed from public surface; use `str(n)` |
| `str_slice`   | Removed from public surface; internal helper only |
| `str_starts_with` | Removed from public surface |
| `str_find`    | Removed from public surface |
| `str_trim`    | Removed entirely; write byte scanning in Epic |
| `str_replace_char` | Removed entirely; write byte scanning in Epic |
| `system`      | Shell command (kept for now) |
| `map_has`     | Map lookup (kept for now) |

### Runtime Helpers (MIR-implemented)

These are unconditionally injected and considered part of the core runtime:

- `__ep_slice_u8_from_str` — str to `_slice_u8`
- `__ep_str_from_slice_u8` — `_slice_u8` to str
- `__ep_str_from_bool` — bool to static string
- `__ep_str_eq` — string equality
- `__ep_str_cat` — string concatenation
- `__ep_str_slice` — string slice copy
- `__ep_str_starts_with` — prefix test
- `__ep_str_get` — bounds-checked byte read
- `__ep_str_find` — substring find
- `__ep_slice_u8_alloc` — allocate initialized byte array
- `__ep_slice_u8_alloc` — allocate empty byte array
- `__ep_slice_u8_get` — bounds-checked byte read
- `__ep_slice_u8_set` — bounds-checked byte write
- `__ep_slice_u8_push` — byte append
- `__ep_slice_u8_slice` — byte array slice copy
- `__ep_slice_i64_get` — bounds-checked i64 array read
- `__ep_slice_i64_set` — bounds-checked i64 array write
- `__ep_slice_u8_extend` — byte array append

### Map

`map[str]T` is retained but not a priority feature. Lookup of non-existent keys
returns zero value. The Python reference compiler currently supports
`map[str]i64`, `map[str]bool`, and `map[str]str`, plus `map_has` and
`map_del`.

### OS Namespace

`os.<dll>.<Function>(<args>)` is retained for WinAPI interop (kernel32, user32).  
FFI arguments are `i64`; C strings require explicit `cstr(...)`.

### Globals

`argv: str[]` — command-line arguments.

---

## Removed from Self-Hosting Core

### ADT (Algebraic Data Types)

ADT is **not** part of the self-hosting core. The following are removed:

| Feature | Reason |
|---------|--------|
| `type Name { Variant1 Variant2 { f: T } }` | Full ADT definition |
| `new Expr.IntLit { value: 123 }` | Variant initialization |
| ADT match | `match e { Expr.IntLit { n }: ... }` — payload binding |
| ADT zero value | Tag `0` + first variant's zero payload |
| ADT repr | 16-byte header (tag + payload pointer) |
| ADT payload lowering | MIR allocation + tag dispatch |

**`match` for literal switch is kept** — see Retained.

### ADT-Related Compiler Code Paths (removed or deferred)

**Python reference compiler (cleared):**
- `bootstrap/sema.py` — ADT type registration, variant checking → **removed**
- `bootstrap/mir_codegen.py` — ADT allocation, tag dispatch, payload lowering → **removed**
- `bootstrap/mir.py` — ADT-specific ops or validators → **removed**

**Self-hosted compiler (deferred):**
- `src/parser.ep` — ADT parse rules
- `src/codegen.ep` — ADT codegen paths

---

## Deferred

These are not decided yet. They remain as-is for now, and will be addressed
after ADT removal and naming unification.

| Topic | Current Status | Future Direction |
|-------|---------------|------------------|
| `str` vs `u8[]` | `str` is kept; `u8[]` is core text truth | Long-term: unify text as `u8[]`; `str` becomes thin view or removed. Public str helper surface removed in Phase 0. |
| `str` helpers (`str_slice`, `str_find`, etc.) | Public surface removed | Internal helpers stay; user code uses `u8[]` byte scanning directly |
| Helper naming | `arr` → `slice` rename complete | `i8` (MIR internal) deferred |
| `required_helpers` / lazy injection | Unconditional injection | Defer until helper naming is stable |
| `match` general future | Kept as literal switch | Decide later whether to keep or remove |
| `system` | Kept for now | May be removed from core |
| `map` | Kept for now | May be removed from core |
| `itoa` | Removed from public surface | Use `str(n)` |
| `i8` public type | Removed | `u8` is Epic's only byte type; byte loads zero-extend to 0..255 |
| `cstr` | Kept for now | May be removed when WinAPI interop is redesigned |

---

## Language Feature Inventory

### Features retained in core

- `i64` / `u64` / `i32` / `u32` / `u8` / `bool`
- `str` (temporary, see Deferred)
- `struct`
- `T[]` (dynamic array)
- `map[str]T` (kept for now)
- `fun` / `if` / `while` / `for` / `return` / `break` / `continue`
- `new S { ... }` struct initialization
- `new T[] { ... }` array literal
- `new T[n]` array allocation
- `let` binding with optional type annotation
- Zero-value initialization for built-in types (i64, bool, str, T[], map[str]T)
- Zero-value containers may be internally represented by a `0` slot and lazily materialized by compiler-inserted ensure code
- **Struct requires explicit `new`**; `let b: Box` is a compile error
- Slice syntax `s[start:end]`
- `match` literal switch only
- Builtins: `print` / `println` / `read_file` / `write_file` / `exit` / `len` / `cap` / `push` / `extend` / `map_has` / `map_del`
- String builtins (retained): `len(s)` / `s[i]` / `s[start:end]` / `s1 == s2` / `s1 != s2` as syntax; `str(bytes)` / `bytes(s)` as zero-copy cast; `cstr` as escape hatch
- String builtins (removed from public surface):
  - `str_new` — removed entirely; use `str(bytes)`
  - `itoa` — removed entirely; use `str(n)`
  - `str_slice`, `str_starts_with`, `str_find`, `str_cat`, `str_get` — removed from public surface; internal helpers retained where syntax lowering still needs them
  - `str_replace_char`, `str_trim` — removed entirely; write byte scanning in Epic
- `system` kept for now
- `os.*` WinAPI calls
- `argv` global
- `assert` / `panic`

### Features removed from core

- `type Name { ... }` ADT definition
- `new A.V { ... }` variant initialization
- ADT match with payload binding
- ADT-specific lowering paths
- ADT constructor shorthand `new A.V`

---

## Migration Strategy

### Phase 0: Str Surface Contraction (this commit)
- [x] 1. Document zero-copy str/bytes semantics
- [x] 2. Remove public str helper builtins from docs
- [x] 3. Document internal helper policy
- [x] 4. Document literal sharing / shared buffer semantics
- [_] 5. (Next commit) Remove public str helper from sema
- [_] 6. (Next commit) Remove `str + str` from sema
- [x] 7. Add zero-copy behavior test (`examples/v5_zero_copy_str_bytes.ep`)

### Phase 1: ADT Removal (completed)
- [x] 1. Document decisions (this file)
- [x] 2. Mark ADT as removed in design docs
- [x] 3. Remove ADT examples
- [x] 4. Remove ADT from Python reference compiler
- [x] 5. Make Python-only test entry explicit (`tests/run.py`)
- [x] 6. Purge stale ADT docs
- [_] Deferred: Remove ADT from self-hosted compiler sources (`src/*.ep`)

### Phase 2: Naming Unification (completed)
Decision: keep internal ABI names with the `__ep_*` / `__epx_*` prefixes.
Do not rename helpers to public-looking bare names such as `bool_to_str`,
`i64_to_str`, `bytes_to_str`, `str_to_bytes`, or `arr_ptr_push`.

Current direction names:
- `__ep_str_from_bool` — bool → str
- `__ep_str_from_i64` — i64 → str
- `__ep_str_from_slice_u8` — u8[] → str
- `__ep_slice_u8_from_str` — str → u8[]
- `__ep_slice_i64_*` — i64[] operations
- `__ep_slice_ptr_*` — pointer slice operations

Older names such as `str_bool`, `str_i64`, `str_arr_i8`, `bytes_str`, and
`__epic_arr_*` have been removed from implementation code. The old Phase 2
plan to rename helpers to bare names is obsolete.

### Phase 3: `str` → `u8[]` Convergence (public surface completed; self-hosted source cleanup remains)

Completed:
- The byte-buffer-first text model is documented.
- `read_file` / `write_file` use `u8[]` as the data carrier.
- `str(u8[])` and `bytes(str)` are zero-copy identity casts.
- The zero-copy shared-buffer behavior is covered by `examples/v5_zero_copy_str_bytes.ep`.
- Public str helper surface is removed: `str_new`, `itoa`, `str_find`,
  `str_starts_with`, `str_replace_char`, and `str_trim` are not public builtins.
- `extend` is byte-oriented and only supports `u8[]`.

Remaining:
- Some `src/*.ep` self-hosted compiler code still calls old helpers such as
  `itoa`, `str_find`, and `str_new`. These should migrate to `str(n)`,
  explicit `u8[]` byte scanning, and `str(bytes)`.

Conclusion: Phase 3 is complete for the public language surface, docs, and tests;
it is not fully complete until the self-hosted compiler source stops using the old helpers.

---

## References

- [`design.md`](design.md) — Epic language design (will be updated)
- [`impl.md`](impl.md) — Epic implementation notes (will be updated)
- [`builtin-inventory.md`](builtin-inventory.md) — Full builtin function inventory
- [`mir-runtime-helper-plan.md`](mir-runtime-helper-plan.md) — MIR helper migration plan
- [`todo.md`](../todo.md) — Project todo
