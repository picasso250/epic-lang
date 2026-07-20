# Epic v1 language reference

## Core direction

- Epic is a small C-like systems language targeting Windows x64 in v0.
- Source files use the `.ep` extension.
- Blocks use `{}` and ordinary statements end at newlines. Semicolons are not part of v0 syntax.
- `if` and condition-form `for` conditions do not require parentheses.
- `let` has no type annotation. Use `let x = expr` or `let x`.
- Function parameters, return types, and product fields keep explicit user-facing types.
- Functions have at most 4 parameters in v0. Calls have at most 4 arguments.
- Memory is not freed in v0; process exit is the reclamation boundary.
- The Epic v1 compiler is self-hosted, and its source deliberately stays within the v0 language subset documented here.
- v1 does not preserve forward compatibility.

**Bootstrap route**: Python v0 stage-0 -> Epic v1 -> Epic v1 fixed point.

## Program model

A program is a set of top-level product type and function definitions.

There are no imports, packages, visibility rules, or per-file namespaces in v0.

## Multi-file compilation

The current driver can compile multiple source files as one whole program:

```text
build\epic-v1.exe [-o output.exe] main.ep lib.ep
```

Without `-o`, the compiler writes `a.asm` and `a.exe` in the current working
directory. `-o` changes only the executable path; the private assembly remains
`a.asm`.

This is whole-program source merging, not a module system.

All top-level product types and functions from input files are merged into one global namespace. Duplicate type or function names are rejected.

The first input is the main file. Only its `main` function is used; `main` functions in later files are ignored.

## Future modules

Future module design should use folders as module/package boundaries, similar to Go packages: files in one folder share declarations, and cross-folder use goes through an explicit module mechanism.

Until that exists, v1 bootstrap source should avoid duplicating shared structures and should not introduce ad hoc compatibility layers.

## Built-in data structures

Epic has two built-in heap data structures: immutable strings and dynamic
arrays. The complete set of user-facing types is:

| Type | Meaning |
| --- | --- |
| `i64` | signed 64-bit integer |
| `u8` | unsigned byte storage; reads zero-extend to `i64` |
| `str` | immutable heap string |
| `Name` | heap-allocated product reference |
| `T[]` | heap-allocated dynamic array |
| `void` | function return type only; no value is produced |

At the language level, `str`, user products, and dynamic arrays have reference
semantics. Assignment and parameter passing copy references, not object
contents. There is no by-value product or array copy semantics in v1.

### Strings

`str` is an immutable, heap-allocated byte string. String literals produce
`str` values.

| Field or expression | Meaning |
| --- | --- |
| `s.data` | low-level address of the first byte |
| `s.data[i]` | byte at index `i` |
| `s.len` | number of bytes, excluding the trailing NUL |

The runtime keeps a trailing NUL for Win32 interop, but it is not part of the
string length. Mutating bytes through `s.data` is outside the language
contract. Use `new u8[n]` for mutable byte buffers.

### Dynamic arrays

`T[]` is a heap-allocated, growable sequence with reference semantics.

| Expression | Meaning |
| --- | --- |
| `new T[]` | empty dynamic array with default capacity |
| `new T[n]` | dynamic array of length `n` and capacity at least `n`, with zero-initialized elements |
| `a.data[i]` | element at index `i` |
| `a.len` | current element count |
| `a.cap` | current capacity |

`new T[]` starts empty. `new T[n]` evaluates `n` once, requires a
non-negative value, and creates `n` zero-initialized elements with `len == n`.
`push` appends after those elements. `push` and `extend` are documented under
built-in functions.

### Built-in global

| Name | Type | Meaning |
| --- | --- | --- |
| `argv` | `str[]` | command-line arguments, including `argv.data[0]` as the executable name |

`argv` is initialized before `main`. v1 implements the Windows command-line
rules needed for bootstrapping: whitespace separates arguments and double
quotes group one argument.

## Functions

Function definitions use explicit parameter and return types:

```epic
fun add(a: i64, b: i64): i64 {
    ret a + b
}
```

`void` functions may use `ret` or fall off the end. `ret expr` is invalid in a `void` function.

## Else-if chains

`else if` is syntax sugar for a nested `if` in the `else` branch:

```epic
if x == 1 {
    print("one")
} else if x == 2 {
    print("two")
} else {
    print("many")
}
```

This does not add a separate control-flow construct; the parser lowers it to
the same AST shape as `else { if ... }`.

## Loop control

`break` and `continue` are statement-only loop control:

```epic
for cond {
    if done {
        break
    }
    if skip {
        continue
    }
}
```

Both statements bind to the nearest enclosing `for` loop. They are rejected
outside loops.

## Product types

Product definitions use `type` with user-facing field types:

```epic
type Token {
    kind: str
    line: i64
}
```

`new Token` allocates a zero-initialized object and returns a `Token` value at the language level. Product values have reference semantics in v0.

`struct` is not a keyword. `type Name = A | B` payload sums and unit sums are outside the bootstrap subset. v1 may implement them for client programs without using them in its own source.

Field access uses `obj.field`. Field assignment uses `obj.field = value`.

## Literals and byte operations

Supported escapes in string and character literals:

```text
\n \r \t \\ \" \' \0
```

String and character literals are ASCII-only in v0. Non-ASCII literals are compile errors.

Integer literals are decimal or hexadecimal (`0x` / `0X`) and must fit the
non-negative range of `i64`.

Bit operations use `i64`. `<<` keeps the low 64 bits, `>>` is arithmetic, and
shift counts outside `0..63` terminate the program. `u8` values are zero-extended
before participating in `<<`, `>>`, `&`, or `|`.

String lengths and indices count bytes, not Unicode characters.

## System calls

`os.*` names are reserved for selected system/runtime calls exposed by the compiler.

In v0, `os` is not a module, package, object, or namespace value. Calls such as `os.ExitProcess(0)` are recognized specially by the compiler.

`os.CreateDirectoryA(path, 0)` creates a directory and returns nonzero on
success. It returns zero on failure, including when the directory already
exists.

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

## Built-in functions

These names are provided by the compiler and runtime. User code does not need
to declare them.

| Function | Meaning |
| --- | --- |
| `print(s: str): void` | writes string bytes without adding a newline |
| `itoa(n: i64): str` | converts an integer to a heap string |
| `str_new(data, len: i64): str` | copies `len` bytes from a low-level address into a new string |
| `bytes(s: str): u8[]` | copies a string into a new mutable byte array |
| `str_slice(s: str, start: i64, end: i64): str` | copies the half-open byte range `[start, end)`; invalid bounds terminate the program |
| `read_file(path: str): str` | reads a whole file, or returns empty string on failure |
| `write_file(path: str, data: str): i64` | writes a whole file and returns bytes written, or `-1` on failure |
| `push(a: T[], x: T): void` | appends to a dynamic array |
| `extend(dst: u8[], src: u8[]): void` | appends all source bytes to the destination; self-extension is supported |
| `embed("path"): u8[]` | embeds raw file bytes at compile time and returns an independent mutable byte array |

`embed` accepts exactly one string literal. Relative paths are resolved against
the `.ep` file containing the expression; absolute paths are used unchanged.
A missing or unreadable file is a compile error, while an empty file is valid.

## Unsupported in v0

- User-written pointer types.
- General module/import/package system.
- General method calls.
- Payload sums, unit sums, and `match`.
- By-value product or array semantics.
- Memory freeing.
- Unicode string semantics.
- Polished diagnostics or error recovery.
