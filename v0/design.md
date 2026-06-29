# Epic v0 language design

## Core direction

- Epic is a small C-like systems language targeting Windows x64 in v0.
- Source files use the `.ep` extension.
- Blocks use `{}` and ordinary statements end at newlines. Semicolons are not part of v0 syntax.
- `if` and `while` conditions do not require parentheses.
- `let` has no type annotation. Use `let x = expr` or `let x`.
- Function parameters, return types, and struct fields keep explicit user-facing types.
- Functions have at most 4 parameters in v0. Calls have at most 4 arguments.
- Memory is not freed in v0; process exit is the reclamation boundary.
- v0 self-hosting only needs to compile the compiler's own known source shape. The happy path should be correct and deterministic; error handling may abort immediately.
- v0 does not preserve forward compatibility. When implementation and design change, self-hosting code follows the current design directly.

**Self-hosting route**: Python prototype -> Epic compiler components -> fully self-hosted compiler.

## Program model

A program is a set of top-level struct and function definitions.

There are no imports, packages, visibility rules, or per-file namespaces in v0.

## Multi-file compilation

The current driver can compile multiple source files as one whole program:

```text
python epic.py --main main.ep main.ep lib.ep
```

This is whole-program source merging, not a module system.

All top-level structs and functions from input files are merged into one global namespace. Duplicate struct or function names are rejected.

When more than one input file is provided, `--main` is required. Only the `main` function from the selected main file is used; `main` functions in non-main files are ignored.

## Future modules

Future module design should use folders as module/package boundaries, similar to Go packages: files in one folder share declarations, and cross-folder use goes through an explicit module mechanism.

Until that exists, compiler self-hosting code should avoid duplicating shared structures and should not introduce ad hoc compatibility layers.

## Types

User-facing types:

| Type | Meaning |
| --- | --- |
| `i64` | signed 64-bit integer |
| `i8` | signed byte |
| `str` | immutable heap string |
| `Name` | heap-allocated struct reference |
| `T[]` | heap-allocated dynamic array |
| `void` | function return type only; no value is produced |

Built-in globals:

| Name | Type | Meaning |
| --- | --- | --- |
| `argv` | `str[]` | command-line arguments, including `argv.data[0]` as the executable name |

At the language level, `str`, user structs, and dynamic arrays have reference semantics in v0. Assignment and parameter passing copy references, not object contents. There is no by-value struct or array copy semantics in v0.

## Functions

Function definitions use explicit parameter and return types:

```epic
fun add(a: i64, b: i64): i64 {
    return a + b
}
```

`void` functions may use `return` or fall off the end. `return expr` is invalid in a `void` function.

## Else-if chains

`else if` is syntax sugar for a nested `if` in the `else` branch:

```epic
if x == 1 {
    putstr("one")
} else if x == 2 {
    putstr("two")
} else {
    putstr("many")
}
```

This does not add a separate control-flow construct; the parser lowers it to
the same AST shape as `else { if ... }`.

## Loop control

`break` and `continue` are statement-only loop control:

```epic
while cond {
    if done {
        break
    }
    if skip {
        continue
    }
}
```

Both statements bind to the nearest enclosing `while` loop. They are rejected
outside loops.

## Structs

Struct definitions use user-facing field types:

```epic
struct Token {
    kind: str
    line: i64
}
```

`new Token` allocates a zero-initialized object and returns a `Token` value at the language level. Struct values have reference semantics in v0.

Field access uses `obj.field`. Field assignment uses `obj.field = value`.

## Strings

`str` is immutable and heap allocated. String literals produce `str` values.

Supported escapes in string and character literals:

```text
\n \r \t \\ \" \' \0
```

String and character literals are ASCII-only in v0. Non-ASCII literals are compile errors.

`len` counts bytes, not characters.

For self-hosting, v0 exposes `s.data` and `s.len` as low-level escape hatches. Mutating string bytes through `s.data[i] = ...` is outside the language contract. Use `new i8[n]` for mutable byte buffers.

## Dynamic arrays

Dynamic arrays are heap-allocated reference values.

| Expression | Meaning |
| --- | --- |
| `new T[]` | empty dynamic array with default capacity |
| `new T[n]` | empty dynamic array with capacity at least `n` |
| `push(a, x)` | append and grow as needed |
| `a.data[i]` | low-level element access |
| `a.len` | current length |
| `a.cap` | current capacity |

`new T[n]` sets capacity, not length. The initial `len` is always 0.

For self-hosting, v0 exposes `a.data`, `a.len`, and `a.cap` as low-level fields.

## System calls

`os.*` names are reserved for selected system/runtime calls exposed by the compiler.

In v0, `os` is not a module, package, object, or namespace value. Calls such as `os.ExitProcess(0)` are recognized specially by the compiler.

General method calls are not supported in v0.

## Program exit

The program entry function must be exactly:

```epic
fun main(): void {
    os.ExitProcess(0)
}
```

Falling off the end of `main` exits with status `0`. Non-zero process status is explicit through `os.ExitProcess(code)`.

`main` returning `i64` is not part of the v0 design.

## Builtins

| Builtin | Meaning |
| --- | --- |
| `putc(c: i64): void` | writes one byte |
| `putstr(s: str): void` | writes string bytes |
| `str_new(bytes, len): str` | creates a string by copying `len` bytes from a low-level byte buffer such as `buf.data` |
| `itoa(n: i64): str` | converts an integer to a heap string |
| `system(cmd: str): i64` | runs a command and returns its process exit code, or `-1` on failure |
| `read_file(path: str): str` | reads a whole file, or returns empty string on failure |
| `write_file(path: str, data: str): i64` | writes a whole file and returns bytes written, or `-1` on failure |
| `push(a: T[], x: T): void` | appends to a dynamic array |

`argv` is initialized by the runtime before `main`. v0 only requires simple Windows command-line splitting for self-hosting: whitespace separates arguments, and double quotes group an argument.

## Unsupported in v0

- User-written pointer types.
- General module/import/package system.
- General method calls.
- By-value struct or array semantics.
- Memory freeing.
- Unicode string semantics.
- Polished diagnostics or error recovery.
