# Epic v2

Epic v2 starts from the completed v1 self-hosted compiler. Its source is still
written in the v0 language subset and retains v1's internal AMD64 assembler and
deterministic PE writer. Future v2 commits can now evolve the language without
changing the frozen stage-0 and v1 milestones.

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v2 -> Epic v2 fixed point
```

## Build

```powershell
python build_epic.py
```

The script resolves the current local `v1` branch to an exact commit. It reuses
`build/epic-v1-<hash>.exe` when present; otherwise it creates a detached v1
worktree and calls that generation's `build_epic.py`. The resulting v1 compiler
then compiles the current v2 working tree.

The default output is `build/epic-v2.exe`. Pass `-o PATH` to copy only the
final v2 executable elsewhere; relative paths are resolved from the calling
working directory.

## Documentation

- [Language reference](docs/language.md), including built-in data structures and functions
- [Compiler implementation](docs/implementation.md)
- [Garbage collector](docs/gc.md)

Verify the self-hosted fixed point:

```powershell
python bootstrap_fixed_point.py
```

The v1-built v2 seed compiles generation 1, then generation 1 compiles
generation 2. The check succeeds only when generations 1 and 2 are
byte-identical.

## Test

```powershell
python tests/run.py
```

`examples/` contains the small learning sequence. Broader regression coverage
lives under `tests/e2e/pass/`.
