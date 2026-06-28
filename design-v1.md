# Epic v1 design notes

v1 starts from the `v0` bootstrap anchor and intentionally does not preserve
source compatibility. The previous compiler is kept on the `v0` branch; v1
source should move with the v1 language.

## Current scope

The first v1 pass is deliberately narrow:

1. Remove semicolons.
2. Add the minimum stronger `str` operations needed by compiler code.
3. Add `len()` and `cap()` builtins.
4. Add checked indexing and copy slices for strings and arrays.
5. Prepare for splitting `codegen.ep`.
6. Revisit `map[str]T` only after the first five items show the real need.

`map` is not rejected. It is deferred because it should be justified by actual
compiler simplification, not by being a generally expected high-level feature.

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

## String operations

String equality is already supported through `==`, so v1 should not add a
duplicate `str_eq` builtin.

The proposed v1 string additions are:

| Operation | Meaning |
| --- | --- |
| `str_starts_with(s: str, prefix: str) -> i64` | true when `s` starts with `prefix` |
| `str_find(s: str, needle: str) -> i64` | first byte index, or `-1` when absent |
| `str_trim(s: str) -> str` | trim leading and trailing ASCII whitespace |

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

String indexing returns `i8`, not a one-byte `str`:

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
let buf = new i8[4096]
push(buf, 77)
push(buf, 90)
```

Because `new T[n]` already covers initial reservation, v1 does not need a
separate `reserve` builtin.

v1 should add array extension:

```epic
extend(dst: T[], src: T[]) -> void
```

`extend` appends all elements of `src` to `dst` in order. It mutates `dst` and
does not allocate a separate result array for expression-style concatenation.
v1 should not add generic `T[] + T[]` list addition.

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
| `len(s: str) -> i64` | string byte length |
| `len(xs: T[]) -> i64` | array element count |
| `cap(xs: T[]) -> i64` | array capacity |

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

The current Python linker depends on operations Epic does not yet expose well:

- reading a file as raw bytes
- writing raw bytes
- mutable byte buffers with explicit length
- little-endian `u16`, `u32`, `u64`, and signed `i32` load/store helpers
- appending bytes and patching bytes at known offsets

Before committing to an Epic linker, v1 should first add enough byte-buffer
surface to make the port direct and testable. A possible minimal direction:

```epic
read_file(path: str) -> i8[]
write_file(path: str, data: i8[]) -> i64
str(bytes: i8[]) -> str
bytes(s: str) -> i8[]
u16_le(buf: i8[], off: i64) -> i64
u32_le(buf: i8[], off: i64) -> i64
u64_le(buf: i8[], off: i64) -> i64
put_u16_le(buf: i8[], off: i64, x: i64) -> void
put_u32_le(buf: i8[], off: i64, x: i64) -> void
put_u64_le(buf: i8[], off: i64, x: i64) -> void
```

This is a breaking change from v0: file IO should operate on bytes, not text.
Compiler source loading should become explicit:

```epic
let source = str(read_file(path))
```

`read_file` returns an empty `i8[]` on failure, matching the v0 happy-path style
without introducing `Result` or exceptions.

`str(i8[])` copies the full array length and appends a trailing NUL for C
compatibility. It does not scan for interior NUL bytes in v1; if such bytes are
present, C APIs will observe the string only up to the first NUL. That is the
caller's responsibility in the v1 happy path.

Epic `str` remains length-carrying and NUL-terminated. Even an empty string
should have non-null data pointing at a NUL byte. The implementation may later
use a global empty string/data object for performance, but `data = 0` is not the
empty string representation.

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
- `map_has(m, key) -> i64` distinguishes absence from stored zero values

This section is intentionally non-committal until the earlier v1 work clarifies
whether maps materially improve the compiler sources.
