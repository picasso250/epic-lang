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

## Outcome: single language-level FFI

- The `os.*` language-special call path is gone from v0, v1, v2, v3 and v4.
  All direct operating-system calls now use source-declared `extern` functions.
  Runtime assembly still imports necessary OS functions internally; these are
  backend implementation dependencies, not a second source-language API.
- Test fixtures that previously relied on implicit OS bindings now declare
  externs; bundled suites hoist identical declarations to one prelude.
- Negative tests reject old `os.*` syntax. The v4 semantic check additionally
  rejects taking a pointer to an imported external function.

## Remaining scope and limitations

- The bootstrap FFI is intentionally restricted: v0 and v1 use `i64` native
  lanes; v2 and v3 add a pointer formal type but do not expose full C ABI
  widths to native calls. v4 offers precise-width integers and opaque `ptr`.
  No generation models floating-point or aggregate ABI lanes.
- Python v0's optional `lld-link` path uses the Windows SDK import libraries,
  currently kernel32 and user32. The default Python PE writer supports imports
  from arbitrary named DLLs without SDK `.lib` files.
- Early assemblers import by function name, so two DLLs exposing the same
  function name need import alias support for complete general-purpose FFI.
  The v4 extern path uses a single source-level declaration mechanism, but its
  runtime assembly still relies on the internal system-import map.
- The old canonical-history `main` is unchanged. The experiment is isolated,
  and should not be merged without review of this API-breaking historical
  correction.

## Next decision

Review the cross-generation diff and ABI boundaries, then decide whether to
adopt this new canonical history. All old Git tags remain preserved.
