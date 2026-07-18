# Epic v3 language reference

## Core direction

- Epic is a small C-like systems language targeting Windows x64 in v0.
- Source files use the `.ep` extension.
- Blocks use `{}` and ordinary statements end at newlines. Semicolons are not part of v0 syntax.
- `if` and `while` conditions do not require parentheses.
- `let` has no type annotation and always requires an initializer: `let x = expr`.
- Function parameters, return types, and product fields keep explicit user-facing types.
- Functions have at most 4 parameters in v0. Calls have at most 4 arguments.
- v3 uses a conservative, non-moving mark-and-sweep garbage collector. There is no explicit `free`.
- The Epic v3 compiler is self-hosted and begins with the v2 language surface.
- v3 does not preserve forward compatibility.

**Bootstrap route**: Python v0 stage-0 -> Epic v1 -> Epic v2 -> Epic v3 -> Epic v3 fixed point.

## Changes introduced in Epic v2

Epic v2 compiles a larger language than Epic v1, while the v2 compiler source
itself deliberately remains within the Epic v1 language surface. These additions
are therefore explicit dogfood targets for the next generation:

- a conservative, non-moving mark-and-sweep garbage collector, described in
  [`gc.md`](gc.md);
- nominal unit enums and exhaustive statement-form `match`;
- integer compound assignment: `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`,
  `<<=`, and `>>=`;
- unary integer negation `-` and logical negation `!`;
- half-open integer range loops whose bounds are evaluated once;
- `len(value)` for strings and arrays, `pop(array)` for stack-style removal,
  plus checked direct string and array subscripting with `value[index]`;
- checked semantic analysis for declarations, lexical local scope,
  use-before-declaration, expression and assignment types, call signatures, and
  required return paths.

Compiler-driver and backend changes such as `-S`, `-o`, embedded runtime text,
and in-memory assembly are implementation changes rather than language
features.

## Changes introduced in Epic v3

Epic v3 starts from the complete Epic v2 language surface, and the v3 compiler
source dogfoods the v2 additions that the previous generation deliberately did
not use. The user-visible language changes introduced in v3 are:

- `ret` is the only return-statement keyword; the legacy compatibility spelling
  `return` is rejected;
- the final expression in a block is its tail value. A compatible tail value can
  implicitly return from a non-`void` function, while explicit `ret` remains
  available;
- `if` and exhaustive enum `match` are expressions. Their branch or arm types
  are joined, so they can be used in bindings, returns, arguments, and other
  expression positions as well as discarded in statement position;
- the compiler has an internal bottom type named `never`. `exit(code)` has this
  type, so a branch that exits is compatible with any normally produced value.
  User code cannot write `never` in a declaration;
- the v2 built-in `str_replace_char(s: str, from: u8, to: u8): str` has been
  removed. Code that needs byte replacement must perform it explicitly, for
  example by copying with `bytes`, mutating the byte array, and constructing a
  new string with `str_new`.
- distinct `bool` values with `true` and `false`, plus `i8`, `u8`, `i16`,
  `u16`, `i32`, `u32`, `i64`, and `u64` integers;
- integer suffixes such as `42u32`, contextual unsuffixed literals, explicit
  integer conversions such as `i64(byte)`, compact fields and arrays, and
  width- and signedness-correct arithmetic, comparisons, shifts, and loads.

The v3 compiler implementation itself stays within the v2-era integer surface.
The v4 compiler is the dogfood target for the new bool and integer types. During
that migration, v3 retains the old `u8`/`i64` assignment and expression bridge,
and accepts legacy `i64` or `u8` conditions. New code should use matching
integer operands, explicit conversions, and `bool` conditions; the bridge is
not a forward-compatibility promise.

The v3 compiler source also dogfoods the v2 foundations: unit enums and
exhaustive matching, compound assignment, unary operators, integer range loops,
loop control, and safe container built-ins. That migration validates the
previous generation's language work; expression-form `match` is the separate v3
extension described above.

Compiler-driver and backend changes such as verbose phase timings, `a.exe` as
the default executable name, structured assembly IR, and fixed-point build
layout changes are implementation changes rather than language features.

## Program model

A program is a set of top-level product type, unit-enum, and function
definitions.

There are no imports, packages, visibility rules, or per-file namespaces in v0.

## Multi-file compilation

The current driver can compile multiple source files as one whole program:

```text
build\epic-v3.exe [-v] [-S] [-o path] main.ep lib.ep
```

Normal compilation assembles in memory and writes only the executable. `-v`
prints parse-and-merge, semantic analysis, code generation, encoding, writing,
and total times in milliseconds. It is available only for executable output
and cannot be combined with `-S`. `-S` writes the generated assembly and stops
before assembly; `-o` selects the output path in either mode. Without `-o`,
executable output is `a.exe` and `-S` output is `a.asm` in the current working
directory.

This is whole-program source merging, not a module system.

All top-level types and functions from input files are merged before semantic
analysis. Product types and enums share one type namespace; functions use a
separate namespace. Duplicate names within either namespace are rejected.

The first input is the main file. Only its `main` function is used; `main` functions in later files are ignored.

## Future modules

Future module design should use folders as module/package boundaries, similar to Go packages: files in one folder share declarations, and cross-folder use goes through an explicit module mechanism.

Until that exists, v1 bootstrap source should avoid duplicating shared structures and should not introduce ad hoc compatibility layers.

## Built-in data structures

Epic has two built-in heap data structures: immutable strings and dynamic
arrays. The complete set of user-facing types is:

| Type | Meaning |
| --- | --- |
| `bool` | distinct truth value, written `true` or `false` |
| `i8`, `i16`, `i32`, `i64` | signed integers of the stated width |
| `u8`, `u16`, `u32`, `u64` | unsigned integers of the stated width |
| `str` | immutable heap string |
| `Name` | heap-allocated product reference |
| enum `Name` | nominal unit-enum value stored as a 64-bit scalar |
| `T[]` | heap-allocated dynamic array |
| `void` | function return type only; no value is produced |

At the language level, `str`, user products, and dynamic arrays have reference
semantics. Assignment and parameter passing copy references, not object
contents. There is no by-value product or array copy semantics in v1.

Integer and bool product fields use natural alignment and occupy 1, 2, 4, or 8
bytes. Integer and bool array elements use their exact storage size and stride.
Locals and parameters remain in 8-byte stack slots as an implementation detail.

### Strings

`str` is an immutable, heap-allocated byte string. String literals produce
`str` values.

| Field or expression | Meaning |
| --- | --- |
| `len(s)` | number of bytes, excluding the trailing NUL |
| `s[i]` | checked byte access; invalid indices terminate the program |
| `s.data` | low-level address of the first byte |
| `s.data[i]` | unchecked low-level byte access |
| `s.len` | compatibility access to the internal length field |

The runtime keeps a trailing NUL for Win32 interop, but it is not part of the
string length. Direct `s[i]` rejects negative indices and indices greater than
or equal to `len(s)`, printing `Epic runtime error: index out of bounds` before
terminating. Mutating bytes through `s.data` is outside the language contract.
Use `new u8[n]` for mutable byte buffers.

### Dynamic arrays

`T[]` is a heap-allocated, growable sequence with reference semantics.

| Expression | Meaning |
| --- | --- |
| `new T[]` | empty dynamic array with default capacity |
| `new T[n]` | dynamic array of length `n` and capacity at least `n`, with zero-initialized elements |
| `len(a)` | current element count |
| `a[i]` | checked element access; invalid indices terminate the program |
| `a.data[i]` | unchecked low-level element access |
| `a.len` | compatibility access to the internal length field |
| `a.cap` | compatibility access to the internal capacity field |

`new T[]` starts empty. `new T[n]` evaluates `n` once, requires a
non-negative value, and creates `n` zero-initialized elements with `len(a) == n`.
Direct `a[i]` rejects negative indices and indices greater than or equal to
`len(a)`. `push` appends after the initialized elements; `push` and `extend` are
documented under built-in functions.

### Built-in global

| Name | Type | Meaning |
| --- | --- | --- |
| `argv` | `str[]` | command-line arguments, including `argv.data[0]` as the executable name |

`argv` is initialized before `main`. v1 implements the Windows command-line
rules needed for bootstrapping: whitespace separates arguments and double
quotes group one argument.

## Local scope

Locals use lexical block scope and are visible only after their declaration.
Parameters are visible throughout the function. A parameter or local name may
not be reused anywhere else in the same function, including a disjoint block.
`argv` and `os` are reserved names.

## Block values and tail expressions

Every block has a type. If its final item is an expression, that expression is
the block tail and supplies the block value. Earlier expression statements are
evaluated and discarded. A block with no tail value has type `void`; a block
that cannot complete normally has the internal type `never`.

```epic
let value = if ready {
    prepare()
    42
} else {
    exit(1)
}
```

The first branch has type `i64`, the second has type `never`, and the complete
`if` therefore has type `i64`. In statement or `void` context, block tail values
are evaluated and discarded instead of being joined into a result.

## Functions

Function definitions use explicit parameter and return types:

```epic
fun add(a: i64, b: i64): i64 {
    a + b
}
```

A compatible function-body tail is an implicit return. Explicit `ret expr`
remains valid and can return early. A non-`void` function is valid when every
normal path produces an assignable value or terminates with `ret` or `never`.
`while` and `for` remain statements and are not assumed to execute or terminate.

A `void` function may use bare `ret`, fall off the end, or discard any body tail
value. `ret expr` remains invalid in a `void` function. `void` means normal
completion without a usable value; `never` means that normal completion is
impossible. The latter is internal and is not a source-level type name.

The v3 statement keyword is `ret`; the legacy `return` spelling is not accepted.

## If expressions

`if` is an expression. With an `else`, its type is the join of both branch block
types:

```epic
let value = if ready {
    1
} else {
    2
}
```

Without an `else`, the false path has type `void`. Thus an `if` without `else`
can be used as a value only when its true branch also joins with `void`. A
terminating branch has type `never` and does not force the other branch to
change type:

```epic
let value = if ready {
    1
} else {
    exit(1)
}
```

Branch types must join even when the complete `if` appears in statement position.
The condition remains an `i64`; zero is false and nonzero is true.

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
while cond {
    if done {
        break
    }
    if skip {
        continue
    }
}
```

Both statements bind to the nearest enclosing `while` or `for` loop. They are
rejected outside loops.

## Integer range loops

An integer range loop traverses a half-open interval:

```epic
for i: 0:len(items) {
    use(items[i])
}
```

Both bounds are `i64` expressions. They are evaluated exactly once, from left
to right, before the first iteration. The loop produces `start` through
`end - 1`; `start >= end` executes zero iterations. Negative bounds are valid,
such as `for i: -3:2`.

The iterator is an implicit, read-only `i64` local visible only in the loop
body. It cannot be assigned or used as a compound-assignment target. `continue`
advances the iterator before the next condition check, while `break` exits the
nearest `while` or `for`. v3 has no range step or automatic reverse
iteration.

## Product types

Product definitions use `type` with user-facing field types:

```epic
type Token {
    kind: str
    line: i64
}
```

`new Token` allocates a zero-initialized object and returns a `Token` value at the language level. Product values have reference semantics in v0.

`struct` is not a keyword.

Field access uses `obj.field`. Field assignment uses `obj.field = value`.

## Unit enums and match

A unit enum has at least two members:

```epic
type TokenKind = EOF | ID | FUN
```

Members are always referenced through their type, such as `TokenKind.ID`.
Member values are nominal: values from different enums are never compatible,
even when the member names match. The only enum operators are `==` and `!=`
between values of the same enum type. An enum cannot be constructed with
`new`, converted to an integer, used as a condition, or used with arithmetic,
ordering, bit, or compound-assignment operators.

`match` is an expression over one enum value:

```epic
let result = match token.kind {
    TokenKind.EOF {
        0
    }
    TokenKind.ID {
        consume_id()
        1
    }
    else {
        exit(1)
    }
}
```

The subject is evaluated once. Explicit arms use qualified members, may appear
only once, and must belong to the subject enum. Without `else`, every member
must appear exactly once. With `else`, explicit arms may cover a strict subset;
an `else` after all members is rejected as unreachable and must be the final
arm. Arms execute in source order, each arm body is a lexical block, and all arm
block types must join. A `never` arm is compatible with the other arm values.
The complete expression may also be used in statement position; arm results are
then discarded and do not need a common value type.

v3 unit enums still have no payloads, guards, fallthrough, explicit
discriminants, or enum-to-integer conversions. Declaration order determines the
current internal values starting at zero, but those values are not source-visible
or a stable ABI.

## Compound assignment

Epic supports integer compound-assignment statements:

```epic
count += 1
flags &= 0xff
buffer[index] <<= 2
```

The complete set is `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `<<=`,
and `>>=`. The target storage type must be an integer. Strings, products,
arrays, and pointers themselves do not support compound assignment. An integer
element reached through an array or pointer remains a valid target.

The operation is performed at the target width and wraps modulo that width.
Except for shifts, the right operand must have the same type as the target; a
shift count may have any integer type. The left-value address is evaluated once,
followed by its old value and then the right operand. Compound assignment is a
statement and does not produce a value.

## Literals, conversions, and integer operations

Unary `-` accepts signed integers and operates at their width. A directly
negated literal may use the signed minimum, such as `-128i8`. Logical `!`
accepts `bool`; the v3 migration bridge also accepts `i64` and `u8`. It returns
`bool`. Unary operators bind more tightly than `*`, `/`, and `%` and may be
chained. Epic has no unary `+` or bitwise `~` in v3.

Supported escapes in string and character literals:

```text
\n \r \t \\ \" \' \0
```

String and character literals are ASCII-only in v0. Non-ASCII literals are compile errors.

Integer literals are decimal or hexadecimal (`0x` / `0X`). A suffix selects an
exact type (`1i8`, `1u8`, `1i16`, `1u16`, `1i32`, `1u32`, `1i64`, or `1u64`);
an unsuffixed literal takes its integer context and otherwise defaults to
`i64`. Literal magnitudes are range-checked mathematically, so `0xffi8` is an
error while `-1i8` is valid. The full `u64` literal range is accepted.

`T(value)` is the integer-conversion syntax. Widening sign- or zero-extends,
narrowing keeps the low bits, and a same-width conversion preserves the bit
pattern. Conversions do not perform runtime range checks: `u8(300)` is `44`,
while the literal `300u8` is a compile error.

Integer arithmetic and bitwise operators require matching operand types and
return that type. They wrap at the type width. Comparisons operate at the
original width and signedness and return `bool`; there is no automatic integer
promotion. Shifts return the left type, accept any integer count type, use
arithmetic right shift for signed values and logical right shift for unsigned
values, and follow native AMD64 count masking without a runtime check (low 6
bits for 64-bit values, low 5 bits for 8-, 16-, and 32-bit values).

String lengths and indices count bytes, not Unicode characters.

`str + str` remains the non-integer addition case. `==` and `!=` additionally
accept two bool values, two strings, or two values of the same enum type;
products and arrays have no implicit reference equality. `if` and `while`
conditions require `bool`, subject to the documented v3 migration bridge.

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

Falling off the end of `main` exits with status `0`. The built-in `exit(code)`
terminates the process with an `i64` status and has the internal result type
`never`. `os.ExitProcess(code)` remains available as the direct Windows binding,
but only `exit(code)` carries language-level no-return semantics.

`panic(message)` writes `Epic panic: `, the message bytes, and a newline to
standard error without allocating, then terminates with status `1`. It also has
the internal result type `never`. Panic output does not include a source location
or stack trace.

`main` returning `i64` is not part of the v0 design.

## Built-in functions

These names are provided by the compiler and runtime. User code does not need
to declare them.

| Function | Meaning |
| --- | --- |
| `exit(code: i64): never` | terminates the process and never returns; `never` is internal |
| `panic(message: str): never` | writes an allocation-free diagnostic to standard error, then terminates with status `1` |
| `print(s: str): void` | writes string bytes without adding a newline |
| `itoa(n: i64): str` | converts an integer to a heap string |
| `str_new(data, len: i64): str` | copies `len` bytes from a low-level address into a new string |
| `bytes(s: str): u8[]` | copies a string into a new mutable byte array |
| `len(value: str | T[]): i64` | returns a string byte length or dynamic-array element count; the argument is evaluated once |
| `is_null(value: reference): bool` | tests whether a product, string, array, or low-level pointer reference is the zero address; the argument is evaluated once |
| `str_slice(s: str, start: i64, end: i64): str` | copies the half-open byte range `[start, end)`; invalid bounds terminate the program |
| `read_file(path: str): str` | reads a whole file, or returns empty string on failure |
| `write_file(path: str, data: str | u8[]): i64` | writes a whole string or byte array and returns bytes written, or `-1` on failure |
| `push(a: T[], x: T): void` | appends to a dynamic array |
| `pop(a: T[]): T` | removes and returns the last element; empty arrays print `Epic runtime error: pop from empty array` and terminate |
| `extend(dst: u8[], src: u8[]): void` | appends all source bytes to the destination; self-extension is supported |
| `embed("path"): u8[]` | embeds raw file bytes at compile time and returns an independent mutable byte array |

`never` appears here to describe the built-in precisely, but it is not accepted
in user-written parameter, field, local, or function return type declarations.

`len(value)`, `pop(array)`, and checked `value[index]` are the preferred
container interfaces. `pop` evaluates its array expression once, preserves
capacity, and clears the removed slot so stale references do not keep objects
alive through the conservative collector.
Direct `.data`, `.len`, and `.cap` access remains available for compatibility
and deliberate low-level code, but exposes the current runtime layout and may be
deprecated in a future generation. Pointer subscripting and `.data[index]` are
unchecked.

`is_null` checks only the outer reference address. An empty string or empty
array is not null, a nonzero dangling pointer is not null, and no implicit null
guard is inserted before field access or subscripting. Integer and enum zero
values are not references and are rejected; test an integer handle with
`value == 0` instead. `is_null` is a normal builtin name rather than a keyword.

`embed` accepts exactly one string literal. Relative paths are resolved against
the `.ep` file containing the expression; absolute paths are used unchanged.
A missing or unreadable file is a compile error, while an empty file is valid.

## Unsupported in v0

- User-written pointer types.
- General module/import/package system.
- General method calls.
- Payload sums.
- By-value product or array semantics.
- Explicit memory freeing.
- Unicode string semantics.
- Polished diagnostics or error recovery.
