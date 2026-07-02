# Builtin Inventory

Current snapshot of functions handled specially by the Epic compiler pipeline
(bootstrap Python reference compiler + self-hosted Epic compiler).

> This document records the **status quo** — no judgment, no removal.
> Four source files define the builtin surface:
> - `bootstrap/sema.py` — type checking (bootstrap path)
> - `bootstrap/mir_codegen.py` — codegen (bootstrap path)
> - `src/parser.ep` — parser (self-hosted path, reserved name list)
> - `src/codegen.ep` — codegen (self-hosted path)

---

## I/O / Process

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `print`  | ✓ (ln 401) | ✓ (ln 588) | ✗ | ✓ (ln 831) | Print with trailing newline — `println` handled same line |
| `println` | ✓ (ln 401) | ✓ (ln 580) | ✗ | ✓ (ln 831) | |
| `putstr` | ✓ (ln 407) | ✓ (ln 595) | ✗ | ✓ (ln 807) | Low-level string output, older sibling of `print` |
| `putc`   | ✓ (ln 410) | ✓ (ln 599) | ✗ | ✓ (ln 792) | Low-level character output |
| `exit`   | ✓ (ln 414) | ✓ (ln 603) | ✗ | ✗ | Terminate process; `n` args=`i64` |
| `system` | ✓ (ln 465) | ✓ (ln 685) | ✗ | ✓ (ln 906) | Shell command, returns `i64` |

---

## String / Byte Conversion

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `str`      | ✓ (ln 417) | ✓ (ln 607) | ✓ (ln 314) | ✓ (ln 921) | Multi-type to string |
| `cstr`     | ✓ (ln 423) | ✓ (ln 632) | ✗ | ✗ | String to C-style (null-terminated); WinAPI interop |
| `itoa`     | ✓ (ln 461) | ✓ (ln 642) | ✗ | ✓ (ln 863) | Integer to ASCII string, legacy |
| `bytes`    | ✓ (ln 436) | ✓ (ln 650) | ✓ (ln 311) | ✓ (ln 934) | String → `u8[]` |
| `str_new`  | ✓ (ln 445) | ✓ (ln 628) | ✓ (ln 317) | ✓ (ln 914) | `str_new(ptr, len)` — raw pointer slice |
| `str_slice` | ✓ (ln 452) | ✓ (auto handled) | ✓ (ln 320) | ✓ (ln 940) | `str_slice(s, start, end)` |
| `str_replace_char` | ✓ (ln 452) | ✓ (auto handled) | ✓ (ln 323) | ✓ (ln 950) | |
| `str_starts_with` | ✓ (ln 455) | ✓ (auto handled) | ✓ (ln 326) | ✓ (ln 960) | |
| `str_find` | ✓ (ln 455) | ✓ (auto handled) | ✓ (ln 329) | ✓ (ln 969) | |
| `str_trim` | ✓ (ln 458) | ✓ (ln 677) | ✓ (ln 332) | ✓ (ln 978) | |

---

## Array

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `len`    | ✓ (ln 482) | ✓ (auto handled) | ✓ (ln 299) | ✓ (ln 1011) | `str` and `array` |
| `cap`    | ✓ (ln 488) | ✓ (auto handled) | ✓ (ln 302) | ✓ (ln 1023) | `array` only |
| `push`   | ✓ (ln 468) | ✓ (ln 700) | ✓ (ln 305) | ✓ (ln 1056) | Array append |
| `extend` | ✓ (ln 475) | ✓ (ln 707) | ✓ (ln 308) | ✓ (ln 1134) | Array extend |

---

## Type Conversion (constructors)

These are all in `bootstrap/sema.py` lines 613–629, `src/codegen.ep`.

| Function | sema.py | mir_codegen.py | parser.ep reserved | codegen.ep | Notes |
|----------|---------|----------------|---------------------|------------|-------|
| `i64`  | ✓ (ln 613) | ✗ delegated | ✗ | ✓ (ln 869) | |
| `u64`  | ✓ (ln 615) | ✗ delegated | ✗ | ✓ (ln 869) | |
| `i32`  | ✓ (ln 617) | ✗ delegated | ✗ | ✗ | In bootstrap sema only |
| `u32`  | ✓ (ln 619) | ✗ delegated | ✗ | ✗ | In bootstrap sema only |
| `i8`   | ✓ (ln 621) | ✗ delegated | ✗ | ✗ | In bootstrap sema only |
| `u8`   | ✓ (ln 623) | ✗ delegated | ✗ | ✓ (ln 886) | |
| `bool` | ✓ (ln 430, 625) | ✗ delegated | ✗ | ✓ (ln 876) | |
| `void` | ✓ (ln 627) | ✗ delegated | ✗ | ✗ | Type-level only |

Note: `i32`, `u32`, `i8` are handled in bootstrap `sema.py` but have no explicit
handler in `src/codegen.ep` — the self-hosted codegen may delegate them to the
general integer cast path. Worth auditing separately.

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
| `puti` | **Not implemented** — mentioned only in `docs/design.md` and `docs/mir-design.md` (historical). No handler in any source file. | |

---

## Known Mismatches

### `src/parser.ep` reserved list is incomplete

The self-hosted parser (`src/parser.ep` ln 299–337) reserves these names to prevent
user code from redefining them:

```
len cap push extend bytes str str_new str_slice
str_replace_char str_starts_with str_find str_trim map_has
```

**But does NOT reserve:**

```
print println putstr putc exit system read_file write_file
itoa cstr i64 u64 i32 u32 u8 bool
```

This means a user function named `print()` or `exit()` would parse successfully
but then fail in codegen — or worse, silently shadow the builtin. The reserved
list should be kept in sync with the actual builtin set.

### `i32`, `u32`, `i8` in bootstrap sema but not in self-hosted codegen

These are handled in `bootstrap/sema.py` lines 617–621 but have no dedicated
handler in `src/codegen.ep`. They may work through a general integer cast path,
or may be broken in the self-hosted path. Needs verification.
