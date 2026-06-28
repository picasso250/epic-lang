# Epic v1 design notes

v1 starts from the `v0` bootstrap anchor and intentionally does not preserve
source compatibility. The previous compiler is kept on the `v0` branch; v1
source should move with the v1 language.

## Current scope

The first v1 pass is deliberately narrow:

1. Remove semicolons.
2. Add the minimum stronger `str` operations needed by compiler code.
3. Prepare for splitting `codegen.ep`.
4. Revisit `map[str]T` only after the first three items show the real need.

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
| `str_sub(s: str, start: i64, len: i64) -> str` | byte slice copy |
| `str_trim(s: str) -> str` | trim leading and trailing ASCII whitespace |

These operations are byte-oriented like v0 strings. Unicode string semantics
remain outside the v1 first pass.

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
