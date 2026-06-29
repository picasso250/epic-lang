# Epic

Epic is a small self-hosting systems language experiment targeting Windows x64.

The current stable milestone is `v0`: a Python prototype can compile the Epic
compiler sources, and the resulting compiler can compile Epic programs.

## Repository branches

- `v0` is the historical stable bootstrap point.
- `v1` continues language development after v0.

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

From the `v0` branch:

```powershell
git switch v0
python test_bootstrap_fixed_point.py
```

This produces the stable previous-compiler artifacts under `build\fixed-point`,
including:

- `epic-py.exe`
- `epic-epic.exe`
- `epic-epic-epic.exe`

Copy the fixed-point compiler to `build\v0.exe`, then switch to the development
branch and use that executable as the trusted previous compiler:

```powershell
Copy-Item build\fixed-point\epic-epic-epic.exe build\v0.exe
git switch v1
.\build\v0.exe epic.ep codegen_support.ep codegen.ep parser.ep lexer.ep
```

This gives v1 development a concrete predecessor: v0 remains available as the
bootstrap anchor, while v1 can change the language without pretending to be
compatible with old source.

## Tests

On `v1`, run the example suite with the previous Epic compiler as the anchor:

```powershell
python runtests.py
```

The test runner builds the current compiler with `build\v0.exe`, then uses the
current compiler to compile and run `examples/*.ep`. Override the anchor with
`PREVIOUS_EPIC` if needed.

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
- `else if`, `break` / `continue`, and half-open `for i in start:end` range loops
- compound assignment operators such as `+=`, `>>=`, and `^=`
- binary byte-buffer support as groundwork for replacing `link.py`
- `link.ep` MVP for the current single-object PE64 path
- split `codegen.ep`
- revisit `map` after the first pass

See `design-v1.md` for the current design notes.
