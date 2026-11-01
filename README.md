# Epic Lang

**The compiler generations are directories, not Git branches.** The active
front line is [`v4/`](v4/). The `main` branch is the single canonical tree.

```text
Epic Lang/
  v0/    Python stage-0, non-self-hosted, compiles v1 only
  v1/    first self-hosted compiler, fixed-point foundation
  v2/    semantic analysis, GC, enums, containers
  v3/    typed integers, bool, expression control flow; v4 compiler seed
  v4/    current language/compiler development, FFI, closures, Windows GUI
  build.py     build the complete generation chain, without Git branches
  test.py      test every generation using each generation's test suites
  AGENTS.md    cross-generation development contract
  MIGRATION.md exact legacy branch snapshots and migration rationale
```

## Build

On Windows x64, install Python 3 and provide a trusted NASM executable at
`v0/tools/nasm.exe` (ignored by Git) or set `EPIC_NASM` to its path. NASM is
needed only for the **trusted Python v0 → Epic v1** bootstrap step. Later
compilers contain their own assembler and PE writer.

```powershell
python build.py             # v0 -> v1 -> v2 -> v3 -> v4
python build.py --to 3      # stop at compiler v3
python test.py              # v0 acceptance + v1..v4 test suites
python test.py --from-version 4   # test only today's front line
```

Each generation is independent at the source level: `vN/build_epic.py` is a
thin interface to the root orchestration. Run a generation's test suite from
its own folder; its build script compiles all prerequisite generations first.
No Git branch names, temporary Git worktrees, or prebuilt compiler images are
required. Builds intentionally always regenerate seeds to avoid stale binary
cache problems.

The compiled current toolchain lives at `v4/build/epic-v4.exe`. For a
byte-identical self-hosted fixed point, run:

```powershell
cd v4
python bootstrap_fixed_point.py
```

Only v1's initial fixed point is an architectural requirement for the
intergenerational bootstrap. Later generations are required to compile their
successors, **not** necessarily themselves. v4 currently supports a fixed-point
check as an additional self-hosting verification.

## Canonical history

**When correcting language history, implement the intended design in the
earliest generation where it logically belongs, then propagate changes forward.**
Do not retrofit future features into Python v0 or retain compatibility layers
merely so vN can recompile its own source. Every generation has its own docs,
tests, and runtime. The fixed-point contract is documented in `AGENTS.md`.

## Existing development history

Before this layout, v0..v4 were separate Git branches. Their original heads and
commit ancestry are preserved by annotated `archive/pre-directories-2026-11-01-*`
tags. See [`MIGRATION.md`](MIGRATION.md) for exact SHAs and recover instructions.
Do not use legacy branches as a basis for new language work.
