# Epic v2 implementation notes

v2 inherits the v1 implementation model: whole-program source merging,
Windows x64 NASM output, Win32 runtime helpers, Epic linker usage, and
example-driven acceptance tests.

Treat `../v1/impl.md` as the baseline. This file records implementation deltas
planned for v2.

## Bootstrap and Toolchain

The root bootstrap script produces these anchors:

```text
build/v0.exe
build/v1.exe
build/link.exe
```

It also syncs these v2-local tools and anchors:

```text
v2/tools/nasm.exe
v2/build/v1.exe
v2/build/link.exe
```

v2 tests run from `v2/` and use `build/v1.exe` as the previous compiler anchor.
The v2 compiler driver links through `build/link.exe`.

## Panic and Assert

Parser:

- add `Panic` and `Assert` statement nodes.
- attach source line information from the keyword token.
- parse `assert expr` and `assert expr, "message"`.

Codegen:

- `panic` emits message output and exits non-zero.
- `assert` emits a bool type check for the condition and branches to the panic
  path on false.
- first version can share the existing process-exit path used by runtime traps.

Source position output should be kept simple at first: file and line are enough.

## Initializers

Add expression nodes:

```text
StructInit
ArrayLiteral
```

Struct initializer lowering:

- allocate the struct using the same heap allocation path as `new T`.
- zero-initialized allocation covers omitted fields.
- for each named field, find its struct layout entry and store the emitted
  expression into the field offset.
- reject unknown fields.
- reject duplicate fields.
- reject field type mismatch.

Array literal lowering:

- allocate the normal dynamic array header.
- set `len` and `cap` to the element count.
- allocate backing storage sized by element width.
- emit each element and store it into the backing storage.
- reject element type mismatch.

`new T[n]` remains unchanged: it creates an empty array with capacity for at
least `n`.

## ADT Lowering

ADT syntax remains visible in the front end, but layout/codegen lowers it into
synthetic struct-like layouts.

For:

```epic
type Expr {
    Empty
    IntLit { value: i64 }
    Binary { op: str, left: Expr, right: Expr }
}
```

the compiler records:

```text
Expr header:
    tag: i64
    data: &payload

Expr.Empty payload:
    empty payload layout

Expr.IntLit payload:
    value: i64

Expr.Binary payload:
    op: str
    left: Expr
    right: Expr
```

Implementation notes:

- ADT values are references to a 16-byte header object.
- header slot 0 stores the numeric tag.
- header slot 1 stores a pointer to a heap-allocated payload object.
- each payload layout reuses struct field layout rules.
- variant tag numbers follow declaration order.
- ADT zero value is tag `0` plus a zero-valued payload for the first variant.
- variant initializer emits header allocation, tag store, payload allocation,
  payload field stores, and data pointer store.

This two-level layout is intentionally chosen over inline max-payload storage to
reuse struct layout and keep v2 implementation simple. The extra allocation and
pointer hop are acceptable for compiler AST data.

## Match Lowering

Add statement node:

```text
Match
```

Basic-type match lowering:

- emit the scrutinee once and save it in a temp slot.
- for integer and bool cases, emit a linear compare/jump chain.
- for string cases, call the existing string equality path/helper.
- emit the selected case block, then jump to the match end label.
- if no case matches, jump to `else` or emitted panic.

ADT match lowering:

- emit the scrutinee once and save the ADT header pointer.
- load the tag from header slot 0.
- emit a linear compare/jump chain over variant tags.
- for a matched variant, load `data` from header slot 1.
- bind named payload fields by loading from the payload layout offsets into
  local slots.
- emit the case block, then jump to the match end label.
- if no case matches, jump to `else` or emitted panic.

Static checks:

- supported scrutinee type only.
- literal case type matches scrutinee type.
- duplicate literal case rejection.
- ADT case variant belongs to the scrutinee ADT.
- duplicate ADT variant rejection.
- payload binding fields exist.
- duplicate payload binding rejection.
- `else` is last.

No exhaustiveness checking is planned for the first v2 match implementation.

## Map Lowering

`map[str]T` should be implemented narrowly.

Likely first representation:

```text
map header:
    entries: &_arr_entry
    len: i64
    cap: i64

entry:
    key: str
    value: T
    used: bool
```

The first implementation may use linear search if that gets compiler code
moving quickly. A hash-table implementation can replace it later without
preserving compatibility.

Required operations:

- `new map[str]T`
- `m[key] = value`
- `m[key]`
- `map_has(m, key)`

Absent lookup returns the zero value of `T`.
