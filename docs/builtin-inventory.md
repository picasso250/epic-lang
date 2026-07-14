# Builtin Inventory

Current snapshot of Epic's public builtins and the active implementation paths.
This document describes the current compiler, not removed NASM-era code.

## Implementation ownership

| Concern | Active implementation |
|---|---|
| Reserved public names | `sema_is_reserved_func` in `src/sema.ep` |
| Type checking | `src/sema.ep` |
| MIR lowering | `src/ast_to_mir.ep` |
| Runtime definitions | MIR bundles plus Epic runtime sources, injected through `src/mir_runtime.ep` |

The parser does not own builtin semantics or builtin-name reservation. Calls are parsed
normally and builtin behavior is resolved during sema and MIR lowering.

## Public function-call surface

| Call | Type / behavior | Lowering intent |
|---|---|---|
| `print(text)` | `str -> void`; writes text without adding a newline | `__ep_print_str` |
| `println()` | `() -> void`; writes one newline | `__ep_print_newline` |
| `println(text)` | `str -> void`; writes text and one newline | `__ep_print_str`, then `__ep_print_newline` |
| `exit(code)` | `i64 -> void`; terminates the process | `ExitProcess` |
| `str(value)` | accepts `str`, integer types, `bool`, or `u8[]`; returns `str` | identity for `str`, NUL-normalizing same-header conversion for `u8[]`, runtime formatting for scalar values |
| `bytes(text)` | `str -> u8[]` | zero-copy view with the shared byte-slice layout |
| `cptr(value)` | accepts `str`, a bool/integer/ptr array, or a non-empty FFI-safe user struct; returns `ptr` | direct data/payload pointer lowering with no runtime checks |
| `cstr(text)` | `str -> ptr` | deprecated alias of `cptr(text)`; no NUL validation or helper call |
| `len(value)` | `str` or any array -> `i64` | reads the public logical length |
| `i64(x)` | integer or `ptr` -> `i64` | integer conversion or pointer bit-pattern extraction |
| `u64(x)` | integer or `ptr` -> `u64` | integer conversion or pointer bit-pattern extraction |
| `ptr(x)` | `i64`, `u64`, or `ptr` -> `ptr` | opaque pointer bit-pattern conversion |
| `i32(x)` | integer -> `i32` | truncates to 32 bits, then keeps canonical sign extension |
| `u32(x)` | integer -> `u32` | truncates to 32 bits, then keeps canonical zero extension |
| `u8(x)` | integer -> `u8` | truncates to 8 bits |
| `bool(x)` | integer or `bool` -> `bool` | zero/nonzero conversion or identity |
| `read_file(path)` | `str -> u8[]` | `__ep_read_file` |
| `write_file(path, data)` | `(str, u8[]) -> i64` | `__ep_write_file` |

`bytes(str)` is a representation-preserving zero-copy view. `str(u8[])` keeps the same
header and logical bytes, but invokes `__ep_str_from_bytes` to reserve a trailing slot and
write NUL; it may therefore replace and copy the backing allocation. Neither conversion
performs UTF-8 validation.

## Public array methods

| Method | Type / behavior |
|---|---|
| `xs.push(value)` | appends one value; returns `void` |
| `xs.pop()` | removes and returns the final value; an empty array panics |
| `dst.extend(src)` | appends an array with the same element type; returns `void` |

These names are not reserved globally. `push(...)`, `pop(...)`, and `extend(...)` are
ordinary user-function or extern calls when written without a receiver; only the dot
forms above receive array-method semantics.

## Pseudo-builtins

| Name | Type / behavior |
|---|---|
| `argv` | implicit local `str[]` available in every function; startup initializes it from the process command line |

`argv` is not a callable function and cannot be redefined as a function or extern.

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
- the historical global builtin forms of `push`, `pop`, and `extend` (the names may still be used by ordinary user functions or externs)
- `cap(array)`; capacity and growth strategy are runtime-private, and `cap` may be used as an ordinary user-function or extern name

Private runtime helpers may retain similar names because syntax lowering still needs
string concatenation, slicing, comparison, or array operations. Their existence does
not make them user-callable builtins.

## Source extern declarations

Syntax:

```epic
extern "kernel32.dll" fun Sleep(milliseconds: u32): void
```

The public extern ABI accepts the public integer scalar types and opaque `ptr`, plus
those types or `void` as returns. Foreign pointers, nullable addresses, and handles use
`ptr`. Strings, byte buffers, and FFI-safe struct payloads cross the boundary only through
explicit borrowed pointers from `cptr(...)`; `cptr` itself performs no conversion or NUL validation.

The compiler lowers source imports to self-describing symbols of the form
`__ep_import$<dll>$<symbol>`. The linker groups them by DLL and does not use a function
whitelist. The removed `os.*` pseudo-namespace is not part of the current interface.

## Private MIR/runtime helpers

Backend-private helpers are ordinary MIR functions, not language builtins. Current
categories include:

- allocation, GC, and startup: `__ep_alloc`, collector helpers, `__ep_runtime_start`;
- string output/conversion: `__ep_print_str`, `__ep_print_newline`, scalar-to-string helpers, `__ep_str_from_bytes`, and `__ep_str_copy`; `cptr`/`cstr` themselves require no runtime helper;
- string operations used by syntax: equality, concatenation, and slicing;
- file operations: Epic implementations of `__ep_read_file` and `__ep_write_file` from `runtime/file.ep`;
- array allocation, checked access, mutation, slicing, `push`, `pop`, and `extend` for supported element representations;
- panic and bounds/null failure paths.

`src/runtime_bundle.ep` embeds the committed MIR bundles and the standard Epic runtime
sources (`str` and `file`) into the compiler image. Array and panic helpers live in
`runtime/mir/helpers.ir`. The Epic sources are
merged before the user program and pass through one frontend. Equivalent repeated extern
declarations are deduplicated by canonical DLL/signature; conflicting declarations fail.
Reachability begins at `main`; unused helpers and imports are pruned before x64 lowering.

## Name reservation

Sema reserves names whose call syntax is always interpreted as a
builtin or pseudo-builtin, including `print`, `println`, `exit`, `cptr`, deprecated
`cstr`, conversions such as `i64`/`u8`/`bool`, file I/O, `len`, and `argv`.

Array operations are different: their builtin meaning is selected by receiver syntax.
Therefore `push`, `pop`, `extend`, and the removed builtin name `cap` are intentionally
not reserved as global names. A program may define or import global functions with those
names while continuing to use `xs.push(...)`, `xs.pop()`, and `xs.extend(...)` for arrays.
