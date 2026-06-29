# Epic v2 language design

v2 starts from the v1 language. Its first feature set is aimed at making the
compiler source easier to write and maintain, not at general language
completeness.

Treat `../v1/design.md` as the inherited baseline. This document records v2
deltas only.

## Scope

Initial v2 features:

- `panic` and `assert`
- struct and array initializers
- algebraic data types
- `match`
- `map[str]T`

These features should serve compiler code first. Do not preserve forward
compatibility for its own sake.

## Panic and Assert

`panic` and `assert` are built-in statements:

```epic
panic "unreachable"

assert ok
assert token.kind == "ID", "expected identifier"
```

Rules:

- `panic` prints source position and message, then exits non-zero.
- `assert` requires a `bool` condition.
- failed `assert` prints source position and optional message, then exits
  non-zero.
- assertions are always enabled in v2.
- `panic` is a statement in the first version; v2 does not add a bottom type.

## Initializers

v2 uses brace initializers, not call-like construction. Epic does not have
constructors; constructor-like type calls are intentionally avoided.

Struct initializer:

```epic
struct Pos {
    line: i64
    col: i64
}

let p = Pos { line: 3, col: 9 }
let q = Pos { line: 3 }
let z = Pos {}
```

Rules:

- fields are named, not positional.
- field order is irrelevant.
- omitted fields get their zero value.
- unknown fields are compile errors.
- duplicate fields are compile errors.

Array literal:

```epic
let xs = i64[] { 1, 2, 3 }
let bs = u8[] { 65, 66, 67 }
```

`T[] { ... }` allocates a dynamic array whose length and capacity are the
number of elements. `new T[n]` keeps its v1 meaning: allocate an empty dynamic
array with capacity for at least `n` elements.

## ADT

v2 adds algebraic data types with block syntax:

```epic
type Expr {
    Empty

    IntLit {
        value: i64
    }

    Binary {
        op: str
        left: Expr
        right: Expr
    }
}
```

Rules:

- ADTs are reference types, like existing user structs.
- the zero value of an ADT is the first variant with zero-valued payload.
- variants may have no payload fields.
- variant payload fields use the same `name: Type` shape as struct fields.
- ADT variant initializers use named brace syntax:

```epic
let e = Expr.IntLit { value: 123 }
let b = Expr.Binary { op: "+", left: a, right: c }
let empty: Expr
```

Variant initializer rules match struct initializer rules: named fields, omitted
fields get zero values, unknown and duplicate fields are compile errors.

## Match

`match` is a statement in v2. It supports basic literal cases and ADT variant
cases.

Basic type match:

```epic
match n {
    0 {
        putstr("zero")
    }

    1 {
        putstr("one")
    }

    else {
        putstr("many")
    }
}
```

Supported scrutinee types for basic cases:

- `i64`
- `u64`
- `u8`
- `bool`
- `str`

ADT match:

```epic
match e {
    Expr.IntLit { value } {
        puti(value)
    }

    Expr.Binary { op, left, right } {
        putstr(op)
    }

    else {
        panic "unknown expr"
    }
}
```

Rules:

- case bodies are blocks.
- `else` is optional, but must be the last case when present.
- no fallthrough.
- literal case values must match the scrutinee type.
- duplicate literal cases are compile errors.
- ADT cases must name a variant of the scrutinee ADT.
- duplicate ADT variant cases are compile errors.
- ADT payload patterns are named.
- `{ value }` binds the payload field `value` to a local with the same name.
- `{ value: n }` binds the payload field `value` to local `n`.
- payload patterns may bind only the fields they need.
- unknown and duplicate payload bindings are compile errors.
- v2 does not do exhaustiveness checking initially.
- if no case matches and no `else` exists, runtime `panic` is emitted.

v2 does not initially support match guards, range cases, combined cases such as
`1 | 2`, nested patterns, or match expressions.

## Map

v2 adds a narrow map type:

```epic
let ids = new map[str]i64
ids["main"] = 1

let id = ids["main"]
let ok = map_has(ids, "main")
```

Rules:

- key type is fixed to `str`.
- value type is explicit: `map[str]T`.
- `m[key] = value` inserts or overwrites.
- `m[key]` returns the value type's zero value when absent.
- `map_has(m, key)` distinguishes absence from stored zero values.

v2 does not initially support non-string keys, deletion, map iteration, or
optional/result lookup.

## Implementation Order

Preferred implementation order:

1. `panic`
2. `assert`
3. struct initializer
4. array literal
5. ADT definition and initializer
6. basic-type `match`
7. ADT `match`
8. `map[str]T`
