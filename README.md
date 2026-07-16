# Epic v1

Epic v1 is the first self-hosted Epic compiler. Its source is written in the
v0 language subset and emits NASM assembly. This keeps the bootstrap step small
while v1 implements the language capabilities needed by the next compiler
generation.

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v1 fixed point
```

## Build

```powershell
python build_epic_v1.py
```

The script resolves the current local `v0` branch, creates a temporary detached
Git worktree at its exact commit, and uses that worktree's Python compiler to
compile `src/`. The temporary worktree is removed when the build finishes.
NASM remains part of the trusted toolchain, and `link.py` remains until a later
Epic generation takes ownership of machine-code emission and linking.

The resulting compiler is `build/epic-v1.exe`.

Verify the self-hosted fixed point:

```powershell
python bootstrap_fixed_point.py
```

The v0-built seed compiles generation 1, then generation 1 compiles generation
2. The check succeeds only when generations 1 and 2 are byte-identical.

## Test

```powershell
python runtests.py
```

`examples/` contains the small learning sequence. Broader regression coverage
lives under `tests/e2e/pass/`.
