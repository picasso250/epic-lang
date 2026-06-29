# Epic

Epic is a small self-hosting systems language experiment targeting Windows x64.

The current development line is `v2`: v1 is the previous compiler anchor, and
the Epic linker is the default linker path.

## Repository layout

- `../v0` is the historical stable bootstrap point.
- `../v1` continues language development after v0.
- `../v2` compiles compiler sources with the v1 compiler and uses `link.ep`.

Do not preserve forward compatibility for its own sake. When the language
changes, compiler sources should move with the current design.

## Tooling

This repository expects Windows x64 and these local tools:

- Python 3
- `tools/nasm.exe`
- `tools/lld-link.exe` when using `--linker lld-link`
- Windows SDK libraries matching the current Epic compiler toolchain paths

`tools/` and build outputs are intentionally ignored by git.

## v0 bootstrap ritual

The important v0 invariant is reproducible bootstrapping from the Python
compiler to a self-hosted compiler.

From the repository root, the top-level bootstrap script can produce the v0 and
v1 anchors:

```powershell
python epic-bootstrap.py
```

Inside `../v0`, `python test_bootstrap_fixed_point.py` produces the stable
previous-compiler artifacts under `v0\build\fixed-point`, including:

- `epic-py.exe`
- `epic-epic.exe`
- `epic-epic-epic.exe`

Copy the fixed-point compiler to root `build\v0.exe`, then use that executable
as the trusted previous compiler for v1:

```powershell
..\build\v0.exe epic.ep codegen_support.ep codegen.ep parser.ep lexer.ep
```

This gives v1 development a concrete predecessor: v0 remains available as the
bootstrap anchor, while v1 can change the language without pretending to be
compatible with old source.

## Tests

From `v2/`, first create the local v1 anchor:

```powershell
python ..\epic-bootstrap.py
```

Then run the example suite with the previous Epic compiler as the anchor:

```powershell
python runtests.py
```

The test runner builds `link.ep` and the current compiler with `build\v1.exe`,
then uses the current compiler and `build\epic\link.ep.exe` to compile and run
`examples/*.ep`. Override the anchor with `PREVIOUS_EPIC` if needed.

The Epic linker MVP can be checked with:

```powershell
python test_link_ep.py
```

This builds `link.ep`, relinks every current example object with it, and runs
the generated executables against the normal example annotations.

## v1 direction

Initial v1 work:

- stronger `str` operations
- `len()` and `cap()` builtins
- remove semicolons
- checked indexing and slice syntax
- `else if`, `break` / `continue`, and half-open `for i in start..end` range loops
- compound assignment operators such as `+=`, `>>=`, and `^=`
- binary byte-buffer support as groundwork for replacing `link.py`
- `link.ep` MVP for the current single-object PE64 path
- split `codegen.ep`
- revisit `map` after the first pass

See `..\v1\design.md` for the inherited v1 design notes and `design.md` for
v2-specific deltas.
