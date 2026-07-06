# Epic

Epic is a small self-hosting systems language experiment targeting Windows x64.

The active development line has two compiler implementations:

- `bootstrap/`: Python reference compiler for the current Epic language.
- `src/`: Epic-written compiler modules and tools that are still active.

Earlier staged bootstrap directories are preserved in Git history and tags, not
as maintained source directories. The last directory-based chain is tagged as:

```text
staged-bootstrap-archive-2026-06-30
```

## Layout

- `bootstrap/`: Python lexer, parser, semantic analyzer, MIR/X64 lowering, machine backend, and compiler driver.
- `src/`: Epic-written lexer/parser/sema modules and `link.ep`.
- `runtime/`: NASM runtime helpers for the older Epic-written backend line.
- `examples/`: annotated acceptance examples for the current language.
- `docs/`: merged design and implementation notes, plus archived source notes.
- `editors/`: editor integration assets.
- `tree-sitter-epic/`: shared tree-sitter grammar support.
- `tools/`: local ignored tool binaries such as `lld-link.exe`; `nasm.exe` is only needed for older archived/self-hosted paths.
- `build/`: local ignored build output.

## Bootstrapping

The Python reference compiler under `bootstrap/` is the oracle for the current
language. Epic-written modules under `src/` are being restored module by module on top of that current language. The old `src/epic.ep` NASM driver has been removed because its backend path no longer exists.

The default self-hosting path is lockstep and unoptimized: Python and Epic
implementations should produce matching dumps at each compiler stage before the
Epic side is allowed to grow an optimized mode. Optimizations belong behind an
explicit future optimization flag and must not pollute the default oracle path.

The old fixed-point bootstrap chain (`python test_bootstrap_fixed_point.py`) is
not the active entry point. Current self-hosting work is covered by module tests
such as the self-hosted lexer and parser comparisons under `tests/`. Parser
self-hosting checks intentionally cover examples plus stable compiler sources
(`src/lexer.ep` and `src/parser.ep`), not every in-progress `src/*.ep` file, to
avoid unrelated backend development noise.

## Tests

Examples are learning-oriented positive programs. Real compiler tests live
under `tests/`, organized by compiler module (matching `bootstrap/*.py`).

All Python reference compiler tests:

```powershell
python tests/run.py               # Module-level test suite
python test_examples_py.py        # examples/ learning examples
```

Module-specific tests:

```powershell
python tests/mir/run.py            # MIR tests
python tests/x64/run.py            # X64 backend tests
python tests/lexer/run.py          # Lexer golden check + self-hosted comparison
python tests/lexer/run.py --no-self-hosted  # Skip self-hosted lexer.exe comparison
python tests/parser/run.py         # Parser Python/self-hosted dump comparison
```

`bootstrap/link.py` is the default Python linker. `src/link.ep` is the Epic linker
implementation and is tested separately.

The old Python `--backend asm` path was archived at tag
`python-asm-archive-2026-07-02` and removed from the active Python reference
compiler. Epic-written modules under `src/` are being moved toward the current language and backend model incrementally.

## Development Rule

Do not preserve forward compatibility for its own sake. When the language
changes, compiler sources should move with the current design.
