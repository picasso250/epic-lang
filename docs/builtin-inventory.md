# Builtin Inventory

Current snapshot of functions handled specially by the active Python reference compiler pipeline. Historical self-hosted codegen notes may remain for context only.

> **2026-07-03 update**: Some `str_*` builtins have been removed from public surface.
> See [design.md](design.md) for the current public string surface.
> This document records the **status quo** of the compiler codebase — internal helpers
> still exist even after public removal.
> `bootstrap/epic_builtins.py` now records the Python-side builtin inventory,
> but it is not wired into parser, sema, or codegen yet.
> Active Python-side builtin handling lives in:
> - `bootstrap/sema.py` — type checking
> - `bootstrap/ast_to_mir.py` — typed AST to MIR
>
> `src/parser.ep` still has a reserved-name list. The old NASM-oriented `src/codegen_support.ep` / `src/codegen.ep` path has been deleted; any remaining `codegen.ep` column below is historical and should be removed in a later inventory refresh.

---

## I/O / Process

| Function | sema.py | ast_to_mir.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `print`  | ✓ (ln 401) | ✓ (ln 588) | ✗ | ✓ (ln 831) | Print with trailing newline — `println` handled same line |
| `println` | ✓ (ln 401) | ✓ (ln 580) | ✗ | ✓ (ln 831) | |
| `exit`   | ✓ (ln 414) | ✓ (ln 603) | ✗ | ✗ | Terminate process; `n` args=`i64` |

---

## String / Byte Conversion

**Public surface status**: `str_new`, `itoa`, `str_slice`, `str_replace_char`, `str_starts_with`, `str_find`, `str_trim` are **removed from public surface**.

- `str_new` — removed entirely; use `str(bytes)`
- `itoa` — removed entirely; use `str(n)` (internal helper `str_i64` retained)
- `str_slice`, `str_cat` — function-style builtins removed from public surface; compiler-internal helpers remain for slice and `str + str` syntax lowering
- `str_replace_char`, `str_trim` — removed entirely; write byte scanning in Epic
`str`, `bytes`, and `cstr` remain public. `str` is a retained byte-string source type; it currently shares the `u8[]` runtime layout so explicit `str(bytes)` / `bytes(str)` views are zero-copy.

| Function | sema.py | ast_to_mir.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `str`      | ✓ (sema) | ✓ (mir) | ✓ (parser) | ✓ (codegen) | Formatting/view operation for the retained byte-string type |
| `cstr`     | ✓ (sema) | ✓ (mir) | ✗ | ✗ | String to NUL-terminated opaque `u64` address for extern calls |
| `bytes`    | ✓ (sema) | ✓ (mir) | ✓ (parser) | ✓ (codegen) | String → `u8[]` |
| `str_new`  | 🚫 Public surface removed; `str(bytes)` is the recommended path |
| `itoa`     | 🚫 Public surface removed; `str(n)` is the recommended path |
| `str_slice` | ✓ (ln 452) | ✓ (auto handled) | ✓ (ln 320) | ✓ (ln 940) | 🚫 Public surface removed; internal helper only |
| `str_replace_char` | 🚫 Removed entirely | 🚫 Removed entirely | 🚫 Removed entirely | 🚫 Removed entirely | Write byte scanning in Epic |
| `str_starts_with` | ✓ (ln 455) | ✓ (auto handled) | ✓ (ln 326) | ✓ (ln 960) | 🚫 Public surface removed |
| `str_find` | ✓ (ln 455) | ✓ (auto handled) | ✓ (ln 329) | ✓ (ln 969) | 🚫 Public surface removed |
| `str_trim` | 🚫 Removed entirely | 🚫 Removed entirely | 🚫 Removed entirely | 🚫 Removed entirely | Write byte scanning in Epic |

---

## Array

| Function | sema.py | ast_to_mir.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `len`    | ✓ (ln 482) | ✓ (auto handled) | ✓ (ln 299) | ✓ (ln 1011) | `str` and `array` |
| `cap`    | ✓ (ln 488) | ✓ (auto handled) | ✓ (ln 302) | ✓ (ln 1023) | `array` only |
| `xs.push(x)` | ✓ | ✓ | ✓ | ✓ | Array append dot call; old `push(xs,x)` removed |
| `xs.pop()` | ✓ | ✓ | ✓ | ✓ | Delete and return last array element; empty array panics; old `pop(xs)` removed |
| `dst.extend(src)` | ✓ | ✓ | ✓ | ✓ | Same-element array dot call; old `extend(dst,src)` removed |

---

## Type Conversion (constructors)

`str(x)` public surface is intentionally narrow: `str`, integer types, `bool`, and `u8[]` only. `str(u8[])` is a zero-copy byte-slice view, not UTF-8 validation or allocation. Struct and non-`u8[]` array repr is not supported, and f-string interpolation follows the same rule.

These are all in `bootstrap/sema.py` lines 613–629, `src/codegen.ep`.

| Function | sema.py | ast_to_mir.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `i64`  | ✓ (ln 613) | ✗ delegated | ✗ | ✓ (ln 869) | |
| `u64`  | ✓ (ln 615) | ✗ delegated | ✗ | ✓ (ln 869) | |
| `i32`  | ✓ | ✓ | ✓ | historical | Signed 32-bit semantics; canonical sign-extended 8-byte slot |
| `u32`  | ✓ | ✓ | ✓ | historical | Unsigned 32-bit semantics; canonical zero-extended 8-byte slot |

| `u8`   | ✓ (ln 623) | ✗ delegated | ✗ | ✓ (ln 886) | |
| `bool` | ✓ (ln 430, 625) | ✗ delegated | ✗ | ✓ (ln 876) | |
| `void` | ✓ (ln 627) | ✗ delegated | ✗ | ✗ | Unit type; not bindable as local/parameter/container element |

`i32` and `u32` are implemented in both the Python and self-hosted MIR paths. Arithmetic and casts re-normalize to 32 bits. `i8` has been removed from public surface; `u8` is Epic's only byte type.

---

## File I/O

| Function | sema.py | ast_to_mir.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `read_file`  | ✓ (ln 439) | ✓ (ln 654) | ✗ | ✓ (ln 1035) | Returns `u8[]` |
| `write_file` | ✓ (ln 442) | ✓ (ln 664) | ✗ | ✓ (ln 1043) | Returns `i64` |

---

## Pseudo-builtins / Globals

| Name | Handled by | Notes |
|------|-----------|-------|
| `argv` | `sema.py` ln 148 (`self.locals`), `codegen.ep` ln 267, 280 | Implicit global `str[]`, not a function. Special-cased in codegen. |

---

## Source extern declarations

Syntax:

```epic
extern "kernel32.dll" fun Sleep(milliseconds: u32): void
```

The public ABI types are `i32`, `u32`, `i64`, `u64`, plus `void` returns. Foreign pointers and handles are represented as opaque `u64` values; `cstr(str)` returns `u64`. The compiler lowers source imports to self-describing symbols of the form `__ep_import$<dll>$<symbol>`, and the built-in linker groups them by DLL without a function whitelist. `os.*` is removed.

---

## Obsolete / Unimplemented

| Function | Status | Evidence |
|----------|--------|----------|
| `puti` | **Removed from docs examples.** No implementation exists or existed — was a legacy concept. | |
| `putstr` | **Removed from public builtin surface.** Replaced by `print(s)`. | |
| `putc` | **Removed from public builtin surface.** Replaced by `print(str(new u8[]{u8(c)}))` for raw byte output. The old backend-private `__epx_putc` label and `_putc_buf` data have been removed. | |

---

## Backend Private Helpers

Backend private helpers are not public Epic builtins. They are implementation
symbols used by the Python backend.

### MIR-implemented private helpers

| helper | purpose |
|---|---|
| `__ep_str_from_bool` | convert `bool` to a static runtime string |
| `__ep_str_eq` | compare two strings for equality |
| `__ep_runtime_panic` | print runtime panic text and exit with status 1 |
| `__ep_str_cat` | concatenate two strings |
| `__ep_str_slice` | copy a half-open string slice |
| `__ep_slice_u8_alloc` | allocate initialized-capacity byte array |
| `__ep_slice_u8_alloc` | allocate empty byte array with capacity |
| `__ep_slice_u8_get` | bounds-checked byte array read |
| `__ep_slice_u8_set` | bounds-checked byte array write |
| `__ep_slice_u8_push` | append one byte to a byte array |
| `__ep_slice_u8_pop` / `__ep_slice_i64_pop` / `__ep_slice_ptr_pop` | remove and return last array element |
| `__ep_slice_u8_slice` | copy a half-open byte-array slice |
| `__ep_slice_u8_extend` / `__ep_slice_i64_extend` / `__ep_slice_ptr_extend` | append one array into another |

Python and self-hosted compilers lower `bytes(str)` and `str(u8[])` as identity casts, not runtime calls. They load the committed bundle at `runtime/mir/helpers.mir`, then prune unreachable MIR functions from the final program. The prune roots are `main` and MIR/Epic functions called directly by hand-written x64 runtime (`__ep_str_from_i64`, `__ep_slice_u8_alloc`). The committed bundle order is authoritative.

> `__ep_str_slice`, `__ep_str_cat`
> in the list above are **internal helpers** — they remain for lowering `s[start:end]`, `+`, `==`, and `!=`
> but are no longer callable by user code as public builtins.

### x64-backed private helpers

Hand-written x64 helpers are emitted from `bootstrap/x64_runtime.py`. MIR-visible semantic helpers such as `__ep_cstr`, `__ep_read_file`, `__ep_write_file`, `__ep_print_str`, and `__ep_print_newline` own their implementation labels directly. Only backend-private primitives such as `__epx_alloc` and `__epx_argv_init` retain the `__epx_*` prefix. Slice helpers are MIR helpers, not x64-backed helpers.

These should be treated as backend implementation details, not language builtins.

---

## Known Mismatches

### `src/parser.ep` reserved list is incomplete

The self-hosted parser (`src/parser.ep` ln 299–337) reserves these names to prevent
user code from redefining them:

```
len cap bytes str str_new str_slice
str_starts_with str_find push extend
```

**But does NOT reserve:**

```
print println exit read_file write_file
itoa cstr i64 u64 i32 u32 u8 bool
```

This means a user function named `print()` or `exit()` would parse successfully
but then fail in codegen — or worse, silently shadow the builtin. The reserved
list should be kept in sync with the actual builtin set.
