# Early extern: experiment, not canonical history

Branch: `experiment/early-extern` (isolated worktree).

## Hypothesis

The Python v0 seed did not intrinsically need an `os.*` language special case.
An early `extern "dll" fun ...` declaration might have been sufficient for
bootstrap, even before v3 introduced precise-width integer types.

## Verified

- Python v0 can parse `extern "kernel32.dll" fun ...` and associate arbitrary
  Win32 names with a declared DLL in its PE import directory.
- One source program with **no `os.*`** compiled and ran with both Python v0
  and self-hosted v1; it imports kernel32 and user32, and exercises a
  seven-argument `CreateFileA` call with an explicitly passed raw pointer.
- The v1 compiler source now uses `extern` declarations instead of
  `os.ExitProcess`, `os.CreateFileA`, and `os.CloseHandle`, and Python v0
  successfully bootstraps it.
- The v1 compiler itself implements the restricted declaration/call/PE import
  path and reaches a two-generation byte-identical fixed point.
- Existing regression suites from v0 through v4 still pass.

## Extended cross-generation demonstration

- The v2 compiler parses, type-checks and encodes `extern` declarations, using
  them as the source for import DLL resolution. Its own source now uses early
  external declarations rather than the previous `os.*` calls.
- v3 has the same declaration path and can compile and execute a native call
  with seven parameters across `kernel32.dll` and `user32.dll`.
- v4 compiler source likewise uses external declarations, and the full chain
  from Python v0 through v4 builds successfully. The v4 bootstrap binary is
  byte-identical across its two independent self-compilation runs.
- v2 and v3 regression suites were rerun after correcting pointer type scope:
  raw `ptr` is valid in external declarations but is not accidentally made a
  general source-language value type.

## Limits / unfinished

- This **does not remove** the historical `os.*` language mechanism yet.
  Untouched old sources/tests still use it. This branch is a feasibility proof,
  not a completed canonical-history migration.
- Early `extern` has `i64` arguments and `i64`/`void` returns only. It treats
  a raw address as a 64-bit integer; when crossing to C strings, use
  `name.data` explicitly (old `str` has a terminating NUL). Passing `name`
  would pass an Epic string object instead.
- Floating-point argument ABI, structs, and exact 32-bit signedness are not
  modeled. Existing `os.*` compiler/runtime import names are still predefined.
- The Python v0 `lld-link` fallback rejects new extern declarations; the
  experimental multi-DLL implementation is in the Python linker.
- The early assembler's symbol namespace cannot yet distinguish two imports
  with the same exported name from different DLLs. General-purpose FFI would
  require a distinct internal import symbol or an alias scheme.

## Next decision

A full migration would eliminate `os.*` in the v0-v4 user-facing surface,
propagate implementation and source changes through successor generations, and
retire duplicate binding lists where they are no longer required. No changes
have been merged into `main`.
