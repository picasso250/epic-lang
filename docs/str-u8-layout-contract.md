# `str` and `u8[]` Layout Contract

This document records the current string/byte-buffer decision for Epic.

## Source-level distinction

`str` remains a source-level byte-string/text type. String literals have type
`str`, string equality compares contents, and `str + str` allocates a new
concatenated `str`.

`u8[]` is a mutable byte buffer. It supports checked indexing and array mutation
operations such as `push`, `pop`, and `extend`. It does not gain string
concatenation or implicit text semantics.

The two types are intentionally distinct even though they currently share a
runtime representation.

## String operators

The retained string operator surface is:

```epic
left == right
left != right
left + right
```

Both operands must be `str`. Equality is byte-content equality. Concatenation
allocates a new header and byte region, copies the left bytes followed by the
right bytes, and does not modify either operand.

String ordering (`<`, `<=`, `>`, `>=`), `str += str`, and implicit conversion in
concatenation are not supported. Use `str(value)` or an f-string for explicit
formatting.

## Current runtime invariant

`str` and `u8[]` currently use the same runtime header layout:

```text
{ data, len, cap }
```

Therefore these explicit conversions are representation-level identity views:

```epic
str(bytes_value)   # u8[] -> str view
bytes(str_value)   # str -> u8[] view
```

They do not allocate, copy, validate UTF-8, or make data immutable. Mutating the
`u8[]` returned by `bytes(s)` mutates the shared backing storage visible through
`s` and any other aliases.

The shared layout is an implementation contract, not a statement that the two
source types are interchangeable. There is no implicit assignment conversion
between `str` and `u8[]`.

## Text model

The current `str` model is byte-oriented:

- `len(s)` counts bytes.
- String literals currently accept the documented ASCII escapes.
- `s[i]` performs checked read-only byte indexing and returns `u8`.
- String subscript assignment and compound assignment are rejected.
- `s[start:end]` returns a copied `str` slice.
- No UTF-8 validation, Unicode scalar indexing, grapheme semantics, or collation
  is defined.

A future Unicode-aware evolution may change string operations or representation,
but that is not a plan to delete the `str` source type.

## API boundary guidance

Use `str` for text values, diagnostics, labels, paths, command-line arguments,
and formatting results. Use `u8[]` for mutable buffers and arbitrary binary data.

Current zero-copy casts are useful at explicit boundaries:

- `read_file(path: str) -> u8[]`
- `write_file(path: str, data: u8[]) -> i64`
- `str(bytes) -> str`
- `bytes(str) -> u8[]`

Public APIs should preserve this semantic distinction even while the layouts are
identical.

## Non-goals

The current contract does not introduce:

- UTF-8 validation or normalization.
- Unicode ordering or locale-aware comparison.
- Immutable string literals.
- Copy-on-write aliasing.
- Automatic formatting for structs or arbitrary arrays.
- Implicit `str`/`u8[]` coercions.

This v0 branch is a bootstrap implementation. Its shared zero-copy representation
is retained so it can build the current compiler; it is not the runtime contract
of the current `dev` language implementation.
