# Epic v0 design

## Core direction

- User programs do not write pointer types. `&T` and `&&T` are compiler-internal codegen types only.
- `let` has no type annotation. Use `let x = expr;` or `let x;`.
- Function parameters, return types, and struct fields keep explicit user-facing types:
  - `i64` and `i8` are value types.
  - `str` lowers internally to `&str`.
  - A user struct name such as `Token` lowers internally to `&Token`.
  - `T[]` lowers internally to `&_arr_T`.
- v0 uses heap objects and one extra pointer hop for non-primitive values. There is no by-value struct semantics.
- Functions have at most 4 parameters in v0. Calls have at most 4 arguments.
- Memory is not freed in v0; process exit is the reclamation boundary.
- v0 self-hosting only needs to compile the compiler's own known source shape. The happy path should be correct and deterministic; error handling only needs to reject bad input, and may abort immediately instead of recovering or producing polished diagnostics.
- v0 does not preserve forward compatibility. When the implementation and design change, self-hosting code follows the current design directly.

**自举路线**: Python 版原型 → Epic 版编译器逐步替换 → 完全自举。

## Modules

v0 does not add a temporary shared-file convention just to factor compiler structs during self-hosting.

Future module design should use folders as module/package boundaries, similar to Go packages: files in one folder share declarations, and cross-folder use goes through an explicit module mechanism. Until that exists, compiler self-hosting code should avoid duplicating shared structures and should not introduce ad hoc compatibility layers.

## Types

User-facing types:

| Type | Meaning |
| --- | --- |
| `i64` | signed 64-bit integer |
| `i8` | signed byte |
| `str` | immutable heap string |
| `Name` | heap-allocated struct reference |
| `T[]` | heap-allocated dynamic array |
| `void` | function return type only |

Built-in globals:

| Name | Type | Meaning |
| --- | --- | --- |
| `argv` | `str[]` | command-line arguments, including `argv.data[0]` as the executable name |

Internal lowering:

| User type | Internal type |
| --- | --- |
| `i64` | `i64` |
| `i8` | `i8` |
| `str` | `&str` |
| `Token` | `&Token` |
| `i64[]` | `&_arr_i64` |
| `Token[]` | `&_arr_Token` |

## Structs

Struct definitions use user-facing field types:

```epic
struct Token {
    kind: str;
    line: i64;
}
```

`new Token` allocates a zero-initialized heap object and returns a `Token` value at the language level. Internally that value is a pointer.

User struct fields use fixed 8-byte slots in v0. Field offsets are `index * 8`, and struct size is `field_count * 8`. `i8` fields still load/store one byte inside their slot. Built-in runtime layouts such as `str` and dynamic arrays keep their explicit layouts.

## Strings

`str` is immutable and heap allocated:

```text
str = { data: &i8, len: i64 }
```

String literals are expression values. Each evaluation deep-copies bytes into a new heap `str` and appends a trailing `\0` byte for Win32 API interop. `len` excludes that trailing null byte.

Supported escapes in string and character literals:

```text
\n \r \t \\ \" \' \0
```

String and character literals are ASCII-only in v0. Non-ASCII literals are compile errors.

Mutation through `str.data[i] = ...` is not part of the language contract. Use `new i8[n]` for mutable byte buffers.

## Dynamic Arrays

Dynamic arrays use:

```text
_arr_T = { data, len: i64, cap: i64 }
```

Operations:

| Expression | Meaning |
| --- | --- |
| `new T[]` | empty dynamic array with default capacity |
| `new T[n]` | empty dynamic array with capacity at least `n` |
| `push(a, x)` | append and grow as needed |
| `a.data[i]` | low-level element access |
| `a.len` | current length |
| `a.cap` | current capacity |

Primitive arrays store primitive values. Struct and `str` arrays store references. `.data`, `.len`, and `.cap` remain exposed in v0 as a self-hosting escape hatch.

## Builtins

| Builtin | Signature | Notes |
| --- | --- | --- |
| `exit` | `exit(code: i64) -> void` | exits the process |
| `putc` | `putc(c: i64) -> void` | writes one byte |
| `putstr` | `putstr(s: str) -> void` | writes `s.data` for `s.len` bytes |
| `strcmp` | `strcmp(a: str, b: str) -> i64` | Win32 `lstrcmpA` over null-terminated data |
| `str_new` | `str_new(bytes: i8[], len: i64) -> str` | deep-copies bytes into a string |
| `itoa` | `itoa(n: i64) -> str` | integer to heap string |
| `system` | `system(cmd: str) -> i64` | returns process exit code or `-1` |
| `read_file` | `read_file(path: str) -> str` | reads a whole file or returns empty string on failure |
| `write_file` | `write_file(path: str, data: str) -> i64` | writes a whole file and returns bytes written, or `-1` on failure |
| `append_file` | `append_file(path: str, data: str) -> i64` | appends to a file, creating it if needed, and returns bytes written, or `-1` on failure |
| `push` | `push(a: T[], x: T) -> void` | appends to dynamic array |

`argv` is initialized by the runtime before `main`. v0 only requires simple Windows command-line splitting for self-hosting: whitespace separates arguments, and double quotes group an argument.

## Compiler Outputs

`epicc.py` writes generated files under `build/` by default and preserves source-relative paths:

```text
examples/m1_exit.ep -> build/examples/m1_exit.asm
examples/m1_exit.ep -> build/examples/m1_exit.obj
examples/m1_exit.ep -> build/examples/m1_exit.exe
```

Use `--out-dir DIR` to choose another output directory.

## Codegen self-hosting plan

The first Epic implementation of codegen is a standalone program:

```text
codegen <input.ep> <output.asm>
```

It reads one source file, calls the self-hosted lexer and parser directly, and emits a complete NASM file to `output.asm`. Runtime helpers live as separate files under `runtime/*.asm`; Epic codegen appends those files to the generated program with `read_file` and `append_file`.

Initial acceptance is behavioral, not textual: assembly generated by Epic codegen must assemble, link, and pass the single-file `examples/*.ep` tests. The first implementation slice targets `m1_exit.ep` through `m7_str.ep`.

The first Epic codegen uses compiler-generated temp locals for expression intermediates. Each function reserves 64 hidden `i64` temp locals in its stack frame. Temps are reset at the start of each statement, and call arguments are evaluated left-to-right into temps before loading `rcx`, `rdx`, `r8`, and `r9`.

Unsupported AST shapes should fail fast through a simple codegen error and `exit(1)`.
