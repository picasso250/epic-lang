# Epic v4

Epic v4 starts from the sealed v3 compiler. Its initial seed intentionally has
the same language semantics and compiler sources as the v3 fixed point; v4 is
the dogfood generation for v3's expression control flow, fixed-width integers,
opaque arrays, string and array slicing, explicit C-string conversion, and
single internal `ptr` model. New v4 language work begins from this fixed point.
The compiler now dogfoods string slicing, and v4 closes the transitional
`str.data`, `str.len`, and `str_new` interfaces retained by v3.

It retains the self-contained structured AMD64 assembler, stable symbol indexes,
deterministic PE writer, and conservative garbage collector.

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v2 -> Epic v3 -> Epic v4 -> Epic v4 fixed point
```

## Build

```powershell
python build_epic.py
```

The script resolves the sealed local `v3` branch to an exact commit. It reuses
`build/epic-v3-<hash>.exe` when present; otherwise it creates a detached v3
worktree and calls that generation's `build_epic.py`. The resulting v3 compiler
then compiles the current v4 working tree.

The default output is `build/epic-v4.exe`. Pass `-o PATH` to copy only the
final v4 executable elsewhere; relative paths are resolved from the calling
working directory.

## Documentation

- [Language reference](docs/language.md), including built-in data structures and functions
- [Compiler implementation](docs/implementation.md)
- [Garbage collector](docs/gc.md)

Verify the self-hosted fixed point:

```powershell
python bootstrap_fixed_point.py
```

The v3-built v4 seed compiles generation 1, then generation 1 compiles
generation 2. The check succeeds only when generations 1 and 2 are
byte-identical.

## Test

```powershell
python tests/run.py
```

`examples/` contains the small learning sequence. Broader regression coverage
lives under `tests/e2e/pass/`.
