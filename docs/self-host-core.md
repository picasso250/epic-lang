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
ADT:            planned as struct union (v1 design)
match:          keep literal switch and add ADT match later
str:            retained byte-string source type; shares current u8[] layout
naming:         unify, but only after ADT removal
required_helpers: explicit dependency tables deferred; MIR function pruning removes unreachable helpers/functions for now
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
| `str`    | Retained byte-string/text type; current runtime header matches `u8[]` |

### Control Flow

| Construct   | Notes |
|-------------|-------|
| `if`/`else if`/`else` | Boolean condition required |
| `while`     | Boolean condition required |
| `for i in start:end` | Half-open increasing numeric range; cursor is loop block scoped |
| `for i in xs` | Array index iteration; `i: i64`, loop block scoped |
| `break`/`continue` | Bound to innermost `while`/`for` |
| `ret`       | With or without expression |

### Functions

| Feature | Notes |
|---------|-------|
| `fun name(params): ret { body }` | Windows x64 register/stack arguments; body may use a tail expression as the return value |
| `main` entry | `fun main(): void` |
| Recursion | Allowed |

### Expressions

| Feature | Notes |
|---------|-------|
| Integer literals | Type-adaptive |
| `true`/`false` | Bool literals |
| String literals | Produce `str` for now; migration target is byte-buffer-first text |
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
| `print`/`println` | Text/byte-buffer output; currently accepts `str` |
| `read_file`   | Returns `u8[]` |
| `write_file`  | Writes `u8[]`, returns `i64` |
| `exit`        | Terminate process |
| `len`/`cap`   | Length and capacity |
| `xs.push(x)` | Array append dot call |
| `xs.pop()` | Delete and return the last element; empty array panics |
| `dst.extend(src)` | dot call for arrays with the same element type |
| `str(x)`      | transitional formatting/view operation: only `str`, integers, `bool`, and `u8[]`; no struct/non-u8 array repr |
| `str(bytes)`  | Explicit `u8[]` to `str` view; zero-copy identity cast |
| `bytes(s)`    | Explicit `str` to mutable `u8[]` view; zero-copy identity cast |
| `cstr`        | NUL-terminated C string (kept for WinAPI interop) |
| `str_new`     | 🚫 Removed from public surface; use `str(bytes)` |
| `itoa`        | 🚫 Removed from public surface; use `str(n)` |
| `str_slice`   | Removed from public surface; internal helper only |
| `str_starts_with` | Removed from public surface |
| `str_find`    | Removed from public surface |
| `str_trim`    | Removed entirely; write byte scanning in Epic |
| `str_replace_char` | Removed entirely; write byte scanning in Epic |

### Runtime Helpers (MIR-implemented)

These are core runtime helpers. MIR helper bodies used by both compilers live in the committed bundle `runtime/mir/helpers.mir`; both compilers load the bundle and then prune unreachable MIR functions. Edit the canonical bundle directly; its function order is authoritative:

- `__ep_str_from_bool` — bool to static string
- `__ep_str_eq` — string equality
- `__ep_str_cat` — string concatenation
- `__ep_str_slice` — string slice copy
- `__ep_slice_u8_alloc` — allocate initialized byte array
- `__ep_slice_u8_alloc` — allocate empty byte array
- `__ep_slice_u8_get` — bounds-checked byte read
- `__ep_slice_u8_set` — bounds-checked byte write
- `__ep_slice_u8_push` — byte append
- `__ep_slice_u8_pop` / `__ep_slice_i64_pop` / `__ep_slice_ptr_pop` — array pop helpers
- `__ep_slice_u8_slice` — byte array slice copy
- `__ep_slice_i64_get` — bounds-checked i64 array read
- `__ep_slice_i64_set` — bounds-checked i64 array write
- `__ep_slice_u8_extend` / `__ep_slice_i64_extend` / `__ep_slice_ptr_extend` — array append

### Extern FFI

`extern "library.dll" fun Name(params): Ret` declares an exact Windows x64 import.
ABI types are `i32`, `u32`, `i64`, `u64`, and `void` for returns. Foreign pointers and handles are opaque `u64` bit patterns; source-level `ptr`, dereference, pointer arithmetic, and `null` literals are not part of the language. C strings require explicit `cstr(...)`, which returns `u64`. The old `os.*` namespace is removed.

### Globals

`argv: str[]` — command-line arguments.

---

## Removed from Self-Hosting Core

### Built-in Map

`map[str]T`, map literals, map subscripting, `.has` / `.del`, map iteration,
and all `__ep_map_*` runtime helpers are removed. Compiler internals use explicit
arrays and linear lookup where associative lookup is needed.

### ADT (Algebraic Data Types)

ADT is planned as a closed struct union feature. It is not implemented in the self-hosting core yet.

The v1 model:

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
- `bootstrap/ast_to_mir.py` — ADT allocation, tag dispatch, payload lowering → **removed**
- `bootstrap/mir.py` — ADT-specific ops or validators → **removed**

**Self-hosted sources:**
- `src/parser.ep` — ADT parse rules remain deferred/stale until parser cleanup
- old `src/codegen.ep` ADT codegen paths were deleted with the NASM-oriented codegen line

---

## Deferred

These are not decided yet. They remain as-is for now, and will be addressed
after ADT removal and naming unification.

| Topic | Current Status | Future Direction |
|-------|---------------|------------------|
| `str` vs `u8[]` | Distinct source types with the same current `{data,len,cap}` layout | Keep text semantics on `str`, mutable-buffer semantics on `u8[]`; the representation may diverge later. See `str-u8-layout-contract.md`. |
| `str` helpers (`str_slice`, `str_find`, etc.) | Public surface removed | Internal helpers stay; user code uses `u8[]` byte scanning directly |
| Helper naming | `arr` → `slice` rename complete | `i8` (MIR internal) deferred |
| `required_helpers` / lazy injection | MIR function reachability pruning | Explicit dependency tables deferred; current pass keeps `main` and x64-runtime MIR roots. |
| `match` general future | Kept as literal switch | Decide later whether to keep or remove |
| `itoa` | Removed from public surface | Use `str(n)` |
| `i8` public type | Removed | `u8` is Epic's only byte type; byte loads zero-extend to 0..255 |
| `cstr` | Returns an opaque `u64` C-string address for extern calls | Keep explicit; no implicit FFI string conversion |

---

## Language Feature Inventory

### Features retained in core

- `i64` / `u64` / `i32` / `u32` / `u8` / `bool`
- `str` (retained byte-string/text source type)
- `struct`
- `T[]` (dynamic array)
- `fun` / `if` / `while` / `for` / `ret` / `break` / `continue`
- `new S { ... }` struct initialization
- `new T[] { ... }` array literal
- `new T[n]` array allocation
- `let` binding with optional type annotation
- Top-level/global `let` is removed; mutable state must be local or passed explicitly
- Local variable declarations must have an initializer; optional type annotations only constrain/check the initializer
- No zero-value initialization for locals; use literals, `new`, calls, or other expressions explicitly
- Lexical block scope for `let`, ADT match bindings, and loop cursors
- Heap-backed references (`str`, `T[]`, structs, ADT wrappers) may use `0` as null storage, but compiler-inserted container materialization is not part of the language model
- Postfix `expr?` is the only public null-check surface: it accepts reference types and returns `bool`; it is not ADT field-exists syntax and it does not dereference the checked value
- `new S { ... }` allows partial field initialization: omitted scalar fields default to `0` / `false`, omitted reference fields default to null
- Slice syntax `s[start:end]`
- `match` literal switch only
- Function-style builtins: `print` / `println` / `read_file` / `write_file` / `exit` / `len` / `cap` / `str` / `bytes` / `cstr`
- Builtin container dot calls: `xs.push(x)` / `xs.pop()` / `dst.extend(src)`
- User methods v1: `fun (receiver: StructName) method(args...): Ret { ... }`; receiver type must be a user-defined struct.
- User method lowering: `fun (p: Parser) peek(): Token` occupies the global symbol `Parser__peek`; `p.peek()` lowers to `Parser__peek(p)`.
- Method calls do not support overloads, traits, inheritance, virtual dispatch, method values, generics, or fallback to `peek(p)`.
- Ordinary function names may contain `__`; if a method-generated `Type__method` symbol duplicates an existing function, normal duplicate-definition checking rejects it.
- String/byte-view operations (retained temporarily): `len(s)` / `s[start:end]` / `s1 == s2` / `s1 != s2` / `s1 + s2`; `+` allocates a new `str`, equality compares contents, byte indexing goes through `bytes(s)[i]`, and `str(bytes)` / `bytes(s)` are zero-copy identity casts
- String builtins (removed from public surface):
  - `str_new` — removed entirely; use `str(bytes)`
  - `itoa` — removed entirely; use `str(n)`
  - `str_slice`, `str_cat` — function-style builtins removed from public surface; internal helpers retained for slice and `+` syntax lowering
  - `str_replace_char`, `str_trim` — removed entirely; write byte scanning in Epic
- Top-level `extern` declarations with `i32/u32/i64/u64/void` ABI types
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
- [x] 5. Remove public str helper from sema
- [x] 6. Define `str + str` as allocating concatenation and reject string ordering / `str += str`
- [x] 7. Add zero-copy behavior test (`tests/e2e/pass/v5_zero_copy_str_bytes.ep`)

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
- `__ep_str_from_i64` — i64 → str, implemented in `runtime/str.ep`
- `__ep_str_from_u64` — u64 → str, implemented in `runtime/str.ep`
- `str(u8[])` / `bytes(str)` — identity casts lowered without helper calls
- `__ep_slice_i64_*` — i64[] operations
- `__ep_slice_ptr_*` — pointer slice operations

Older names such as `str_bool`, `str_i64`, `str_arr_i8`, `bytes_str`, and
`__epic_arr_*` have been removed from implementation code. The old Phase 2
plan to rename helpers to bare names is obsolete.

### Phase 3: String / byte-buffer boundary cleanup (active)

Completed:
- The source-level distinction between `str` text values and mutable `u8[]` buffers is documented.
- `read_file` / `write_file` use `u8[]` as the data carrier.
- `str(u8[])` and `bytes(str)` are zero-copy identity casts. `str(struct)` and `str(T[])` for non-`u8` arrays are not supported; f-string interpolation uses the same convertibility rule as `str(expr)`.
- The zero-copy shared-buffer behavior is covered by `tests/e2e/pass/v5_zero_copy_str_bytes.ep`.
- Public str helper surface is removed: `str_new`, `itoa`, `str_find`,
  `str_starts_with`, `str_replace_char`, and `str_trim` are not public builtins.
- `xs.pop()` removes and returns the last element, and panics on an empty array. `dst.extend(src)` appends arrays with the same element type. Function-style `push`, `pop`, and `extend` are removed from the public source surface.

Remaining:
- No retained `src/*.ep` source currently calls removed public string helpers. `src/link.ep` uses local `u8[]` byte scanning plus `str(n)`, and `src/parser.ep` no longer reserves `str_new`.

Conclusion: `str` remains a source-level byte-string/text type. The active direction is to keep text operations (`+`, `==`, `!=`, slicing, formatting) on `str`, keep mutable/binary operations on `u8[]`, and preserve explicit zero-copy views while the layouts match. See [`str-u8-layout-contract.md`](str-u8-layout-contract.md).

---

## References

- [`design.md`](design.md) — Epic language design (will be updated)
- [`impl.md`](impl.md) — Epic implementation notes (will be updated)
- [`builtin-inventory.md`](builtin-inventory.md) — Full builtin function inventory
- [`str-u8-layout-contract.md`](str-u8-layout-contract.md) — source-type and shared-layout contract
- [`todo.md`](../todo.md) — Project todo

