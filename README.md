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

- `bootstrap/`: Python lexer, parser, AST, codegen, and compiler driver.
- `src/`: self-hosted compiler sources and `link.ep`.
- `runtime/`: NASM runtime helpers appended by the compiler.
- `examples/`: annotated acceptance examples for the current language.
- `docs/`: merged design and implementation notes, plus archived source notes.
- `editors/`: editor integration assets.
- `tree-sitter-epic/`: shared tree-sitter grammar support.
- `tools/`: local ignored tool binaries such as `nasm.exe` and `lld-link.exe`.
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

Run the current Python reference compiler against all annotated examples:

```powershell
python test_examples_py.py
```

Formatter and bootstrap checks:

```powershell
python test_epicfmt.py
python test_bootstrap_fixed_point.py
```

`link.py` is the default Python linker. `src/link.ep` is the Epic linker
implementation and is tested separately.

## Development Rule

Do not preserve forward compatibility for its own sake. When the language
changes, compiler sources should move with the current design.
