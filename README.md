# Epic

Epic is a small self-hosted systems language targeting Windows x64.

It includes a Python reference compiler, an Epic-written self-hosted compiler,
a typed LLVM-like MIR, a structured x64 backend, a small COFF/PE toolchain, and
runtime helpers for building real Windows executables.

```text
Epic source
  -> AST
  -> typed MIR
  -> structured X64IR / LowIR
  -> machine bytes
  -> AMD64 COFF object
  -> PE executable
```

Epic is still experimental, but it has crossed the self-hosting milestone and
already supports enough language surface to write non-trivial programs, including
compiler pieces written in Epic itself.

## Highlights

- **Self-hosted language work**: `bootstrap/` is the Python reference compiler;
  `src/` contains Epic-written compiler modules and tools kept close to the
  current language.
- **Typed LLVM-like MIR**: Epic has its own middle IR with typed values, basic
  blocks, terminators, `load` / `store`, `gep`, calls, branches, and validation.
  It is inspired by LLVM-style compiler construction, not by LLVM compatibility.
- **Structured x64 backend**: MIR lowers into X64IR / LowIR, a structured object
  model for registers, stack slots, labels, symbols, data items, and Windows x64
  ABI calls. The `.asm` output is a debug pretty print, not the active backend.
- **Machine backend**: X64IR is encoded directly into machine bytes, written as
  AMD64 COFF, and linked into PE executables by the in-repo Python linker.
- **Runtime helper migration**: MIR runtime helper bodies are bundled in
  `runtime/mir/helpers.mir` so the Python reference compiler and self-hosted
  compiler consume the same runtime text.
- **No legacy compatibility tax**: when the language changes, active compiler
  sources move with it instead of preserving old source compatibility.

## Language Features

Epic currently supports:

- functions, local variables, returns, `if`, `while`, `for in range`, `break`,
  and `continue`
- integer and boolean operations, including signed / unsigned arithmetic cases
- strings as byte-slice-backed text views during the current migration stage
- dynamic arrays (`T[]`) backed by slice headers, with `len`, `cap`, checked indexing, and `push`
- byte-oriented `u8[]` helpers such as slicing and `extend`
- `map[str]T` with lookup, assignment, `has`, `del`, literals, and growth
- heap-backed structs with field access, initialization, embedded fields, and
  user-defined methods on struct receivers
- ADTs backed by struct-union lowering, plus `match`
- file I/O helpers, `argv`, process exit, and direct WinAPI import
  calls on Windows

The language is intentionally moving fast. Public surface is documented by the
current compiler, examples, and `docs/`; old convenience builtins and old backend
paths are removed instead of kept as compatibility shims.

## Compiler Pipeline

The active compiler path is:

```text
parse / merge
  -> semantic analysis
  -> AST to MIR
  -> MIR validation
  -> MIR to X64IR
  -> X64IR validation
  -> machine bytes + COFF relocations
  -> PE linking
```

Key implementation files:

```text
bootstrap/epic.py          compiler driver
bootstrap/lexer.py         lexer
bootstrap/parser.py        parser
bootstrap/sema.py          semantic analysis
bootstrap/ast_to_mir.py    AST -> MIR
bootstrap/mir.py           typed MIR model and validator
bootstrap/mir_to_x64.py    MIR -> structured X64IR
bootstrap/x64.py           X64IR model and pretty printer
bootstrap/machine.py       X64IR -> machine bytes + COFF records
bootstrap/coff.py          minimal AMD64 COFF writer
bootstrap/link.py          minimal PE linker
```

The Python reference compiler is the oracle for the current language. Epic-written
compiler code should match the reference path before growing separate optimized
behavior. Future optimization work belongs behind an explicit optimization mode,
not in the default oracle path.

## Repository Layout

```text
bootstrap/          Python reference compiler for the current language
src/                Epic-written compiler modules and tools
runtime/            MIR runtime helpers and backend runtime support
examples/           positive learning examples
tests/              module-level compiler tests and negative tests
docs/               design notes and implementation contracts
editors/            editor integration assets
tools/              local tool binaries such as lld-link.exe
build/              ignored local build output
```

Earlier staged bootstrap directories are preserved in Git history and tags, not
as maintained source directories. Useful archive tags include:

```text
staged-bootstrap-archive-2026-06-30
python-asm-archive-2026-07-02
```

## Running Tests

Recommended test entry points from the repository root:

```powershell
python tests/run.py                    # module-level compiler tests
python test_examples.py             # examples/ positive learning programs
python test_bootstrap_fixed_point.py   # self-hosting fixed-point check
```

Module-specific checks are also available:

```powershell
python tests/mir/run.py
python tests/x64/run.py
python tests/lexer/run.py
python tests/parser/run.py
python tests/link/run.py
```

`test_*.py` files are direct script tests. Do not treat `python -m pytest` as the
supported test entry point.

## Building and Running Examples

Examples live under `examples/` and are intended to be positive, typical programs
that help new readers learn the current language.

```powershell
python test_examples.py
```

Individual examples can be compiled through the Python reference compiler. Build
artifacts are written under `build/`.

```powershell
python bootstrap/epic.py examples/00_hello_world.ep
```

The default path uses the in-repo Python PE linker. `lld-link` is optional for
comparison when present in `tools/`.

## Current Boundaries

Epic is not trying to be a stable general-purpose language yet. Current explicit
boundaries include:

- Windows x64 first; no cross-platform ABI promise yet
- MIR is LLVM-like, but not LLVM IR compatible
- first-class user pointer types are not part of the public language surface
- no full SSA / phi-node optimizer pipeline yet
- no general-purpose assembler or general-purpose register allocator
- old NASM text-assembly backend paths are archived, not active

## Development Rules

- Read the relevant `docs/` files before changing a compiler area.
- Keep examples positive and beginner-friendly; put negative tests under
  `tests/<module>/fail/`.
- Prefer clear compiler code over premature performance work.
- Do not preserve forward compatibility for its own sake. When the language
  changes, active compiler sources should move with the current design.
