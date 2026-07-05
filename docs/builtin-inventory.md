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
> - `bootstrap/mir_codegen.py` — typed AST to MIR
>
> `src/parser.ep` still has a reserved-name list. The old NASM-oriented `src/codegen_support.ep` / `src/codegen.ep` path has been deleted; any remaining `codegen.ep` column below is historical and should be removed in a later inventory refresh.

---

## I/O / Process

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `print`  | ✓ (ln 401) | ✓ (ln 588) | ✗ | ✓ (ln 831) | Print with trailing newline — `println` handled same line |
| `println` | ✓ (ln 401) | ✓ (ln 580) | ✗ | ✓ (ln 831) | |
| `exit`   | ✓ (ln 414) | ✓ (ln 603) | ✗ | ✗ | Terminate process; `n` args=`i64` |
| `system` | ✓ (ln 465) | ✓ (ln 685) | ✗ | ✓ (ln 906) | Shell command, returns `i64` |

---

## String / Byte Conversion

**Public surface status**: `str_new`, `itoa`, `str_slice`, `str_replace_char`, `str_starts_with`, `str_find`, `str_trim` are **removed from public surface**.

- `str_new` — removed entirely; use `str(bytes)`
- `itoa` — removed entirely; use `str(n)` (internal helper `str_i64` retained)
- `str_slice`, `str_cat` — removed from public surface, but retained as compiler-internal helpers where syntax lowering still needs them
- `str_replace_char`, `str_trim` — removed entirely; write byte scanning in Epic
`str`, `bytes`, and `cstr` remain public during the alias transition, but `str` is now documented as a temporary `u8[]`-layout view rather than the future UTF-8 string design.

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `str`      | ✓ (sema) | ✓ (mir) | ✓ (parser) | ✓ (codegen) | Transitional formatting/view operation; `u8[]` is the text truth |
| `cstr`     | ✓ (sema) | ✓ (mir) | ✗ | ✗ | String to C-style (null-terminated); WinAPI interop |
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

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `len`    | ✓ (ln 482) | ✓ (auto handled) | ✓ (ln 299) | ✓ (ln 1011) | `str` and `array` |
| `cap`    | ✓ (ln 488) | ✓ (auto handled) | ✓ (ln 302) | ✓ (ln 1023) | `array` only |
| `push`   | ✓ (ln 468) | ✓ (ln 700) | ✓ (ln 305) | ✓ (ln 1056) | Array append |
| `extend` | ✓ (ln 475) | ✓ (ln 707) | ✓ (ln 308) | ✓ (ln 1134) | u8[] only; use for + push for other types |

---

## Type Conversion (constructors)

`str(x)` public surface is intentionally narrow: `str`, integer types, `bool`, and `u8[]` only. `str(u8[])` is a zero-copy byte-slice view, not UTF-8 validation or allocation. Struct, map, and non-`u8[]` array repr is not supported, and f-string interpolation follows the same rule.

These are all in `bootstrap/sema.py` lines 613–629, `src/codegen.ep`.

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `i64`  | ✓ (ln 613) | ✗ delegated | ✗ | ✓ (ln 869) | |
| `u64`  | ✓ (ln 615) | ✗ delegated | ✗ | ✓ (ln 869) | |
| `i32`  | ✓ (ln 617) | ✗ delegated | ✗ | ✗ | In bootstrap sema only |
| `u32`  | ✓ (ln 619) | ✗ delegated | ✗ | ✗ | In bootstrap sema only |

| `u8`   | ✓ (ln 623) | ✗ delegated | ✗ | ✓ (ln 886) | |
| `bool` | ✓ (ln 430, 625) | ✗ delegated | ✗ | ✓ (ln 876) | |
| `void` | ✓ (ln 627) | ✗ delegated | ✗ | ✗ | Type-level only |

Note: `i32`, `u32` are handled in bootstrap `sema.py` but have no explicit
handler in `src/codegen.ep`. `i8` has been removed from public surface;
u8 is Epic's only byte type.

---

## File I/O

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `read_file`  | ✓ (ln 439) | ✓ (ln 654) | ✗ | ✓ (ln 1035) | Returns `u8[]` |
| `write_file` | ✓ (ln 442) | ✓ (ln 664) | ✗ | ✓ (ln 1043) | Returns `i64` |

---

## Map

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `map_has` | ✓ (ln 494) | ✓ (ln 707) | ✓ (ln 335) | ✓ (ln 986) | Only `map[str]i64` path |

---

## Pseudo-builtins / Globals

| Name | Handled by | Notes |
|------|-----------|-------|
| `argv` | `sema.py` ln 148 (`self.locals`), `codegen.ep` ln 267, 280 | Implicit global `str[]`, not a function. Special-cased in codegen. |

---

## OS-namespaced calls

Syntax: `os.<dll>.<Function>(<args>)`

Only `kernel32` and `user32` are supported (`bootstrap/sema.py` ln 506).

Registered signatures (`bootstrap/sema.py` ln 75–95):

```
kernel32.ExitProcess(i64) -> void
kernel32.Sleep(i64) -> void
kernel32.GetTickCount64() -> i64
kernel32.lstrlenA(i64) -> i64
kernel32.lstrcmpA(i64, i64) -> i64
kernel32.GetStdHandle(i64) -> i64
kernel32.GetProcessHeap() -> i64
kernel32.HeapAlloc(i64, i64, i64) -> i64
kernel32.CreateFileA(i64, i64, i64, i64, i64, i64, i64) -> i64
kernel32.GetFileSize(i64, i64) -> i64
kernel32.ReadFile(i64, i64, i64, i64, i64) -> i64
kernel32.WriteFile(i64, i64, i64, i64, i64) -> i64
kernel32.CloseHandle(i64) -> i64
kernel32.CreateProcessA() -> i64
kernel32.WaitForSingleObject(i64, i64) -> i64
kernel32.GetExitCodeProcess(i64, i64) -> i64
kernel32.GetCommandLineA() -> i64
user32.MessageBoxA(i64, i64, i64, i64) -> i64
```

The self-hosted `src/codegen.ep` maps these to MASM `invoke` / `call` stubs.

---

## Obsolete / Unimplemented

| Function | Status | Evidence |
|----------|--------|----------|
| `puti` | **Removed from docs examples.** No implementation exists or existed — was a legacy concept. | |
| `putstr` | **Removed from public builtin surface.** Replaced by `print(s)`. | |
| `putc` | **Removed from public builtin surface.** Replaced by `print(str(new u8[]{u8(c)}))` for raw byte output. Backend private label `__epx_putc` still exists as an x64-private implementation detail (direct WriteFile with `_putc_buf`), not referenced by any MIR call. | |

---

## Backend Private Helpers

Backend private helpers are not public Epic builtins. They are implementation
symbols used by the Python backend.

### MIR-implemented private helpers

| helper | purpose |
|---|---|
| `__ep_slice_u8_from_str` | convert `str` to `_slice_u8` |
| `__ep_str_from_slice_u8` | view/convert `_slice_u8` as `str` |
| `__ep_str_from_bool` | convert `bool` to a static runtime string |
| `__ep_str_eq` | compare two strings for equality |
| `__ep_str_cat` | concatenate two strings |
| `__ep_str_slice` | copy a half-open string slice |
| `__ep_slice_u8_alloc` | allocate initialized-capacity byte array |
| `__ep_slice_u8_alloc` | allocate empty byte array with capacity |
| `__ep_slice_u8_get` | bounds-checked byte array read |
| `__ep_slice_u8_set` | bounds-checked byte array write |
| `__ep_slice_u8_push` | append one byte to a byte array |
| `__ep_slice_u8_slice` | copy a half-open byte-array slice |
| `__ep_slice_u8_extend` | append one byte array into another |

These are currently injected unconditionally by `bootstrap/mir_runtime_helpers.py`.

> `__ep_str_slice`, `__ep_str_cat`
> in the list above are **internal helpers** — they remain for lowering `s[start:end]`, `==`, `!=`
> but are no longer callable by user code as public builtins.

### x64-backed private helpers

Most other private helpers are still emitted as x64 helper bodies from
`bootstrap/mir_lower.py`. This includes `__ep_str_from_i64`, `__ep_str_from_u64`, `__ep_map_str_i64_*`,
`__ep_read_file`, `__ep_write_file`, `__ep_system_cmd`, `__epx_argv_init`,
`__ep_print_str`, `__ep_print_newline`, and `__epx_putc`.

These should be treated as backend implementation details, not language builtins.

---

## Known Mismatches

### `src/parser.ep` reserved list is incomplete

The self-hosted parser (`src/parser.ep` ln 299–337) reserves these names to prevent
user code from redefining them:

```
len cap push extend bytes str str_new str_slice
str_starts_with str_find map_has
```

**But does NOT reserve:**

```
print println exit system read_file write_file
itoa cstr i64 u64 i32 u32 u8 bool
```

This means a user function named `print()` or `exit()` would parse successfully
but then fail in codegen — or worse, silently shadow the builtin. The reserved
list should be kept in sync with the actual builtin set.

### `i32`, `u32` in bootstrap sema but not in self-hosted codegen

These are handled in `bootstrap/sema.py` but have no dedicated
handler in `src/codegen.ep`. They may work through a general integer cast path,
or may be broken in the self-hosted path. Needs verification.

Note: `i8` was previously listed here but has been removed from the public
surface. `u8` is Epic's only byte type.
