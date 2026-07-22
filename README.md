# Epic v2

Epic v2 starts from the completed v1 self-hosted compiler. Its source remains
in the v0 language subset and retains v1's internal AMD64 assembler and
deterministic PE writer. v2 adds conservative garbage collection, semantic
analysis, integer compound assignment, nominal unit enums, and statement-only
enum matching. It also introduces the safe `str(u8[])` snapshot conversion
that v3 compiler sources dogfood. Its final language surface includes snapshot-bound integer
range loops and integer unary `-` / `!`, without changing the stage-0 or v1
milestones.

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

The build script writes the compiler to `build/epic-v2.exe`. Programs compiled
without `-o` produce `a.exe`, while `-S` without `-o` produces `a.asm`, in the
current working directory. `-o PATH` selects the output path in either mode.

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
