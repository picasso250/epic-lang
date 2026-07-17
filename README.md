# Epic v1

Epic v1 is the first self-hosted Epic compiler. Its source is written in the
v0 language subset, emits its private assembly text, encodes AMD64 instructions,
and writes deterministic PE executables. This keeps the bootstrap step small
while making the self-hosted compiler independent of external assembly and
linking tools during normal compilation.

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v1 fixed point
```

## Build

```powershell
python build_epic.py
```

The script resolves the current local `v0` branch, creates a temporary detached
Git worktree at its exact commit, and uses that worktree's Python compiler to
compile `src/`. The temporary worktree is removed when the build finishes.
NASM remains only in the trusted stage-0 path that builds the first v1 seed from
Python v0. Self-hosted generations and programs compiled by v1 use Epic's
internal assembler and PE writer.

The resulting compiler is `build/epic-v1.exe`. Pass `-o PATH` to copy the
final executable elsewhere; relative paths are resolved from the calling
working directory.

## Documentation

- [Language reference](docs/language.md), including built-in data structures and functions
- [Compiler implementation](docs/implementation.md)

Verify the self-hosted fixed point:

```powershell
python bootstrap_fixed_point.py
```

The v0-built seed compiles generation 1, then generation 1 compiles generation
2. The check succeeds only when generations 1 and 2 are byte-identical.

## Test

```powershell
python tests/run.py
```

`examples/` contains the small learning sequence. Broader regression coverage
lives under `tests/e2e/pass/`.
