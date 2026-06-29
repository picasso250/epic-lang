# Epic v1 implementation notes

This document describes the current compiler implementation. It is not the language spec. User-visible language semantics live in `design.md`.

## Compiler entry

The v1 branch no longer keeps the Python compiler prototype or `epic.py`
driver. Build the v0 fixed point compiler on the `v0` branch, copy
`epic-epic-epic.exe` to `v0.exe`, then use `v0.exe` as the previous compiler
anchor for v1.

The current compiler sources are `epic.ep`, `lexer.ep`, `parser.ep`,
`codegen_support.ep`, and `codegen.ep`. Test scripts invoke the previous
compiler to build `build/epic/epic.ep.exe`, then use that executable to compile
examples.

## Multi-file merge

The Epic compiler supports whole-program source merging.

- More than one input file requires `--main`.
- All structs share one global namespace.
- All functions share one global namespace.
- Duplicate struct names are rejected.
- Duplicate function names are rejected.
- A `main` function in a non-main input file is ignored.
- This is not a module system.

## Toolchain

Current toolchain paths are configured by the Epic compiler/runtime path:

- `tools/nasm.exe`
- `tools/lld-link.exe`
- `link.py`
- Windows SDK `kernel32.lib` and `user32.lib`

`link.py` is the default linker. `lld-link` is available through `--linker lld-link`.
`link.ep` is an Epic MVP linker for the same current single-object PE64 path;
it is tested separately and is not yet the compiler driver's default linker.

## Runtime helpers

The driver appends runtime assembly helpers after emitted program assembly:

```text
runtime/str_alloc.asm
runtime/bytes.asm
runtime/str_cat.asm
runtime/str_slice.asm
runtime/str_replace_char.asm
runtime/str_starts_with.asm
runtime/str_find.asm
runtime/str_trim.asm
runtime/extend_i8.asm
runtime/itoa.asm
runtime/argv.asm
runtime/system.asm
runtime/read_file.asm
runtime/write_file.asm
```

## Type lowering

User-facing types lower to implementation types:

| User type | Internal type |
| --- | --- |
| `i64` | `i64` |
| `u8` | `u8` |
| `u64` | `u64` |
| `bool` | `bool` |
| `str` | `&str` |
| `Token` | `&Token` |
| `i64[]` | `&_arr_i64` |
| `Token[]` | `&_arr_Token` |

User programs do not write pointer types. `&T` and `&&T` are compiler-internal codegen types only.

## Runtime layouts

### String layout

```text
str = {
    data: &u8,
    len: i64,
}
```

String literals are deep-copied into heap storage and include a trailing NUL byte for Win32 interop. `len` excludes the trailing NUL.

### Dynamic array layout

```text
_arr_T = {
    data,
    len: i64,
    cap: i64,
}
```

Primitive arrays store primitive values. Struct and `str` arrays store references.

### Struct layout

User struct fields use fixed 8-byte slots in v1.

- Field offset is `index * 8`.
- Struct size is `field_count * 8`.
- `u8` and `bool` fields load/store one byte inside their 8-byte slot.
- Built-in runtime layouts such as `str` and dynamic arrays keep their explicit layouts.

## Parser notes

- Type names are parsed as identifiers in type context.
- `let` supports optional type annotations.
- Functions may have at most 4 parameters.
- Calls may have at most 4 arguments.
- `os.*` calls are recognized specially.
- General method calls are rejected.
- Assignment targets support variables, field chains, and subscripts.
- Expression postfixes support checked indexing and copy slices for strings and arrays.
- `for i in start..end` is parsed as a lowering to existing `let` and `while`
  nodes with hidden start/end locals.

## Codegen notes

The backend emits NASM x64 assembly for Windows x64.

- The process entry symbol is `_start`.
- Calls follow the Windows x64 ABI.
- User calls support up to 4 register arguments.
- Runtime and Win32 calls are wrapped by helper code where needed.
- Heap allocation uses Win32 heap APIs through runtime/codegen helpers.

The first Epic codegen implementation uses compiler-generated temp locals for expression intermediates.

- Each function reserves 64 hidden `i64` temp locals in its stack frame.
- Temps are reset at the start of each statement.
- Call arguments are evaluated left-to-right into temps before loading `rcx`, `rdx`, `r8`, and `r9`.
- Unsupported AST shapes should fail fast through a simple codegen error and `exit(1)`.

## Builtin lowering

Current builtins are handled directly by codegen or runtime assembly helpers:

| Builtin | Implementation note |
| --- | --- |
| `putc` | writes one byte through `WriteFile` |
| `putstr` | writes `s.data` for `s.len` bytes |
| `itoa` | calls `_itoa` runtime helper |
| `system` | calls `_system` runtime helper |
| `read_file` | calls `_read_file` runtime helper and returns `u8[]` |
| `write_file` | writes a `u8[]` payload through `_write_file` |
| `str_new` | calls `_str_alloc` runtime helper |
| `str` | converts `u8[]` to `str` through `_str_alloc` |
| `bytes` | calls `_bytes` runtime helper |
| `str_starts_with` | calls `_str_starts_with` runtime helper |
| `str_find` | calls `_str_find` runtime helper |
| `str_trim` | calls `_str_trim` runtime helper |
| `len` / `cap` | emitted directly for strings and dynamic arrays |
| `push` | emitted by codegen for dynamic arrays |
| `extend` | calls `_extend_i8` for byte arrays; emits copy loops for other dynamic arrays |
| slice syntax | calls `_str_slice` for strings and emits array copy loops directly |

## Codegen self-hosting

The Epic implementation of codegen is split across `codegen_support.ep` and
`codegen.ep`. `codegen_support.ep` owns shared codegen data structures,
low-level assembly output helpers, runtime helper emission, and type helpers.
`codegen.ep` owns AST collection, layout, expression emission, statement
emission, function emission, and program emission.

The old standalone codegen entry point shape is:

```text
codegen <input.ep> <output.asm>
```

It reads one source file, calls the self-hosted lexer and parser directly, and emits a complete NASM file to `output.asm`.

Runtime helpers live as separate files under `runtime/*.asm`; Epic codegen reads those files into the generated program.

## Status and acceptance

Primary runtime acceptance:

```text
python runtests.py --linker py
```

Current known result:

```text
50 passed, 0 failed
```

v0-only historical bootstrap checks lived in the Python implementation path.
On v1, the default acceptance path uses the previous Epic compiler anchor:

```text
python runtests.py
```

The examples are the current behavioral acceptance suite, not a complete language specification.

Epic linker MVP acceptance:

```text
python test_link_ep.py
```

Current known result:

```text
50 passed, 0 failed
```
