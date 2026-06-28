# Epic v0 implementation notes

This document describes the current compiler implementation. It is not the language spec. User-visible language semantics live in `design.md`.

## Compiler driver

The current compiler entry point is:

```text
python epic.py <file.ep>
```

Useful forms:

```text
python epic.py examples/m1_exit.ep
python epic.py examples/m1_exit.ep --linker lld-link
python epic.py --main main.ep main.ep lib.ep
python epic.py examples/m1_exit.ep --out-dir build/custom
```

Generated files are written under `build/` by default while preserving source-relative paths:

```text
examples/m1_exit.ep -> build/examples/m1_exit.asm
examples/m1_exit.ep -> build/examples/m1_exit.obj
examples/m1_exit.ep -> build/examples/m1_exit.exe
```

The driver parses all input files, merges top-level definitions, emits one NASM assembly file, assembles it with NASM, then links it with either `link.py` or `lld-link`.

## Multi-file merge

`epic.py` supports whole-program source merging.

- More than one input file requires `--main`.
- All structs share one global namespace.
- All functions share one global namespace.
- Duplicate struct names are rejected.
- Duplicate function names are rejected.
- A `main` function in a non-main input file is ignored.
- This is not a module system.

## Toolchain

Current toolchain paths are configured in `epic.py`:

- `tools/nasm.exe`
- `tools/lld-link.exe`
- `link.py`
- Windows SDK `kernel32.lib` and `user32.lib`

`link.py` is the default linker. `lld-link` is available through `--linker lld-link`.

## Runtime helpers

The driver appends runtime assembly helpers after emitted program assembly:

```text
runtime/str_alloc.asm
runtime/itoa.asm
runtime/argv.asm
runtime/system.asm
runtime/read_file.asm
runtime/write_file.asm
runtime/append_file.asm
```

## Type lowering

User-facing types lower to implementation types:

| User type | Internal type |
| --- | --- |
| `i64` | `i64` |
| `i8` | `i8` |
| `str` | `&str` |
| `Token` | `&Token` |
| `i64[]` | `&_arr_i64` |
| `Token[]` | `&_arr_Token` |

User programs do not write pointer types. `&T` and `&&T` are compiler-internal codegen types only.

## Runtime layouts

### String layout

```text
str = {
    data: &i8,
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

User struct fields use fixed 8-byte slots in v0.

- Field offset is `index * 8`.
- Struct size is `field_count * 8`.
- `i8` fields load/store one byte inside their 8-byte slot.
- Built-in runtime layouts such as `str` and dynamic arrays keep their explicit layouts.

## Parser notes

- Type names are parsed as identifiers in type context.
- `let` annotations are rejected.
- Functions may have at most 4 parameters.
- Calls may have at most 4 arguments.
- `sys.*` calls are recognized specially.
- General method calls are rejected.
- Assignment targets support variables, field chains, and subscripts.
- Expression postfixes support checked indexing and copy slices for strings and arrays.

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
| `read_file` | calls `_read_file` runtime helper |
| `write_file` | calls `_write_file` runtime helper |
| `append_file` | calls `_append_file` runtime helper |
| `str_new` | calls `_str_alloc` runtime helper |
| `len` / `cap` | emitted directly for strings and dynamic arrays |
| `push` | emitted by codegen for dynamic arrays |
| slice syntax | calls `_str_slice` for strings and emits array copy loops directly |

## Codegen self-hosting

The Epic implementation of codegen is currently a standalone program:

```text
codegen <input.ep> <output.asm>
```

It reads one source file, calls the self-hosted lexer and parser directly, and emits a complete NASM file to `output.asm`.

Runtime helpers live as separate files under `runtime/*.asm`; Epic codegen appends those files to the generated program with `read_file` and `append_file`.

## Status and acceptance

Primary runtime acceptance:

```text
python runtests.py --linker py
```

Current known result:

```text
46 passed, 0 failed
```

v0-only historical bootstrap checks lived in the Python implementation path.
On v1, the default acceptance path uses the previous Epic compiler anchor:

```text
python runtests.py
```

The examples are the current behavioral acceptance suite, not a complete language specification.
