# Epic

Epic is a small self-hosting systems language experiment targeting Windows x64.

The active development line has two compiler implementations:

- `bootstrap/`: Python reference compiler for the current Epic language.
- `src/`: Epic compiler and Epic-written tools, written in the current language.

Earlier staged bootstrap directories are preserved in Git history and tags, not
as maintained source directories. The last directory-based chain is tagged as:

```text
staged-bootstrap-archive-2026-06-30
```

## Layout

- `bootstrap/`: Python lexer, parser, semantic analyzer, MIR/X64 lowering, machine backend, and compiler driver.
- `src/`: self-hosted compiler sources and `link.ep`.
- `runtime/`: NASM runtime helpers for the older Epic-written backend line.
- `examples/`: annotated acceptance examples for the current language.
- `docs/`: merged design and implementation notes, plus archived source notes.
- `editors/`: editor integration assets.
- `tree-sitter-epic/`: shared tree-sitter grammar support.
- `tools/`: local ignored tool binaries such as `lld-link.exe`; `nasm.exe` is only needed for older archived/self-hosted paths.
- `build/`: local ignored build output.

## Bootstrapping (inactive)

The self-hosted compiler under `src/` is a separate, older line. The fixed-point
bootstrap chain (`python test_bootstrap_fixed_point.py`) is strategically
abandoned — the `src/*.ep` sources still contain ADT syntax that the current
Python parser no longer accepts.

Active development targets the Python reference compiler (`bootstrap/`).
Self-hosted sources are preserved for future bootstrapping but are not part of
the current testing pipeline.

## Tests

Examples are learning-oriented positive programs. Real compiler tests live
under `tests/`, organized by compiler module (matching `bootstrap/*.py`).

All Python reference compiler tests:

```powershell
python tests/run.py               # Module-level test suite (Python-only, all green)
python test_examples_py.py        # examples/ learning examples
```

Module-specific tests:

```powershell
python tests/mir/run.py            # MIR tests
python tests/x64/run.py            # X64 backend tests
python tests/lexer/run.py          # Lexer golden check (skip self-hosted by default)
python tests/lexer/run.py --self-hosted  # Also compare against self-hosted lexer.exe
```

The self-hosted compiler (`src/*.ep`) is a separate, inactive line and is not
required for Python reference compiler tests.

`link.py` is the default Python linker. `src/link.ep` is the Epic linker
implementation and is tested separately.

The old Python `--backend asm` path was archived at tag
`python-asm-archive-2026-07-02` and removed from the active Python reference
compiler. The Epic-written compiler under `src/` still belongs to the older
NASM-oriented self-hosting line and is not the current Python machine backend.

## Development Rule

Do not preserve forward compatibility for its own sake. When the language
changes, compiler sources should move with the current design.
