# Epic Implementation Notes

This document describes the current implementation. Earlier version notes
(impl-v0, impl-v1, impl-v2) are preserved in git history and tag
`staged-bootstrap-archive-2026-06-30` as historical anchors.

## Repository Layout

```
bootstrap/          Python reference compiler
src/                Self-hosted Epic compiler sources
runtime/            NASM runtime helpers
examples/           Example programs and regression tests
tools/              NASM, LLD-Link
docs/               Documentation
editors/            Editor support
tree-sitter-epic/   Tree-sitter grammar
```

## Python Reference Compiler

`bootstrap/` contains the Python implementation:

```
bootstrap/epic.py
bootstrap/lexer.py
bootstrap/parser.py
bootstrap/ast_nodes.py
bootstrap/codegen.py
```

The driver reads sources from the repository root, writes build output under
`build/`, appends runtime helpers from `runtime/`, assembles with
`tools/nasm.exe`, and links through `link.py` (Python linker) or
`tools/lld-link.exe`.

### Constructor Shorthand

The Python parser lowers constructor shorthand to the same AST form as an empty
initializer: `new S` → `new S {}` and `new A.V` → `new A.V {}`. Codegen has no
separate shorthand path.

## Epic Compiler

`src/` contains the self-hosted compiler sources:

```
src/epic.ep
src/lexer.ep
src/parser.ep
src/codegen_support.ep
src/codegen.ep
src/link.ep              # Epic linker (separate tool, not compiler fixed-point)
```

### Codegen Split

`codegen_support.ep` owns shared codegen data structures, low-level assembly
output helpers, runtime helper emission, and type helpers. `codegen.ep` owns
AST collection, layout, expression emission, statement emission, function
emission, and program emission. This split uses the existing whole-program
multi-file compilation model.

## Acceptance

Core acceptance checks:

```powershell
python runtests.py --linker py
python test_bootstrap_fixed_point.py
```

Lexer/parser/codegen bootstrap checks:

```powershell
python test_lexer_bootstrap.py
python test_parser_bootstrap.py
python test_codegen_bootstrap.py
```

## Toolchain

Current toolchain paths:

- `tools/nasm.exe`
- `tools/lld-link.exe`
- `link.py` (Python PE linker, default)
- Windows SDK `kernel32.lib` and `user32.lib`

## Runtime Helpers

The driver appends runtime assembly helpers after emitted program assembly:

```
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

## Type Lowering

| User type   | Internal type     |
|-------------|-------------------|
| `bool`      | `bool`            |
| `u8`        | `u8`              |
| `i64`       | `i64`             |
| `u64`       | `u64`             |
| `str`       | `&str`            |
| `Token`     | `&Token`          |
| `u8[]`      | `&_arr_u8`        |
| `Token[]`   | `&_arr_Token`     |

User programs do not write pointer types. `&T` and `&&T` are codegen-internal
types only.

## Runtime Layouts

### String

```
str = {
    data: &u8,
    len: i64,
}
```

String literals are deep-copied into heap storage with a trailing NUL byte.
`len` excludes the NUL. Empty strings may have `data = 0` when `len = 0`.

### Dynamic Array

```
_arr_T = {
    data,
    len: i64,
    cap: i64,
}
```

Primitive arrays store primitive values. Struct and `str` arrays store
references.

### Struct

User struct fields use fixed 8-byte slots. Field offset is `index * 8`.
Struct size is `field_count * 8`. `u8` and `bool` fields load/store one byte
inside their 8-byte slot.

### ADT

ADT values are references to a 16-byte header object:

- header slot 0: numeric tag (`i64`)
- header slot 1: pointer to a heap-allocated payload object

Payload layouts reuse struct field layout rules. Variant tags follow
declaration order. ADT zero value is tag `0` plus a zero-valued payload for
the first variant.

## Codegen Model

The backend emits NASM x64 assembly for Windows x64.

- Process entry symbol: `_start`
- Calls follow the Windows x64 ABI (up to 4 register arguments)
- Heap allocation uses Win32 heap APIs through runtime helpers
- Each function reserves temp locals for expression intermediates
- Temps are reset at the start of each statement
- Call arguments are evaluated left-to-right into temps before loading `rcx`,
  `rdx`, `r8`, `r9`

### Lowering Notes

- **Brace disambiguation**: A postfix `{ ... }` in expression or pattern
  position is always parsed as an initializer or pattern-payload candidate.
  The semantic pass and codegen reject invalid uses.
- **Match colon rule**: Every match case uses a colon between the pattern and
  its body. The parser enforces this at the syntax level.
- **ADT match lowering**: Emit the scrutinee once, load the tag, linear
  compare/jump chain over variant tags, load `data` from header slot 1, bind
  payload fields by layout offsets, emit the case block.
- **Map lowering**: `map[str]T` uses a linear-probe or dynamic-array-backed
  entry table. `m[key] = value` inserts or overwrites. Absent lookup returns
  zero value. `map_has` distinguishes absence.

## Linker

`link.py` is the default Python PE linker, supporting the narrow single-object
PE64 path needed by generated examples. `src/link.ep` is an Epic MVP linker for
the same path, compiled with the current Epic compiler.

`lld-link` is available through `--linker lld-link`.

## Builtin Lowering

| Builtin            | Implementation                               |
|--------------------|---------------------------------------------|
| `putc`             | `WriteFile` syscall                          |
| `putstr`           | writes `s.data` for `s.len` bytes            |
| `itoa`             | `_itoa` runtime helper                       |
| `system`           | `_system` runtime helper                     |
| `read_file`        | `_read_file` runtime helper, returns `u8[]`  |
| `write_file`       | writes `u8[]` payload through `_write_file`  |
| `str` (`u8[]`)     | `_str_alloc` runtime helper                  |
| `bytes`            | `_bytes` runtime helper                      |
| `str_new`          | `_str_alloc` runtime helper                  |
| `str_slice`        | `_str_slice` runtime helper                  |
| `str_starts_with`  | `_str_starts_with` runtime helper            |
| `str_find`         | `_str_find` runtime helper                   |
| `str_trim`         | `_str_trim` runtime helper                   |
| `push`             | emitted by codegen for dynamic arrays        |
| `extend`           | `_extend_i8` for byte arrays; copy loops for others |
| `len` / `cap`      | emitted directly                             |
| slice syntax       | `_str_slice` for strings; array copy loops   |

Little-endian load/store helpers are not builtins. `link.ep` and examples
implement them as ordinary Epic functions using `u8[]`, `u64`, checked
indexing, and bit operations.
