# Epic language design

This document describes the current Epic language. The former v0/v1/v2 notes
have been folded into the active design; their source snapshots remain in this
directory as `design-v0.md`, `design-v1.md`, and `design-v2.md`.

## Direction

Epic is a small C-like systems language targeting Windows x64. It is designed
around whole-program compilation, explicit types at function and struct
boundaries, heap-allocated reference values for strings, structs, and dynamic
arrays, and a self-hosted compiler written in Epic.

The implementation does not preserve forward compatibility for its own sake.
When the language changes, compiler sources move with the current design.

## Current Surface

The current language includes:

- scalar types: `bool`, `u8`, `i64`, `u64`
- reference types: `str`, user structs, `T[]`
- typed `let` declarations and zero values
- explicit boolean conditions
- checked arithmetic, checked indexing, and copy slices
- bitwise and shift operators
- `if`, `else if`, `while`, `break`, `continue`, and half-open `for i in start:end`
- compound assignment for assignable variables, fields, and subscripts
- byte-oriented string helpers and byte-array file IO
- `panic` and `assert`
- struct initializers and array literals
- algebraic data types and `match`
- narrow `map[str]T`

## Bootstrap Model

The active bootstrap model is:

```text
Python reference compiler -> Epic compiler -> Epic compiler
```

The staged v0/v1 directory chain is historical. Git tags preserve that chain;
it is no longer part of the maintained source layout.
