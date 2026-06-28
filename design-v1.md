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

The low-level `.data`, `.len`, and `.cap` fields should become deprecated escape
hatches in v1. They remain allowed during the first v1 pass because compiler
sources still depend on them and the language has no module/internal boundary
yet. New ordinary code should use `len()`, `cap()`, checked indexing, and slice
syntax instead.

## Codegen split

`codegen.ep` is large enough that v1 should try to split it after the syntax
and string improvements land.

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
