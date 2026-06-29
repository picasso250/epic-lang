# Epic v1 design notes

v1 starts from the `v0` bootstrap anchor and intentionally does not preserve
source compatibility. The previous compiler is kept on the `v0` branch; v1
source should move with the v1 language.

## Bootstrap boundary

The v1 compiler sources are still compiled by the v0 bootstrap anchor. That
means `epic.ep`, `lexer.ep`, `parser.ep`, `codegen_support.ep`, and
`codegen.ep` must stay in the source shape accepted by v0 until a future v2
source tree is compiled by the v1 compiler.

v1 features can and should be tested with examples, but they should not be
used to rewrite the v1 compiler sources themselves. The dogfooding point for
v1 syntax and builtins is v2-src, not the current v1-src.

## Current scope

The first v1 pass is deliberately narrow, but v1 itself is allowed to break
source compatibility whenever that simplifies the language:

1. Remove semicolons.
2. Add the minimum stronger `str` operations needed by compiler code.
3. Add `len()` and `cap()` builtins.
4. Add checked indexing and copy slices for strings and arrays.
5. Prepare for splitting `codegen.ep`.
6. Revisit `map[str]T` only after the first five items show the real need.

`map` is not rejected. It is deferred because it should be justified by actual
compiler simplification, not by being a generally expected high-level feature.

## v1 breaking type and operator reset

v1 removes the user-facing signed byte type. `u8` is the byte type used by
strings, byte buffers, file IO, and character literals. The user-facing scalar
types are:

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

`if`, `while`, `!`, `&&`, and `||` operate on `bool`. Integers do not have
implicit truthiness; write `x != 0` or `bool(x)`.

Integer types do not implicitly mix. Untyped integer literals may adapt to a
clear target type when the literal is representable; negative literals do not
implicitly adapt to unsigned types. Same-width integer conversions such as
`i64(x)` and `u64(x)` preserve the 64-bit bit pattern. Narrowing conversions
such as `u8(x)` check the range at runtime and exit on failure.

Arithmetic `+`, `-`, `*`, `/`, and `%` is checked and exits on overflow or
division by zero. Bit operations are low-level operations and are not checked:
`~`, `&`, `|`, `^`, `<<`, `>>`, and `>>>` operate on the fixed-width bit
pattern. `>>` is arithmetic for `i64` and logical for unsigned integers;
`>>>` is always logical.

`let` supports type annotations:

```epic
let b: u8 = 1
let ok: bool
let token: Token
```

When the right-hand side clearly determines the type, the annotation should be
omitted. `let x: T` without an initializer creates a zero value. For scalar
types that is `0` or `false`. For `str`, arrays, and structs, the variable holds
a non-null descriptor/object whose fields are zeroed; `str.data` and
`array.data` may be `0` when their length is `0`.

Length, capacity, indexes, and offsets use `i64`, following Go's choice that
`len` and `cap` return a signed machine integer rather than an unsigned value.

The system-call escape hatch is `os.*`, not `sys.*`. It still exposes Win32
names directly, for example `os.ExitProcess(1)`.

Little-endian helpers such as `u16_le` and `put_u32_le` are no longer compiler
builtins. Programs that need them should write ordinary Epic helper functions
using `u8[]`, `u64`, checked indexing, and bit operations.

## Semicolon removal

v1 removes statement semicolons completely. There is no optional-semicolon
compatibility mode.

The lexer should preserve newline tokens for the parser. Parser rules should
use newlines as ordinary statement terminators for simple statements:

```epic
let x = 1
x = x + 2
return x
```

Initial constraints:

- ordinary statements are one line each
- blank lines are allowed and skipped
- `{` and `}` may appear around newlines naturally
- expression-internal arbitrary newlines are not part of the first pass
- no JavaScript/Go-style automatic semicolon insertion system

This keeps the migration mechanical and keeps parser behavior explicit.

## Else-if chains

v1 supports `else if` as syntax sugar for nested `if` statements in the `else`
branch:

```epic
if x == 1 {
    putstr("one")
} else if x == 2 {
    putstr("two")
} else {
    putstr("many")
}
```

This does not add a new runtime control-flow construct. The parser lowers it
to the same AST shape as `else { if ... }`, keeping codegen unchanged.

## Loop control

v1 supports `break` and `continue` as statement-only loop control:

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
not expressions, cannot be chained, and are rejected outside loops. In range
loops, `continue` jumps to the loop increment before re-checking the end bound.

## For-in ranges

v1 supports a deliberately narrow integer range loop:

```epic
for i in start:end {
    putc(i)
}
```

The first version only supports half-open ascending ranges. It is equivalent to
evaluating `start` and `end` once before the loop, then running while `i < end`
and incrementing `i` by `1` after each iteration. If `start >= end`, the body
runs zero times.

This is intended to shorten the common manual counter-loop shape in compiler
sources. It does not yet support array or string iteration, reverse ranges,
custom steps, or block-scoped loop variables. For now, the loop variable follows
the compiler's existing function-local variable behavior.

## Compound assignment

v1 supports compound assignment for assignable variables, fields, and
subscripts:

```epic
x += 1
node.count -= n
xs[i] <<= 1
```

Supported operators are `+=`, `-=`, `*=`, `/=`, `%=`, `<<=`, `>>=`, `>>>=`,
`&=`, `|=`, and `^=`. The left-hand side is evaluated once, then its old value
is combined with the right-hand side and written back to the same target.
`str += str` performs string concatenation. Array concatenation and boolean
compound assignment are not supported.

## String operations

String equality is already supported through `==`, so v1 should not add a
duplicate `str_eq` builtin.

The v1 string additions are:

| Operation | Meaning |
| --- | --- |
| `str_starts_with(s: str, prefix: str): i64` | true when `s` starts with `prefix` |
| `str_find(s: str, needle: str): i64` | first byte index, or `-1` when absent |
| `str_trim(s: str): str` | trim leading and trailing ASCII whitespace |

These operations are byte-oriented like v0 strings. Unicode string semantics
remain outside the v1 first pass.

## Indexing and slices

v1 should add bounds checks to ordinary indexing:

```epic
let c = s[i]
let x = xs[i]
xs[i] = x
```

If `i < 0` or `i >= len`, the program dies immediately. The current v0 codegen
does not check this; it emits direct memory loads and stores.

String indexing returns `u8`, not a one-byte `str`:

```epic
let c = s[i]
let one = s[i:i + 1]
```

Use a slice when a `str` result is needed.

v1 should also add copy slice syntax for strings and arrays:

```epic
let a = s[start:end]
let b = s[start:]
let c = s[:end]
let d = s[:]

let xs2 = xs[start:end]
let ys = xs[:]
```

Slice ranges are half-open: `[start, end)`.

The initial semantics are deliberately strict:

- omitted `start` means `0`
- omitted `end` means `.len`
- `start < 0` dies
- `end < 0` dies
- `start > end` dies
- `end > len` dies
- successful slices allocate and copy

`str_sub` is not needed when slice syntax exists.

## Arrays and byte buffers

Epic arrays keep the v0 allocation rule:

```epic
let xs = new i64[1024]
```

This creates an empty array with capacity for at least `1024` elements. It does
not create an array whose length is `1024`. The initial `len(xs)` is `0`.

This is intentionally different from Go-like indexed allocation and should stay
explicit in documentation because it affects byte-buffer code. To create output,
append elements:

```epic
let buf = new u8[4096]
push(buf, 77)
push(buf, 90)
```

Because `new T[n]` already covers initial reservation, v1 does not need a
separate `reserve` builtin.

v1 should add array extension:

```epic
extend(dst: T[], src: T[]): void
```

`extend` appends all elements of `src` to `dst` in order. It snapshots
`src.data` and `src.len` before growing `dst`, so `extend(xs, xs)` appends the
original contents once. It mutates `dst` and does not allocate a separate result
array for expression-style concatenation. v1 should not add generic `T[] + T[]`
list addition.

Like `push`, `extend` is a reserved builtin name.

## Length and capacity

v1 should add builtin functions for length and capacity:

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
`len` and `cap` are reserved builtin names; user code cannot define functions
with those names.

The low-level `.data`, `.len`, and `.cap` fields should become deprecated escape
hatches in v1. They remain allowed during the first v1 pass because compiler
sources still depend on them and the language has no module/internal boundary
yet. New ordinary code should use `len()`, `cap()`, checked indexing, and slice
syntax instead.

## Binary support and linker replacement

Replacing `link.py` with Epic code would be a valuable v1 stretch goal because
binary parsing and patching are core systems-language capabilities.

The current Python linker depends on byte-buffer operations that v1 now exposes
directly:

- reading a file as raw bytes
- writing raw bytes
- mutable byte buffers with explicit length
- little-endian helper functions written in Epic with `u8[]`, `u64`, and bit operations
- appending bytes and patching bytes at known offsets

The current minimal byte-buffer surface is:

```epic
read_file(path: str): u8[]
write_file(path: str, data: u8[]): i64
str(bytes: u8[]): str
bytes(s: str): u8[]
```

This is a breaking change from v0: file IO should operate on bytes, not text.
Ordinary source loading should become explicit:

```epic
let source = str(read_file(path))
```

The current v1 compiler sources are still compiled by the v0 bootstrap anchor,
so they may temporarily rely on bootstrap-era byte/string layout details. New
v1 user code should use explicit `str(read_file(path))` conversion when it
needs text.

`read_file` returns an empty `u8[]` on failure, matching the v0 happy-path style
without introducing `Result` or exceptions.

`str(u8[])` copies the full array length and appends a trailing NUL for C
compatibility. It does not scan for interior NUL bytes in v1; if such bytes are
present, C APIs will observe the string only up to the first NUL. That is the
caller's responsibility in the v1 happy path.

Little-endian load/store helpers are ordinary Epic functions. Checked indexing
provides their bounds checks.

Epic `str` remains length-carrying and NUL-terminated. Even an empty string
may have `data = 0` when `len = 0`; runtime and builtin boundaries must accept
that representation without passing a null buffer to WinAPI for non-zero
length operations.

The linker should not block the first v1 syntax/string/indexing pass. It should
be considered after byte-buffer support exists, and it can become the proof that
Epic is ready for binary tooling.

## Codegen split

`codegen.ep` is large enough that v1 should try to split it after the syntax
and string improvements land.

The first split moved shared codegen support into `codegen_support.ep`:
emitter state, low-level assembly output helpers, runtime helper emission, and
type helpers. `codegen.ep` remains the core emission file while later splits
can carve expression, statement, layout, and program emission along existing
function boundaries.

The split should be driven by existing compiler boundaries rather than a new
module system. Candidate boundaries:

- emitter state and low-level output helpers
- type size/layout helpers
- expression emission
- statement emission
- function and program emission

The goal is to make the self-hosted compiler easier to change while staying
within the current whole-program multi-file compilation model.

## Deferred map shape

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

This section is intentionally non-committal until the earlier v1 work clarifies
whether maps materially improve the compiler sources.
