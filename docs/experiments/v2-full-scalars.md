# Experiment: native fixed-width scalar types in v2

Status: **working, experimentally verified, not accepted for canonical main**
Date: 2026-11-01
Branch: `experiment/v2-full-scalars` (forked from `experiment/v2-scalar-ffi-frontload`).
Baseline main: `85e850a`.

## Question

Can v2 introduce all native scalar types earlier than the canonical v3
implementation, while v0 stays a small Python seed and v1 stays the first
self-hosted compiler? Does that reduce the *maintained* bootstrap chain, not
merely create a prettier historical feature timeline?

## Implemented and exercised in the experiment

- `bool`, `i8`, `u8`, `i16`, `u16`, `i32`, `u32`, `i64`, and `u64` are accepted as
  ordinary value, local, parameter, return, field, and array-element types.
- Explicit integer conversions `T(expr)`, literal suffixes such as `42u32`,
  `true`/`false`, signed and unsigned arithmetic and comparisons, integer
  wrapping at the declared width, sign/zero extension, and literal range
  checks, including `18446744073709551615u64` and `-9223372036854775808i64`.
- Unsuffixed integer literals gain their type from immediately expected
  parameter/assignment/return types or a directly adjacent typed operand.
- Narrow values occupy natural 1/2/4/8-byte sizes in product fields and array
  storage, with natural product-field alignment; indexing, dynamic array
  reallocation, `push`, and `pop` work with the new strides. The v2 internal
  assembler now has the necessary 16-bit addressing/instruction support and
  unsigned condition codes, without importing v3's entire assembler.
- Native `extern` parameters are checked at exact scalar widths; narrow return
  values keep their declared types rather than being silently widened to
  `i64`. The v3 compiler source uses explicit conversions and correct
  `DWORD`/`BOOL` declarations for selected Win32 APIs.
- v2 compiler **source** remains legal in the v1 language subset, preserving
  the real bootstrap dependency instead of dogfooding its own changes.

## Known compatibility debt and intentionally limited scope

- **Legacy `u8` bridge remains.** Existing v2 GC tests and large parts of the
  v3 compiler source write `i64` values into `u8` arrays or fields. The v2
  semantic checker still accepts `i64 -> u8` at ordinary assignment boundaries,
  while explicit `extern` integer lanes remain exact. `u8` reads through
  certain container/field paths and `pop` retain the historical promotion to
  `i64`. A strict full scalar language must eventually retire these exceptions
  through a separate migration of successor compiler sources and tests.
- **Legacy `i64` condition bridge remains.** Existing programs still use
  integer conditions and obtain `i64`-typed comparison results in older paths,
  rather than universally requiring `bool` as modern v3/v4 code does.
- Contextual numeric typing is deliberately limited to immediate contexts.
  Arbitrary nested expressions are not fully bidirectionally type-checked.
  Explicit casts are available for unsupported inference cases.
- `ptr` still has v2-era source restrictions; this experiment does not import
  v4's public `ptr` conversions, callbacks or lifetime mechanisms.
- No changes to `read_file`, exception semantics, `GetFileSize` assembly, GC,
  v0, or v1; no change to floating-point or aggregate native ABI support.
- The added compiler features have broad directed tests, but do not constitute
  proof of all arithmetic, bounds and ABI edge cases. The v3 historical type
  checker/code generator remain present: this experiment **adds capability**
  rather than removing their source code wholesale.

## Evidence (2026-11-01)

New v2 E2E scenarios cover scalar math and wrap, unsigned division/comparison,
`bool`, precise mixed-width product storage, array stride/copy/growth/pop,
negative signed values, `u64` maximum, signed `i64` minimum, and contextual
literal typing. New negative semantics check out-of-range suffixes, mixed
integer arithmetic, boolean arithmetic, reserved scalar type names and invalid
implicit FFI narrowing.

`python test.py` passes **v0, v1, v2, v3, v4** with byte-identical fixed points.
The current v2 compiler has approximately **6,598 physical lines** in
`src/*.ep`, compared with **6,065** on main (approximately +533). v3 is
approximately 8,946 lines versus 8,945; v4 remains approximately 9,313.
These are source line counts, not executable complexity or semantic quality.
**The maintained cumulative source has not become smaller yet.**

## Version-count / maintainability proposal (not implemented)

Separate *history* from the *live bootstrap chain*:

1. Preserve historical checkpoints in git tags/docs instead of needing a
   separate actively maintained compiler for every tidy feature milestone.
2. Keep the **minimum trusted compiler chain that can produce today's compiler
   from source**, plus one actively maintained language/compiler implementation.
3. Shorten the executable chain only after demonstrating that an earlier stage
   can actually compile the next stage's source; renaming `vN` folders does not
   remove compiler dependencies. Today v2 still cannot compile the v4 compiler
   source directly, because v4 source uses features implemented by v3.
4. Prioritize removal of duplicated semantic mechanisms, obsolete bridges and
   redundant integration tests over the aesthetics of a numbered narrative.
5. Only change the canonical directory layout when the result demonstrably
   reduces bootstrap cost, maintained source, and cognitive load without losing
   a reproducible fixed point or trustworthy historical tests.

## Outcome and next decision

This is a **positive feasibility result** for moving scalar types to v2 and
an explicit measurement of the maintenance cost. It does not yet establish a
net simplification: the remaining `u8`/condition bridges and duplicated later
implementations still exist. The branch must remain experimental until we
have a specific plan for eliminating or archiving those redundant generations,
with a before/after maintained-LOC and full-bootstrap comparison.
