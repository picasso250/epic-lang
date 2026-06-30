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
- `new StructName {}` for zero/default struct initialization
- `new StructName { field: value }` for named struct initialization
- `new TypeName.Variant` and `new TypeName.Variant { field: value }` for ADT values
- `new T[] { ... }` for dynamic array literals
- `new T[n]` for array allocation (remains)
- `new map[str]T` for map allocation (remains)
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

## Struct Initialization

`new StructName {}` initializes a struct with all fields set to their
zero/default values (heap-allocated). Named fields can be supplied with
`new StructName { field: value }`; omitted fields keep their zero/default
values.

ADT values use the same constructor marker. Payload variants are written as
`new TypeName.Variant { field: value }`; no-payload variants are written as
`new TypeName.Variant`.

Dynamic array literals are written as `new T[] { ... }`. `new T[n]` (array
allocation) and `new map[str]T` (map allocation) remain valid in the current
language.

## Bootstrap Model

The active bootstrap model is:

```text
Python reference compiler -> Epic compiler -> Epic compiler
```

The staged v0/v1 directory chain is historical. Git tags preserve that chain;
it is no longer part of the maintained source layout.

## Brace Disambiguation

Braces `{ ... }` serve different roles depending on grammatical position,
not on identifier spelling or capitalization.

- **Block/body position**: `{ ... }` is a block or body only where the
grammar explicitly expects one:
  - function body
  - `if` then block
  - `else` block
  - `while` block
  - `for` block
  - struct body
  - type body
  - `match` body
  - `match` case body (after the colon)

- **Expression/pattern position**: `new ... { ... }` is an initializer, and
postfix `{ ... }` is a pattern-payload candidate in match patterns, never a
block. The parser may create init/pattern candidate AST nodes from token shape
and syntactic context, but legality belongs to semantic and codegen checks:
  - the target must be a real struct, type, or ADT variant
  - fields/payload bindings must exist and be valid
  - types must be compatible

## Match Case Colon Rule

Every `match` case must use a colon to separate the pattern from its body:

```text
pattern: { ... }
else:    { ... }
```

ADT patterns with payload use the same colon form:

```text
Expr.IntLit { value: n }: { ... }
```

**Rationale.** This rule eliminates the old double-brace ambiguity
(`Expr.IntLit { value: n } { ... }`), removes the need for
uppercase-name heuristics, and makes the match syntax uniform across all
pattern forms.
