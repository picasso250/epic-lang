# Epic v1 implementation notes

This document describes the v1 implementation delta from `../v0`. It is not the language spec. User-visible v1 language changes live in `design.md`.

Unless this file says otherwise, v1 inherits the v0 compiler model: whole-program source merging, Windows x64 NASM output, Win32 runtime helpers, 4 register arguments, fixed 8-byte user struct slots, `os.*` special calls, `link.py`, and the basic example-driven acceptance suite.

## Compiler entry

The v1 directory no longer keeps the Python compiler prototype or `epic.py` driver. Build the v0 fixed point compiler from `../v0`, copy `epic-epic-epic.exe` to root `build\v0.exe`, then use `..\build\v0.exe` as the previous compiler anchor for v1.

The current compiler sources are:

```text
epic.ep
lexer.ep
parser.ep
codegen_support.ep
codegen.ep
```

Test scripts invoke the previous compiler to build `build/epic/epic.ep.exe`, then use that executable to compile examples.

## Codegen split

The Epic implementation of codegen is split across `codegen_support.ep` and `codegen.ep`.

`codegen_support.ep` owns shared codegen data structures, low-level assembly output helpers, runtime helper emission, and type helpers.

`codegen.ep` owns AST collection, layout, expression emission, statement emission, function emission, and program emission.

This split is implemented within the existing whole-program multi-file compilation model. It is not a module system.

## Type lowering delta

v1 adds `bool`, `u8`, and `u64`, while keeping `i8` only as a bootstrap-era compatibility detail where old v0-shaped sources still require it.

| User type | Internal type |
| --- | --- |
| `bool` | `bool` |
| `u8` | `u8` |
| `u64` | `u64` |
| `i64` | `i64` |
| `str` | `&str` |
| `Token` | `&Token` |
| `u8[]` | `&_arr_u8` |
| `Token[]` | `&_arr_Token` |

The built-in `str` layout changes from `&i8` bytes to `&u8` bytes:

```text
str = {
    data: &u8,
    len: i64,
}
```

Dynamic array layout remains:

```text
_arr_T = {
    data,
    len: i64,
    cap: i64,
}
```

Primitive arrays store primitive values. Struct and `str` arrays store references.

`u8` and `bool` struct fields load/store one byte inside their inherited 8-byte user struct slot.

## Parser delta

The v1 parser adds:

- optional `let` type annotations
- `bool`, `u8`, and `u64` type recognition
- `true` and `false` literals
- user-level bitwise operators `~`, `&`, `|`, `^`
- shift operators `<<`, `>>`, and `>>>`
- compound assignment through a unified `AssignOp` node
- expression postfixes for checked indexing and copy slices
- `for i in start:end`, lowered to existing `let` and `while` nodes with hidden start/end locals

Assignment targets support variables, field chains, and subscripts as in v0. Compound assignment uses the same assignable target shapes.

## Codegen delta

v1 codegen enforces bool-only conditions for `if` and `while`.

Integer arithmetic emits runtime checks for overflow and division by zero. Bit operations and shifts operate on fixed-width bit patterns and are not overflow-checked.

Subscript emission performs bounds checks for strings and arrays. String indexing returns `u8`. Slice emission calls `_str_slice` for strings and emits array copy loops directly.

Range loops reuse the inherited while-loop machinery. `continue` in a lowered range loop jumps to a generated increment label before the next condition check.

Compound assignment evaluates the left-hand side once, computes the operation, and writes back to the same target. Boolean compound assignment is rejected.

## Runtime helper delta

v1 appends the inherited v0 helpers plus new or changed helpers:

```text
runtime/bytes.asm
runtime/str_cat.asm
runtime/str_slice.asm
runtime/str_replace_char.asm
runtime/str_starts_with.asm
runtime/str_find.asm
runtime/str_trim.asm
runtime/extend_i8.asm
runtime/read_file.asm
runtime/write_file.asm
```

The important v1 runtime changes are:

- `_read_file` returns `u8[]` instead of `str`
- `_write_file` writes a `u8[]` payload instead of `str`
- `_str_starts_with`, `_str_find`, and `_str_trim` implement byte-oriented string helpers
- `_str_slice` is used by slice syntax for strings
- `_bytes` supports `bytes(str)`
- `_str_alloc` supports `str(u8[])`
- `_extend_i8` remains the fast byte-array extension helper

## Builtin lowering delta

Current v1 builtins added or changed relative to v0:

| Builtin | Implementation note |
| --- | --- |
| `read_file` | calls `_read_file` and returns `u8[]` |
| `write_file` | writes a `u8[]` payload through `_write_file` |
| `str` | converts `u8[]` to `str` through `_str_alloc` |
| `bytes` | calls `_bytes` runtime helper |
| `str_starts_with` | calls `_str_starts_with` runtime helper |
| `str_find` | calls `_str_find` runtime helper |
| `str_trim` | calls `_str_trim` runtime helper |
| `len` / `cap` | emitted directly for strings and dynamic arrays |
| `extend` | calls `_extend_i8` for byte arrays; emits copy loops for other dynamic arrays |
| slice syntax | calls `_str_slice` for strings and emits array copy loops directly |

Little-endian load/store helpers are not compiler builtins. `link.ep` and examples implement them as ordinary Epic functions using `u8[]`, `u64`, checked indexing, and bit operations.

## Linker written in Epic

v1 includes `link.ep`, an Epic MVP linker for the same current single-object PE64 path covered by `link.py`.

`link.ep` uses v1 source syntax and v1 byte-buffer builtins. It is compiled with the current v1 compiler, not with the v0 anchor directly.

The compiler driver still defaults to `link.py` in v1. `link.ep` is tested separately as proof that v1 can do binary parsing and patching in Epic.

## Toolchain

The inherited toolchain remains:

- `tools/nasm.exe`
- `tools/lld-link.exe`
- `link.py`
- Windows SDK `kernel32.lib` and `user32.lib`

`lld-link` remains available through `--linker lld-link`.

## Status and acceptance

Primary runtime acceptance:

```text
python runtests.py
```

Current known result:

```text
54 passed, 0 failed
```

Epic linker MVP acceptance:

```text
python test_link_ep.py
```

Current known result:

```text
54 passed, 0 failed
```

v0-only historical bootstrap checks live in the Python implementation path. On v1, the default acceptance path uses the previous Epic compiler anchor.
