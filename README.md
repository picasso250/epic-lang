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
- Windows SDK libraries matching the path in `epic.py`

`tools/` and build outputs are intentionally ignored by git.

## v0 bootstrap ritual

The important v0 invariant is reproducible bootstrapping from the Python
compiler to a self-hosted compiler.

From the `v0` branch:

```powershell
git switch v0
python epic.py --main epic.ep epic.ep codegen.ep parser.ep lexer.ep --out-dir build\v00
Copy-Item build\v00\epic.exe build\v00.exe
.\build\v00.exe epic.ep codegen.ep parser.ep lexer.ep
Copy-Item build\epic\epic.ep.exe build\v0.exe
```

The two stages are:

1. Python compiler -> `v00.exe`
2. `v00.exe` compiles the Epic compiler -> `v0.exe`

After that, switch to the development branch and use the v0 compiler as the
trusted previous compiler:

```powershell
git switch v1
.\build\v0.exe epic.ep codegen.ep parser.ep lexer.ep
```

This gives v1 development a concrete predecessor: v0 remains available as the
bootstrap anchor, while v1 can change the language without pretending to be
compatible with old source.

## Tests

Run the example suite with the Python driver:

```powershell
python runtests.py
```

Run the self-hosted compiler smoke test:

```powershell
python test_epic_bootstrap.py
```

## v1 direction

Initial v1 work:

- stronger `str` operations
- remove semicolons
- split `codegen.ep`
- revisit `map` after the first pass

See `design-v1.md` for the current design notes.
