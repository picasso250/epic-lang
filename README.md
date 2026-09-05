# Epic v2

Epic v2 starts from the completed v1 self-hosted compiler. Its source remains
in the v0 language subset and retains v1's internal AMD64 assembler and
deterministic PE writer. v2 adds conservative garbage collection, semantic
analysis, integer compound assignment, nominal unit enums, and statement-only
enum matching. Dynamic arrays become opaque and are accessed through `len`,
checked subscripting, `push`, `pop`, and `extend`. v2 also introduces the safe
`str(u8[])` snapshot conversion that v3 compiler sources dogfood. Its final
language surface includes snapshot-bound integer range loops and integer unary
`-` / `!`, without changing the stage-0 or v1 milestones.

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v2 -> Epic v3
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

## Test

```powershell
python tests/run.py
```

The test runner builds the v2 compiler with v1 and tests that seed directly.
The v2 compiler is required to compile the v3 compiler sources; it is not
required to compile its own v1-era sources.

`examples/` contains the small learning sequence. Broader regression coverage
lives under `tests/e2e/pass/`.
