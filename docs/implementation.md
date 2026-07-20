# Epic v0 implementation notes

This document describes the current compiler implementation. It is not the language spec. User-visible language semantics live in [`language.md`](language.md).

## Compiler driver

The current compiler entry point is:

```text
python epic.py <file.ep>
```

Useful forms:

```text
python epic.py examples/00_hello_world.ep
python epic.py examples/00_hello_world.ep --linker lld-link
python epic.py --main main.ep main.ep lib.ep
python epic.py examples/m1_exit.ep --out-dir build/custom
```

Generated files are written under `build/` by default while preserving source-relative paths:

```text
examples/00_hello_world.ep -> build/examples/00_hello_world.asm
examples/00_hello_world.ep -> build/examples/00_hello_world.obj
examples/00_hello_world.ep -> build/examples/00_hello_world.exe
```

The driver parses all input files, merges top-level definitions, emits one NASM assembly file, assembles it with NASM, then links it with either `link.py` or `lld-link`.

## Multi-file merge

`epic.py` supports whole-program source merging.

- More than one input file requires `--main`.
- All product types share one global namespace.
- All functions share one global namespace.
- Duplicate product type names are rejected.
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
runtime/bytes.asm
runtime/extend_u8.asm
runtime/itoa.asm
runtime/argv.asm
runtime/read_file.asm
runtime/write_file.asm
runtime/str_slice.asm
runtime/str_cat.asm
```

## Type lowering

User-facing types lower to implementation types:

| User type | Internal type |
| --- | --- |
| `i64` | `i64` |
| `u8` | `u8` |
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

### Product layout

User product fields use fixed 8-byte slots in v0.

- Field offset is `index * 8`.
- Struct size is `field_count * 8`.
- `u8` fields load/store one byte inside their 8-byte slot.
- Built-in runtime layouts such as `str` and dynamic arrays keep their explicit layouts.

## Parser notes

- Type names are parsed as identifiers in type context.
- The lexer preserves newline tokens and rejects semicolons.
- Ordinary statements use newlines as explicit statement terminators.
- `let` annotations are rejected.
- Functions may have at most 4 parameters.
- Calls may have at most 4 arguments.
- `os.*` calls are recognized specially.
- General method calls are rejected.
- Assignment targets support variables, field chains, and subscripts.
- `else if` is lowered by the parser to a nested `IfNode` in the `else` block.
- `break` and `continue` are statements; codegen tracks the nearest loop labels.

## Codegen notes

The backend emits NASM x64 assembly for Windows x64.

- The process entry symbol is `_start`.
- Calls follow the Windows x64 ABI.
- User calls support up to 4 register arguments.
- Runtime and Win32 calls are wrapped by helper code where needed.
- Heap allocation uses Win32 heap APIs through runtime/codegen helpers.

The backend uses compiler-generated temp locals for expression intermediates.

- A pre-scan computes the temp slots required by each function; there is no fixed temp-slot limit.
- Temps are reset at the start of each statement.
- Call arguments are evaluated left-to-right into temps before loading `rcx`, `rdx`, `r8`, and `r9`.
- Unsupported AST shapes should fail fast through a simple codegen error and `exit(1)`.

## Builtin lowering

Current builtins are handled directly by codegen or runtime assembly helpers:

| Builtin | Implementation note |
| --- | --- |
| `print` | writes `s.data` for `s.len` bytes without adding a newline |
| `itoa` | calls `_itoa` runtime helper |
| `str_new` | calls `_str_alloc` runtime helper |
| `bytes` | calls `_bytes` runtime helper |
| `str_slice` | calls `_str_slice` runtime helper |
| `read_file` | calls `_read_file` runtime helper |
| `write_file` | calls `_write_file` runtime helper |
| `push` | emitted by codegen for dynamic arrays |
| `extend` | calls `_extend_u8` runtime helper |

## Status and acceptance

Primary runtime acceptance:

```text
python runtests.py --linker py
```

The runner combines examples and end-to-end sources into one generated Epic
program, compiles it once, and starts the resulting process separately for each
case. This avoids antivirus false positives on many tiny executables and keeps
the stage-0 test cycle short.

Stage-0 checks:

```text
python test_stage0_surface.py
pwsh ./testall.ps1
```

v0 has no Epic compiler implementation and no v0 fixed-point test. Its eventual bootstrap acceptance is that the Python compiler builds an Epic v1 compiler, after which v1 reaches its own fixed point. The bundled examples and regressions are the current stage-0 behavioral suite, not a complete language specification.
