# Builtin Inventory

Current snapshot of Epic's public builtins and the active implementation paths.
This document describes the current compiler, not removed NASM-era code.

## Implementation ownership

| Concern | Python reference compiler | Self-hosted compiler |
|---|---|---|
| Reserved public names | `bootstrap/epic_builtins.py`, consumed by `bootstrap/sema.py` | `sema_is_reserved_func` in `src/sema.ep` |
| Type checking | `bootstrap/sema.py` | `src/sema.ep` |
| MIR lowering | `bootstrap/ast_to_mir.py` | `src/ast_to_mir.ep` |
| Runtime definitions | `runtime/mir/helpers.mir`, `runtime/*.ep`, `bootstrap/mir_runtime_helpers.py` | the same runtime sources through `src/mir_runtime.ep` |

The parser does not own builtin semantics or builtin-name reservation. Both compiler
implementations parse ordinary calls first and resolve builtin behavior during sema and
MIR lowering.

`bootstrap/epic_builtins.py` is the central Python-side name inventory. It is already
used by Python sema to reject builtin and pseudo-builtin redefinitions; it does not by
itself implement typing or lowering.

## Public function-call surface

| Call | Type / behavior | Lowering intent |
|---|---|---|
| `print(text)` | `str -> void`; writes text without adding a newline | `__ep_print_str` |
| `println()` | `() -> void`; writes one newline | `__ep_print_newline` |
| `println(text)` | `str -> void`; writes text and one newline | `__ep_print_str`, then `__ep_print_newline` |
| `exit(code)` | `i64 -> void`; terminates the process | `ExitProcess` |
| `str(value)` | accepts `str`, integer types, `bool`, or `u8[]`; returns `str` | identity view for `str`/`u8[]`, runtime formatting for scalar values |
| `bytes(text)` | `str -> u8[]` | zero-copy view with the shared byte-slice layout |
| `cstr(text)` | `str -> u64` | validates/creates a NUL-terminated buffer through `__ep_cstr` |
| `len(value)` | `str` or any array -> `i64` | reads the public logical length |
| `cap(array)` | any array -> `i64` | reads array capacity |
| `i64(x)` | integer -> `i64` | integer conversion |
| `u64(x)` | integer -> `u64` | integer conversion |
| `i32(x)` | integer -> `i32` | truncates to 32 bits, then keeps canonical sign extension |
| `u32(x)` | integer -> `u32` | truncates to 32 bits, then keeps canonical zero extension |
| `u8(x)` | integer -> `u8` | truncates to 8 bits |
| `bool(x)` | integer or `bool` -> `bool` | zero/nonzero conversion or identity |
| `read_file(path)` | `str -> u8[]` | `__ep_read_file` |
| `write_file(path, data)` | `(str, u8[]) -> i64` | `__ep_write_file` |

`str(u8[])` and `bytes(str)` are representation-preserving views. They do not perform
UTF-8 validation and do not allocate merely to change the static source type.

## Public array methods

| Method | Type / behavior |
|---|---|
| `xs.push(value)` | appends one value; returns `void` |
| `xs.pop()` | removes and returns the final value; an empty array panics |
| `dst.extend(src)` | appends an array with the same element type; returns `void` |

The old function-call forms `push(xs, value)`, `pop(xs)`, and `extend(dst, src)` are
removed and are explicitly rejected by sema.

## Pseudo-builtins

| Name | Type / behavior |
|---|---|
| `argv` | implicit local `str[]` available in every function; startup initializes it from the process command line |

`argv` is not a callable function and cannot be redefined as a function or extern in the
Python reference compiler.

## Removed public surface

The following historical function-style APIs are not part of the current language:

- `str_new`
- `itoa` (use `str(n)`)
- `str_slice` (use `s[start:end]`)
- `str_cat` (use `left + right`)
- `str_replace_char`
- `str_starts_with`
- `str_find`
- `str_trim`
- function-style `push`, `pop`, and `extend`

Private runtime helpers may retain similar names because syntax lowering still needs
string concatenation, slicing, comparison, or array operations. Their existence does
not make them user-callable builtins.

## Source extern declarations

Syntax:

```epic
extern "kernel32.dll" fun Sleep(milliseconds: u32): void
```

The public extern ABI accepts `i32`, `u32`, `i64`, and `u64` parameters, plus those
integer types or `void` as returns. Foreign pointers and handles are represented as
opaque `u64` values; `cstr(str)` supplies a NUL-terminated address for C APIs.

The compiler lowers source imports to self-describing symbols of the form
`__ep_import$<dll>$<symbol>`. The linker groups them by DLL and does not use a function
whitelist. The removed `os.*` pseudo-namespace is not part of the current interface.

## Private MIR/runtime helpers

Backend-private helpers are ordinary MIR functions, not language builtins. Current
categories include:

- allocation and startup: `__ep_alloc`, `__ep_runtime_start`;
- string output/conversion: `__ep_print_str`, `__ep_print_newline`, `__ep_cstr`, scalar-to-string helpers;
- string operations used by syntax: equality, concatenation, and slicing;
- file operations: `__ep_read_file`, `__ep_write_file`;
- array allocation, checked access, mutation, slicing, `push`, `pop`, and `extend` for supported element representations;
- panic and bounds/null failure paths.

Python and self-hosted compilers load the committed MIR helper bundle, merge helpers
compiled from `runtime/*.ep`, and prune unreachable functions. Reachability begins at
`main`; startup and runtime dependencies are normal MIR calls. The x64 backend lowers
this MIR and imports only the WinAPI symbols that remain reachable.

## Known reservation mismatches

The callable behavior is aligned between Python and self-hosted sema, but declaration
reservation is not yet represented by one shared source of truth:

1. Python sema reserves the numeric and boolean constructor names `i64`, `u64`, `i32`,
   `u32`, `u8`, and `bool` through `BUILTIN_FUNCTIONS`. `src/sema.ep` currently omits
   those names from `sema_is_reserved_func`. A self-hosted declaration may therefore
   pass the declaration check even though calls with that name are still interpreted as
   builtin conversions.
2. `pop` is not in `BUILTIN_FUNCTIONS` and is also absent from
   `sema_is_reserved_func`, while function-style `pop(...)` is hard-rejected before
   ordinary user-function lookup. A user function named `pop` can be declared but
   cannot be called normally.

These are compiler consistency issues, not additional public language features. The
current public surface remains the one documented above.
