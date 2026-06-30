# Epic Language Design

This document describes the current Epic language. Earlier version notes
(design-v0, design-v1, design-v2) are preserved in git history and tag
`staged-bootstrap-archive-2026-06-30` as historical anchors.

## Direction

Epic is a small C-like systems language targeting Windows x64. It is designed
around whole-program compilation, explicit types at function and struct
boundaries, heap-allocated reference values for strings, structs, dynamic
arrays, and ADTs, and a self-hosted compiler written in Epic.

The implementation does not preserve forward compatibility. When the language
changes, compiler sources move with the current design.

## Program Model

A program is a set of top-level struct, type, and function definitions. There
are no imports, packages, visibility rules, or per-file namespaces.

The current driver supports whole-program source merging:

```text
python epic.py --main main.ep main.ep lib.ep
```

All top-level definitions from input files are merged into one global
namespace. Duplicate names are rejected. When more than one input file is
provided, `--main` is required; only the `main` function from the selected main
file is used.

## Types

User-facing types:

| Type     | Meaning                                    |
|----------|--------------------------------------------|
| `bool`   | logical value, `true` or `false`           |
| `u8`     | unsigned 8-bit byte                        |
| `i64`    | signed 64-bit integer                      |
| `u64`    | unsigned 64-bit integer                    |
| `str`    | immutable byte string descriptor           |
| `Name`   | heap-allocated struct or ADT reference     |
| `T[]`    | heap-allocated dynamic array descriptor    |
| `map[str]T` | heap-allocated map (str key)           |
| `void`   | function return type only                  |

`str`, user structs, ADTs, dynamic arrays, and maps have reference semantics.
Assignment and parameter passing copy references, not object contents. There is
no by-value struct or array copy semantics.

### Built-in Globals

| Name   | Type     | Meaning                                                        |
|--------|----------|----------------------------------------------------------------|
| `argv` | `str[]`  | command-line arguments, `argv.data[0]` is the executable name  |

## Functions

Function definitions use explicit parameter and return types:

```epic
fun add(a: i64, b: i64): i64 {
    return a + b
}
```

Functions have at most 4 parameters. Calls have at most 4 arguments. `void`
functions may use `return` or fall off the end. `return expr` is invalid in a
`void` function.

The program entry function must be:

```epic
fun main(): i64 {
    return 0
}
```

`main` may also return `void`. Falling off the end of `main` exits with status
`0`. Non-zero exit is explicit through `os.ExitProcess(code)`.

## Expressions and Statements

### Literals

- Integer literals adapt to the target type when representable. Negative
  literals do not adapt to unsigned types.
- `true` and `false` are `bool` literals.
- String literals produce `str` values. Supported escapes:
  `\n \r \t \\ \" \' \0`. ASCII-only.
- Character literals produce `u8`. Supported escapes match strings.

### Let Declarations

`let` supports optional type annotations:

```epic
let b: u8 = 1
let ok: bool
let token: Token
```

When the RHS clearly determines the type, the annotation should be omitted.

`let x: T` without an initializer creates a zero value. For scalars that is
`0` or `false`. For `str`, arrays, structs, and ADTs, the variable holds a
non-null descriptor whose fields are zeroed; `.data` may be `0` when `.len`
is `0`.

### Operators

Arithmetic `+`, `-`, `*`, `/`, `%` is checked and exits on overflow or
division by zero.

Comparison `==`, `!=`, `<`, `<=`, `>`, `>=` operates on `bool` for logical
results.

Logical `&&`, `||`, `!` operate on `bool`. Integers do not have implicit
truthiness; write `x != 0` or `bool(x)`.

Bitwise `~`, `&`, `|`, `^` and shift `<<`, `>>`, `>>>` are low-level and not
checked. `>>` is arithmetic for `i64` and logical for unsigned integers.
`>>>` is always logical.

### Compound Assignment

Supported: `+=`, `-=`, `*=`, `/=`, `%=`, `<<=`, `>>=`, `>>>=`, `&=`, `|=`, `^=`.
The left-hand side is evaluated once. `str += str` performs string
concatenation.

### Control Flow

- `if` / `else if` / `else` with explicit boolean conditions.
- `while` with explicit boolean condition.
- `break` and `continue` bind to the nearest enclosing `while` loop.
- `for i in start:end` — half-open ascending range, evaluates `start` and
  `end` once, runs while `i < end`. `continue` jumps to the increment.
- `return expr` / `return`.
- `panic "message"` — prints source position and message, exits non-zero.
- `assert cond` / `assert cond, "message"` — always enabled, exits on failure.

### Struct Initialization

```epic
struct Pos { line: i64; col: i64 }
let p = new Pos { line: 3, col: 9 }
let q = new Pos { line: 3 }     # omitted fields get zero
let z = new Pos {}              # all fields zero
```

`new Ctor` is shorthand for `new Ctor {}`. For structs, `Ctor` is a struct
name. Omitted fields are initialized to zero values.

```epic
let b = new Box
let b2 = new Box {}
```

Fields are named. Order is irrelevant. Unknown or duplicate fields are compile
errors.

### Array Literals

```epic
let xs = new i64[] { 1, 2, 3 }
let bs = new u8[] { 65, 66, 67 }
```

Allocates a dynamic array whose `len` and `cap` are the element count.
`new T[n]` allocates an empty array with capacity for at least `n` elements.

### ADTs

```epic
type Expr {
    Empty
    IntLit { value: i64 }
    Binary { op: str; left: Expr; right: Expr }
}
```

ADTs are reference types. The zero value is the first variant with zero-valued
payload. Variant initializers use named brace syntax:

```epic
let e = new Expr.IntLit { value: 123 }
let empty: Expr
```

Constructor shorthand applies to ADT variants as well:

```epic
let e = new Expr.Empty              # shorthand for new Expr.Empty {}
let e2 = new Expr.Empty {}
```

`new AdtName` is not an ADT constructor; ADT construction must name a variant.

### Match

`match` is a statement. Supports literal cases and ADT variant cases.

Basic type match:

```epic
match n {
    0:  { putstr("zero") }
    1:  { putstr("one") }
    else: { putstr("many") }
}
```

Supported scrutinee types: `i64`, `u64`, `u8`, `bool`, `str`.

ADT match:

```epic
match e {
    Expr.IntLit { value: n }: { puti(n) }
    Expr.Binary { op, left, right }: { putstr(op) }
    else: { panic "unknown expr" }
}
```

Rules:
- Every case uses a colon between pattern and body.
- `else` is optional, must be last when present.
- No fallthrough.
- ADT payload patterns bind fields by name (`{ value: n }` or `{ value }`).
- Unknown or duplicate payload bindings are compile errors.
- No exhaustiveness checking — missing cases produce a runtime panic.

### Map

```epic
let ids = new map[str]i64
ids["main"] = 1
let id = ids["main"]
let ok = map_has(ids, "main")
```

Key type is fixed to `str`. Absent lookup returns the value type's zero value.

## Strings and Arrays

### String Layout

`str` is length-carrying and NUL-terminated for Win32 interop. `s.len` counts
bytes, excludes the trailing NUL. `s.data` and `s.len` are low-level fields;
new code should use `len()` and slice syntax.

### Dynamic Arrays

`T[]` is a heap-allocated reference value.

| Expression           | Meaning                                              |
|----------------------|------------------------------------------------------|
| `new T[]`            | empty array with default capacity                    |
| `new T[n]`           | empty array with capacity at least `n`               |
| `push(a, x)`         | append and grow                                      |
| `extend(dst, src)`   | append all elements of one array to another          |
| `a.data[i]`          | low-level unchecked element access                   |
| `a.len` / `len(a)`   | current length                                       |
| `a.cap` / `cap(a)`   | current capacity                                     |

### Indexing and Slices

Indexing is bounds-checked. `s[i]` on a string returns `u8`.

Slice syntax (copy semantics, half-open `[start, end)`):

```epic
let a = s[start:end]
let b = s[start:]
let c = s[:end]
let d = s[:]
```

- omitted `start` = `0`, omitted `end` = `.len`
- `start < 0` or `end < 0` dies
- `start > end` or `end > len` dies
- successful slices allocate and copy

### Length and Capacity (builtins)

| Builtin            | Meaning                     |
|--------------------|-----------------------------|
| `len(s: str): i64`   | string byte length          |
| `len(xs: T[]): i64`  | array element count         |
| `cap(xs: T[]): i64`  | array capacity              |

`cap(str)` is invalid.

## File IO (byte-oriented)

```epic
read_file(path: str): u8[]
write_file(path: str, data: u8[]): i64
str(bytes: u8[]): str
bytes(s: str): u8[]
```

`read_file` returns an empty `u8[]` on failure. `str(u8[])` copies the full
array length and appends a trailing NUL. Ordinary source loading:

```epic
let source = str(read_file(path))
```

## Other Builtins

| Builtin                                | Meaning                                       |
|----------------------------------------|-----------------------------------------------|
| `putc(c: i64): void`                   | writes one byte                               |
| `putstr(s: str): void`                 | writes string bytes                           |
| `itoa(n: i64): str`                    | integer to heap string                        |
| `str_new(bytes, len): str`             | creates a string by copying `len` bytes from a low-level buffer |
| `str_starts_with(s, prefix): i64`      | true when `s` starts with `prefix`            |
| `str_find(s, needle): i64`             | first byte index, or `-1`                     |
| `str_trim(s): str`                     | trim leading/trailing ASCII whitespace        |
| `system(cmd: str): i64`                | runs a command, returns exit code             |
| `push(a: T[], x: T): void`             | append to dynamic array                       |
| `extend(dst: T[], src: T[]): void`      | append all elements                           |

`os.*` names are reserved for system/runtime calls exposed by the compiler.
`os.ExitProcess(code)`, `os.WriteFile`, etc. are recognized specially.

## Bootstrap Model

```text
Python reference compiler -> Epic compiler -> Epic compiler
```

The Python reference compiler lives in `bootstrap/`. The self-hosted Epic
compiler lives in `src/`. The fixed-point test
(`test_bootstrap_fixed_point.py`) verifies that repeated Epic-built compilers
are byte-identical.

The staged v0/v1/v2 directory chain is historical. Git tags preserve that
chain; it is no longer part of the maintained source layout.
