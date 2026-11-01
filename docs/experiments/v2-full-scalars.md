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

- **Resolved in the strict-`u8` follow-up below:** v2 previously allowed
  `i64 -> u8` narrowing and `u8 -> i64` read promotions. These have now been
  removed from v2's semantics; successor v3 source and v2 tests use explicit
  `u8(...)` / `i64(...)` casts. This does **not** rewrite the independent v3
  compiler's own legacy language semantics, which require separate analysis.
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

## Outcome and next decision (original experiment conclusion)

This is a **positive feasibility result** for moving scalar types to v2 and
an explicit measurement of the maintenance cost. It does not yet establish a
net simplification: the remaining `u8`/condition bridges and duplicated later
implementations still exist. The branch must remain experimental until we
have a specific plan for eliminating or archiving those redundant generations,
with a before/after maintained-LOC and full-bootstrap comparison.

## Follow-up review: actual compiler adoption and LOC (2026-11-01)

**Historical decision (superseded by the strict-`u8` cleanup below): defer
removal of the legacy `u8` implicit-conversion bridge and avoid a broad v3
source rewrite for now.** This is not acceptance of the bridge
as permanent language semantics; it is a prioritization decision. No compiler
semantics or test code were changed in this follow-up.

A read-only audit of `src/*.ep` identifiers on canonical `main` (counting type
names in code, excluding quoted strings and comments) found:

| Compiler source | `i64` | `u8` | New scalar names `i8/i16/u16/i32/u32/u64/bool` |
| --- | ---: | ---: | ---: |
| v2 | 380 | 30 | 0 |
| v3 | 427 | 41 | **0** |
| v4 | 287 | 89 | **68** (`bool` 59, `u32` 8, `i32` 1) |

These are **lexical token counts, not type-checked usage counts**, and include
the occurrences of the basic `i64`/`u8` type names in the compiler's
implementation. The important finding is that v3's **own compiler source**
does not actually dogfood the new scalar types; it *implements their support*
for the next generation. Moving that support into v2 therefore does not
magically remove v3's semantic analyzer, code generator, or assembler support
for the same types. The v3 compiler must still be able to compile v4 source.

The experimentally instrumented v2 compiler identified **14 conversion events
at 14 source locations** when compiling v3: 11 `i64 -> u8` narrowings and
three `u8 -> i64` read promotions (concentrated in `asm.ep`, `pe.ep`,
`codegen.ep`, `lexer.ep`). The v2 E2E bundle produced 25 promotion events
across 13 source lines in 12 cases, and its GC stress test had one narrowing.
These are finite migration sites, but cleaning them only changes source and
removes legacy bridges; it does not itself yield large source reductions.

Current experiment compiler LOC are about v2 **6,598** (main: 6,065), v3
**8,946** (main: 8,945), and v4 **9,313** (unchanged). This is about **+534
lines** across v2-v4, not a demonstrated reduction. The primary benefit so far
is a more coherent *earlier language contract*, not a smaller live bootstrap.

**Revisit when** one of the following is true: (a) strict `u8` rules are needed
for real user-facing correctness, (b) v3 source is being edited for another
substantial reason and the 14 sites can be migrated naturally, or (c) an
architectural experiment demonstrates that code can actually be removed from
the maintained compiler chain, with all five generations and fixed-point tests
still passing. No version deletion or forced v3 rewrite is implied by this
record.

## Follow-up implementation: strict v2 `u8` conversions (2026-11-01)

**Decision: implement the narrow migration now.** The 14 audited v3 source
sites are small and localized enough to remove the transitional rules, rather
than keep them as permanent exceptions. This supersedes the prior deferral.

- Removed `sema_promote` and the `i64 -> u8` branch of `sema_assignable` from
  the **experimental v2 compiler**. A `u8` array read, pointer read, product
  field, function return, or `pop(u8[])` now has type `u8` rather than silently
  becoming `i64`. Implicit `i64` assignment into `u8` is rejected.
- Updated the 14 source sites across `v3/src/asm.ep`, `codegen.ep`,
  `lexer.ep`, and `pe.ep` to request explicit `u8(...)` truncation or
  `i64(...)` widening. The v3 source still builds with the v2 compiler.
- Updated impacted v2 E2E, GC stress and isolated-compiler fixture cases.
  Unsuffixed integer literals remain contextually typed; e.g. `push(bytes, 42)`
  is not an implicit conversion from an already-typed `i64` expression.
- Added semantic rejection tests covering `u8 -> i64` argument/return and
  `i64 -> u8` subscript-assignment/`push` conversions.
- The previous `i64` condition-compatibility behavior **remains** as a
  separate issue. This cleanup changes v2's byte conversions only, and does
  not backport strict byte rules into the distinct **v3 language implementation**.
  In particular, v3's own `sema.ep` still contains historical `u8`/`i64`
  compatibility, which is not needed to compile v3 from strict v2.

Compiler source LOC after this cleanup: approximately **6,586** for v2
(main: 6,065), **8,946** for v3, and **9,313** for v4. This is a small
semantic simplification, **not** evidence that front-loading types reduced
cumulative maintained LOC or the number of bootstrap generations.

Verification: `python test.py` returns **ALL 5 GENERATIONS PASS** (v0,
v1, v2, v3, v4); byte-identical bootstrap fixed points are preserved.
Experimental v2 additionally passes **80 E2E** cases, **72 semantic rejection**
cases, its isolated-compiler tests, and GC stress/small tests. The negative
cases specifically reject implicit typed `u8`/`i64` conversions. No changes
are merged into canonical `main` as part of this experiment.

## Follow-up: remove v3 scalar-compatibility bridges (2026-11-01)

**Completed on the experiment branch; not merged into `main`.** The v3
compiler no longer accepts implicit `i64 -> u8`, `u8 -> i64`, or
`bool -> i64` scalar assignment/call/return conversions. It no longer accepts
mixed `u8`/`i64` arithmetic, mixed `bool`/`i64` equality, cross-type joins,
`i64`/`u8` conditions, non-`bool` `!`, or mixed-type boolean operators.
Unsigned/signed integer operations still require matching operand types,
except for the already-defined integer shift-count rule. Unsuffixed literals
continue to receive types from their immediate contexts; explicit conversions
remain available.

This removes `sema_legacy_i64_pair` entirely, simplifies v3's integer
comparison and code generation, and replaces old conditional expressions in
v3's positive tests with explicit comparisons or actual `bool` values. It also
updates the few v3 GC, isolated-compiler, and assembler fixtures that exercised
implicit byte conversion. The assembler integration tests recompile portions
of the v3 compiler with v3 itself, so `v3/src/utils.ep` and two `asm.ep` sites
now use source expressions valid under *both* the v2 bootstrap and strict v3.

**`ptr` is intentionally unchanged.** In particular, v3 still permits the
historical integer-to-`ptr` argument conversion; this is a separate FFI and
null-pointer design question, not an unexamined part of the scalar cleanup.
A direct `GetFileType(0)` Win32 call compiled and ran successfully after the
change. No `ptr` design decision is made here.

Verification: `python test.py` produced **`ALL 5 GENERATIONS PASS`** for
v0–v4, including v3's **105 passing E2E** cases, **81 semantic diagnostics**
(including 12 new strict-scalar rejection cases), assembler integration,
GC stress/views, and the isolated compiler tests. The v1 and v4 bootstrap
fixed-point comparisons remained byte-identical. After this cleanup, v3's
compiler-source LOC (`src/*.ep`) is approximately **8,897**, down from
**8,946** on the preceding experimental revision (49 fewer lines). v2 stays
at 6,586; v4 stays at 9,313. These are compiler-only physical source lines.

The next separate design discussion is `ptr` (null representation, integer
conversions, precise Win64 ABI signatures, and pointer-lifetime rules). Nothing
in this scalar cleanup presupposes that decision.
