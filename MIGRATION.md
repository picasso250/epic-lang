# Migration: compiler generation branches → directories

Date: 2026-11-01. The original source is retained in **annotated Git tags**:

| Generation | Original tip SHA | Tag |
|---|---|---|
| main | `fe1f2c397d86ed6fb1aeaf6dfbefada329cc7e4a` | `archive/pre-directories-2026-11-01-main` |
| v0 | `eb7610e41e0c43e01a69893a17df54440c4e2c92` | `archive/pre-directories-2026-11-01-v0` |
| v1 | `ec056d49768301cc83fe981d8ce95dd3dc9b6123` | `archive/pre-directories-2026-11-01-v1` |
| v2 | `e5243c8220611cf1674e43c70d2f80c691141fc6` | `archive/pre-directories-2026-11-01-v2` |
| v3 | `b6b60235e64c18cf4ff994b63d5bde08ab864a41` | `archive/pre-directories-2026-11-01-v3` |
| v4 | `2b5a3dfbce034bcfdf5cc86ba6b72243cd82cc2f` | `archive/pre-directories-2026-11-01-v4` |

All tracked files from each generation were transferred as Git trees beneath
`v0/` to `v4/` without losing untracked/ignored build artifacts in the original
working trees. The only compiler/build script substitutions were `v1/build_epic.py` through
`v4/build_epic.py`, now small wrappers around root `build.py`. We also revised
README, implementation-guide and AGENTS prose in each generation to describe
the new layout. The old build scripts and documentation survive in the
annotated tags above. Compiler source (`src/`), runtime (`runtime/`) and tests
retain their original file bytes.

The old build system used `git rev-parse refs/heads/vN` and detached worktrees
to materialize seed compilers. The new one instead invokes the previous
compiler from the sibling generation directory. Trusted NASM remains an
external installation (`v0/tools/nasm.exe` or `EPIC_NASM`), not a checked-in
executable. Build files and untracked user work were never part of this move.

To inspect the original source, for example:

```powershell
git show archive/pre-directories-2026-11-01-v4:src/sema.ep
git log archive/pre-directories-2026-11-01-v3 --oneline
```

This repository is **one** source history with five logical compiler generations.
A change to shared language semantics should update the appropriate generation
folders together; do not recreate five long-lived Git branches.
