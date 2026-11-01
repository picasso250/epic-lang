# Experiment: front-load native scalar FFI into v2

Branch: `experiment/v2-scalar-ffi-frontload`
Status: **partial working probe, NOT an accepted language-history correction**
Baseline: `main` at `85e850a` (2026-11-01).

## Original hypothesis

Moving v3's integer widths (`i8`–`u64`, `bool`) and native-width `extern` ABI
into v2, whose semantic checker already exists, might simplify v3/v4, reduce
bootstrap compatibility work, and preserve the v0/v1 minimal seed.

## Implemented: deliberately smaller ABI-only probe

- v2 validates `extern` declarations against signed/unsigned 8-, 16-, 32-,
  64-bit integer lanes, `ptr`, and `void` results. It rejects `str`, arrays,
  products, enums, and other invalid native argument/result categories.
- v2 emits an external call as before, but **normalizes the return register's
  defined width into an `i64` value**: unsigned results zero-extend, signed
  results sign-extend. `ptr` remains a raw machine-word value.
- For the probe only, native integer arguments accept ordinary `i64` Epic
  expressions and rely on the ABI's low-N-bit lane. This is **not** the strict
  explicitly typed parameter checking of v3/v4. It would be misleading to call
  these declarations fully typed Epic values.
- The v3 compiler driver now declares `GetTickCount64(): u64`, Win32 `DWORD`
  inputs of `CreateFileA` as `u32`, and `CloseHandle`'s result as `i32`.
  The handle return and nullable pointer inputs are still `i64` because v2's
  regular expression type system does not offer the needed pointer conversions.
- E2E: `GetSystemDefaultUILanguage(): u16`, `GetCurrentThreadId(): u32`,
  `MulDiv(i32, i32, i32): i32` including a negative result, and a `ptr`
  result passed as a `ptr` argument via `GetStdHandle`/`GetFileType`.
  Semantic negative tests reject foreign aggregates in both parameters and
  results.

## What this does NOT implement

- No `bool` as an ordinary language type; no typed integer literals or
  conversions; no fixed-width arithmetic, comparisons, local values, product
  fields, natural-width array strides, or explicit `ptr`/integer conversions.
- The `i64` ABI adapter means that `u64` values outside signed `i64` range are
  not safely usable with native unsigned comparisons, and it deliberately
  permits implicit native integer narrowing. This is proof of an ABI boundary,
  not a replacement for v3's full type system.
- Does not change `read_file`, exception semantics, `GetFileSize` runtime
  assembly, GC, or any frozen v0/v1 language semantics.

## Result and design implication

The independent ABI-only approach is feasible in v2, while keeping the
v2 compiler source in v1 syntax. It does **not** by itself demonstrate that
migrating **all** fixed-width integers and `bool` into v2 reduces code.
Full integer semantics would additionally need width-aware arithmetic,
conversions, strict typing, storage layouts, and missing assembler encoding
support. These are separate costs and could negate the simplicity of an
ABI-only implementation.

Do not merge this branch into `main` as though the original hypothesis were
fully verified. A future full-type port must compare implementation LOC,
bootstrap fixed-point behavior, v3 compatibility bridges, and semantic
correctness against the unchanged baseline. If a bridge remains, it should
be explicit and transitional, not mistaken for a permanent safe ABI contract.

## Verification (2026-11-01)

`python test.py` passed for **v0, v1, v2, v3 and v4**. The bootstrap fixed
points remained byte-identical, and the added v2 E2E and semantic rejection
cases passed. This establishes that the ABI bridge is executable through the
full compiler chain; it does **not** establish full fixed-width language support
in v2. Experiment isolation is deliberate: `main` remains unchanged.
