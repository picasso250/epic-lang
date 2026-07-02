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

## Bootstrap

Build and verify the self-hosted compiler fixed point from the repository root:

```powershell
python test_bootstrap_fixed_point.py
```

The check builds:

1. `epic-py`: Python reference compiler builds the Epic compiler.
2. `epic-epic`: `epic-py` builds the Epic compiler.
3. `epic-epic-epic`: `epic-epic` builds the Epic compiler again.
4. a fourth compiler to verify repeated output is byte-identical.

`python epic-bootstrap.py` is a thin wrapper around that fixed-point check.

## Tests

Examples are learning-oriented positive programs. Real compiler tests live
under `tests/`, organized by compiler module (matching `bootstrap/*.py`).

Recommended commands:

```powershell
python tests/run.py               # Module-level test suite (MVP)
python test_examples_py.py        # examples/ learning examples
python test_mir.py                 # Legacy MIR tests (migrating to tests/mir/)
python test_x64_layers.py          # Legacy x64 tests (migrating to tests/x64/)
python test_lexer_dump_format.py   # Legacy lexer tests (migrating to tests/lexer/)
```

Or use the batch script:

```powershell
./testall.ps1
```

`link.py` is the default Python linker. `src/link.ep` is the Epic linker
implementation and is tested separately.

The old Python `--backend asm` path was archived at tag
`python-asm-archive-2026-07-02` and removed from the active Python reference
compiler. The Epic-written compiler under `src/` still belongs to the older
NASM-oriented self-hosting line and is not the current Python machine backend.

## Development Rule

Do not preserve forward compatibility for its own sake. When the language
changes, compiler sources should move with the current design.
