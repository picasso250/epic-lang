# Epic Lang development contract

- `main` is the canonical **directory-based** source tree. `v4/` is the current
  active compiler generation. `v0/`–`v3/` are historical compiler generations,
  not active alternative development branches.
- Question the requirements, remove unnecessary parts, simplify, accelerate
  iteration, and only then automate.
- New features, bug fixes, and refactors should be tested and committed. Do not
  overwrite or delete user-created/untracked files or archived Git history.
- Python `v0/` is the non-self-hosting stage-0 seed and compiles only `v1/`.
  Do not maintain a separate Epic self-hosted compiler implementation in `v0/`.
- The `v1/` compiler source is written in the v0 language subset, even when
  v1 implements newer language capabilities. Do not make a generation dogfood
  its own new features just for self-compilation.
- For difficult Win32 API / ABI behavior, a small unoptimized C example
  compiled to assembly can help verify calling conventions before changing
  Epic's assembler or code generation.
- Initial fixed point is established at v0 → v1. Later generation vN must
  correctly compile the vN+1 compiler source. **Do not require vN to compile
  itself or preserve outdated language behavior just to achieve this.**
- New language features are implemented by vN and dogfooded in the source
  of vN+1. Avoid pushing future features backwards into the earlier seed.
- For canonical-history corrections, change the logically earliest relevant
  generation and propagate the change to successor generations in one coherent
  cross-directory diff.
- Prefer end-to-end tests expressing intended behavior over white-box tests
  that encode incidental implementation details. Remove misleading tests.
- Before calling work complete, run `python test.py` or at least
  `python test.py --from-version 4` if the change is strictly v4-only.
- Root `build.py` is the only cross-generation build logic; there must be no
  compiler dependency on Git branches, worktrees or prebuilt binary seeds.
