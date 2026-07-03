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
str:            defer; keep for now, u8[] is the long-term truth
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
| `extend`      | Array extend |
| `itoa`        | Integer to string (kept for now) |
| `str(bytes)`  | `u8[]` to `str` (kept for now) |
| `bytes(s)`    | `str` to `u8[]` (kept for now) |
| `str_new`     | Raw pointer + len (kept as escape hatch) |
| `cstr`        | NUL-terminated C string (kept for WinAPI interop) |
| `str_slice`   | String slice (kept for now) |
| `str_starts_with` | (kept for now) |
| `str_find`    | (kept for now) |
| `str_trim`    | (kept for now) |
| `str_replace_char` | (kept for now) |
| `system`      | Shell command (kept for now) |
| `map_has`     | Map lookup (kept for now) |

### Runtime Helpers (MIR-implemented)

These are unconditionally injected and considered part of the core runtime:

- `bytes_str` — str to `_arr_i8`
- `str_arr_i8` — `_arr_i8` to str
- `str_bool` — bool to static string
- `str_eq` — string equality
- `str_cat` — string concatenation
- `str_slice` — string slice copy
- `str_starts_with` — prefix test
- `str_get` — bounds-checked byte read
- `str_find` — substring find
- `str_replace_char` — char replacement copy
- `str_trim` — trim whitespace
- `new_arr_i8` — allocate initialized byte array
- `new_arr_i8_empty` — allocate empty byte array
- `arr_i8_get` — bounds-checked byte read
- `arr_i8_set` — bounds-checked byte write
- `arr_i8_push` — byte append
- `arr_i8_slice` — byte array slice copy
- `extend_i8` — byte array append

### Map

`map[str]T` is retained but not a priority feature. Lookup of non-existent keys
returns zero value.

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

### ADT-Related Compiler Code Paths

- `bootstrap/sema.py` — ADT type registration, variant checking
- `bootstrap/mir_codegen.py` — ADT allocation, tag dispatch, payload lowering
- `bootstrap/mir.py` — ADT-specific ops or validators
- `src/parser.ep` — ADT parse rules (to be removed last)
- `src/codegen.ep` — ADT codegen paths (to be removed last)

---

## Deferred

These are not decided yet. They remain as-is for now, and will be addressed
after ADT removal and naming unification.

| Topic | Current Status | Future Direction |
|-------|---------------|------------------|
| `str` vs `u8[]` | `str` is kept; `u8[]` is file I/O truth | Long-term: unify text as `u8[]`; `str` becomes thin wrapper or removed |
| `str` helpers (`str_slice`, `str_find`, etc.) | Kept for now | Migrate to byte-oriented helpers (`bytes_find`, `bytes_slice`) then remove `str_*` public surface |
| Helper naming | Current mixed convention | Unify to `bool_to_str`, `i64_to_str`, `arr_i8_push`, etc. |
| `required_helpers` / lazy injection | Unconditional injection | Defer until helper naming is stable |
| `match` general future | Kept as literal switch | Decide later whether to keep or remove |
| `system` | Kept for now | May be removed from core |
| `map` | Kept for now | May be removed from core |
| `itoa` | Kept for now | May be replaced by generic int-to-string |
| `cstr` | Kept for now | May be removed when WinAPI interop is redesigned |

---

## Langauge Feature Inventory

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
- Zero-value initialization
- Slice syntax `s[start:end]`
- `match` literal switch only
- Builtins: `print` / `println` / `read_file` / `write_file` / `exit` / `len` / `cap` / `push` / `extend`
- String builtins (deferred removal): `str` / `bytes` / `str_new` / `str_slice` / `str_starts_with` / `str_find` / `str_trim` / `str_replace_char` / `itoa` / `cstr` / `system`
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

### Phase 1: ADT Removal (immediate)
1. Document decisions (this file)
2. Mark ADT as removed in design docs
3. Remove ADT examples
4. Add ADT compile-fail tests
5. Reject ADT in sema
6. Remove ADT MIR codegen paths
7. Remove ADT parser support
8. Update remaining docs

### Phase 2: Naming Unification (after Phase 1)
- `str_bool` → `bool_to_str`
- `str_i64` → `i64_to_str`
- `str_arr_i8` → `bytes_to_str`
- `bytes_str` → `str_to_bytes`
- `str_new` → `raw_to_str`
- `__epic_cstr` → `str_cstr`
- `__epic_arr_i64_push` → `arr_i64_push`
- `__epic_arr_ptr_push` → `arr_ptr_push`
- `__epic_arr_qword_extend` → `qword_extend`
- `__epic_arr_ptr_get` → `arr_ptr_get`

### Phase 3: `str` → `u8[]` Convergence (after Phase 2)
- Document byte-buffer-first text model
- Add byte-oriented helpers alongside str helpers
- Migrate compiler source to `u8[]`
- Remove public `str` helper surface last

---

## References

- [`design.md`](design.md) — Epic language design (will be updated)
- [`impl.md`](impl.md) — Epic implementation notes (will be updated)
- [`builtin-inventory.md`](builtin-inventory.md) — Full builtin function inventory
- [`mir-runtime-helper-plan.md`](mir-runtime-helper-plan.md) — MIR helper migration plan
- [`todo.md`](../todo.md) — Project todo
