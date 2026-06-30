# Epic v1 language design

v1 starts from the current `../v0` language and records only the v1 language delta. It intentionally does not preserve source compatibility.

The v1 compiler sources are still compiled by the v0 bootstrap anchor. That means `epic.ep`, `lexer.ep`, `parser.ep`, `codegen_support.ep`, and `codegen.ep` must stay in the source shape accepted by v0. v1 syntax and builtins are tested through examples and through `link.ep`; the first source tree compiled by the v1 compiler is reserved for `../v2`.

## Scope

v1 focuses on the features needed to make compiler and binary-tooling code less fragile:

- a small type reset around `bool`, `u8`, and `u64`
- explicit boolean conditions
- typed `let` and zero values
- user-level bitwise and shift operators
- checked arithmetic and conversions
- compound assignment
- `len()` and `cap()`
- checked indexing and copy slice syntax
- stronger byte-oriented string helpers
- byte-array file IO
- a narrow integer range loop
- enough binary support to write `link.ep`

`map[str]T` remains deferred until compiler code shows a concrete need.

## Type Reset

v1 removes the user-facing signed byte type. `u8` is the byte type used by strings, byte buffers, file IO, and character literals.

User-facing scalar and reference types are:

| Type | Meaning |
| --- | --- |
| `bool` | logical value, `true` or `false` |
| `u8` | unsigned 8-bit byte |
| `i64` | signed 64-bit integer |
| `u64` | unsigned 64-bit integer |
| `str` | immutable byte string descriptor |
| `Name` | heap-allocated zero-value struct reference |
| `T[]` | heap-allocated dynamic array descriptor |
| `void` | function return type only |

`if`, `while`, `!`, `&&`, and `||` operate on `bool`. Integers do not have implicit truthiness; write `x != 0` or `bool(x)`.

Integer types do not implicitly mix. Untyped integer literals may adapt to a clear target type when the literal is representable. Negative literals do not implicitly adapt to unsigned types.

Same-width integer conversions such as `i64(x)` and `u64(x)` preserve the 64-bit bit pattern. Narrowing conversions such as `u8(x)` check the range at runtime and exit on failure.

## Typed Let and Zero Values

`let` supports type annotations:

```epic
let b: u8 = 1
let ok: bool
let token: Token
```

When the right-hand side clearly determines the type, the annotation should be omitted.

`let x: T` without an initializer creates a zero value. For scalar types that is `0` or `false`. For `str`, arrays, and structs, the variable holds a non-null descriptor/object whose fields are zeroed; `str.data` and `array.data` may be `0` when their length is `0`.

Length, capacity, indexes, and offsets use `i64`, following Go's choice that `len` and `cap` return a signed machine integer rather than an unsigned value.

## Operators

Arithmetic `+`, `-`, `*`, `/`, and `%` is checked and exits on overflow or division by zero.

Bit operations are low-level operations and are not checked:

```epic
~x
x & y
x | y
x ^ y
x << n
x >> n
x >>> n
```

`>>` is arithmetic for `i64` and logical for unsigned integers. `>>>` is always logical.

Little-endian helpers such as `u16_le` and `put_u32_le` are ordinary Epic functions in v1. Programs that need them should write them with `u8[]`, `u64`, checked indexing, and bit operations.

## Compound Assignment

v1 supports compound assignment for assignable variables, fields, and subscripts:

```epic
x += 1
node.count -= n
xs[i] <<= 1
```

Supported operators are `+=`, `-=`, `*=`, `/=`, `%=`, `<<=`, `>>=`, `>>>=`, `&=`, `|=`, and `^=`.

The left-hand side is evaluated once, then its old value is combined with the right-hand side and written back to the same target. `str += str` performs string concatenation. Array concatenation and boolean compound assignment are not supported.

## For-In Ranges

v1 supports a deliberately narrow integer range loop:

```epic
for i in start:end {
    putc(i)
}
```

The first version only supports half-open ascending ranges. It evaluates `start` and `end` once before the loop, then runs while `i < end` and increments `i` by `1` after each iteration. If `start >= end`, the body runs zero times.

This is intended to shorten the common manual counter-loop shape. It does not support array or string iteration, reverse ranges, custom steps, or block-scoped loop variables. For now, the loop variable follows the compiler's existing function-local variable behavior.

In range loops, `continue` jumps to the loop increment before re-checking the end bound.

## String Operations

String equality is already supported through `==`, so v1 does not add a duplicate `str_eq` builtin.

The v1 string additions are:

| Operation | Meaning |
| --- | --- |
| `str_starts_with(s: str, prefix: str): i64` | true when `s` starts with `prefix` |
| `str_find(s: str, needle: str): i64` | first byte index, or `-1` when absent |
| `str_trim(s: str): str` | trim leading and trailing ASCII whitespace |

These operations are byte-oriented like v0 strings. Unicode string semantics remain outside v1.

## Indexing and Slices

v1 adds bounds checks to ordinary indexing:

```epic
let c = s[i]
let x = xs[i]
xs[i] = x
```

If `i < 0` or `i >= len`, the program dies immediately.

String indexing returns `u8`, not a one-byte `str`:

```epic
let c = s[i]
let one = s[i:i + 1]
```

Use a slice when a `str` result is needed.

v1 adds copy slice syntax for strings and arrays:

```epic
let a = s[start:end]
let b = s[start:]
let c = s[:end]
let d = s[:]

let xs2 = xs[start:end]
let ys = xs[:]
```

Slice ranges are half-open: `[start, end)`.

The initial semantics are strict:

- omitted `start` means `0`
- omitted `end` means `.len`
- `start < 0` dies
- `end < 0` dies
- `start > end` dies
- `end > len` dies
- successful slices allocate and copy

`str_sub` is not needed when slice syntax exists.

## Arrays and Byte Buffers

v1 keeps the v0 allocation rule: `new T[n]` creates an empty array with capacity for at least `n` elements. It does not create an array whose length is `n`.

The v1 array extension surface is:

```epic
extend(dst: T[], src: T[]): void
```

`extend` appends all elements of `src` to `dst` in order. It snapshots `src.data` and `src.len` before growing `dst`, so `extend(xs, xs)` appends the original contents once. It mutates `dst` and does not allocate a separate result array for expression-style concatenation. v1 does not add generic `T[] + T[]` list addition.

Like `push`, `extend` is a reserved builtin name.

## Length and Capacity

v1 adds builtin functions for length and capacity:

```epic
let n = len(s)
let m = len(xs)
let c = cap(xs)
```

Supported forms:

| Builtin | Meaning |
| --- | --- |
| `len(s: str): i64` | string byte length |
| `len(xs: T[]): i64` | array element count |
| `cap(xs: T[]): i64` | array capacity |

`cap(str)` is invalid.

`len` and `cap` are reserved builtin names; user code cannot define functions with those names.

The low-level `.data`, `.len`, and `.cap` fields become deprecated escape hatches in v1. They remain allowed because compiler sources still depend on them and the language has no module/internal boundary yet. New ordinary code should use `len()`, `cap()`, checked indexing, and slice syntax instead.

## Binary Support

v1 changes file IO from text strings to raw bytes:

```epic
read_file(path: str): u8[]
write_file(path: str, data: u8[]): i64
str(bytes: u8[]): str
bytes(s: str): u8[]
```

Ordinary source loading becomes explicit:

```epic
let source = str(read_file(path))
```

`read_file` returns an empty `u8[]` on failure, matching the v0 happy-path style without introducing `Result` or exceptions.

`str(u8[])` copies the full array length and appends a trailing NUL for C compatibility. It does not scan for interior NUL bytes in v1; if such bytes are present, C APIs observe the string only up to the first NUL.

Epic `str` remains length-carrying and NUL-terminated. Even an empty string may have `data = 0` when `len = 0`; runtime and builtin boundaries must accept that representation without passing a null buffer to WinAPI for non-zero length operations.

The v1 binary surface is enough to write the current single-object PE64 linker in Epic as `link.ep`.

## Deferred Map Shape

If v1 later adds maps, the current preferred shape is:

```epic
let ids = new map[str]i64
ids["main"] = 1
let id = ids["main"]
```

Tentative semantics:

- key type is fixed to `str`
- value type is explicit: `map[str]T`
- `m[key] = value` inserts or overwrites
- `m[key]` returns the value type's zero value when the key is absent
- `map_has(m, key): i64` distinguishes absence from stored zero values

This section is intentionally non-committal until the earlier v1 work clarifies whether maps materially improve the compiler sources.
