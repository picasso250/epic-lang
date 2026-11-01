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

## Verification and branch retirement

- Migration commit: `812d537beaa34d9ce6d3e39c2eb21180c6edc952`
  (plus this documentation follow-up).
- Verified original Git blob identities for each generation's `src/`,
  `runtime/`, `tests/`, and `examples/` files against the archived snapshots.
- Executed `python test.py` in the new layout: **all five generations passed**.
  In particular, v4's full six-suite test runner (including fixed point,
  132 end-to-end cases, 67 semantic diagnostics, assembler and GC) passed.
- Executed `python test.py --from-version 4` again on the existing repository's
  real `main` working tree: **passed**.
- **After deleting the local v0–v4 branches**, executed `python build.py --to 4`
  again: **passed**. This confirms that normal builds no longer depend on
  branch references or Git worktrees.
- The new v4 executable's SHA-256 does **not** match the executable built in
  the older v4 worktree. Each location independently passes its two-generation
  byte-identical fixed-point check and full functional suite; cross-directory
  binary identity has not been established, and the difference's cause has not
  yet been isolated. Do not overstate binary reproducibility across locations.
- The original `v0`–`v4` local and `origin` branches were deleted **only after**
  annotated archive tags were pushed to GitHub. Other experimental branches
  were left unchanged. The five older local worktrees under `build/worktrees/`
  were **detached at their original commit** and retained as local safety copies;
  do not make new changes there. The scratch integration worktree was removed.
- The preexisting untracked `.continue-on-phone/` was preserved. Untracked
  ignored build/cache artifacts in the original repository were not deleted.
