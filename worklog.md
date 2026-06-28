# Epic worklog

This file is a chronological project log only. Current language design lives in `design.md`; current implementation notes live in `impl.md`.

## 2026-06-25

### Project kickoff

- Chose Epic as the language name and `.ep` as the source extension.
- Target platform: Windows x64 with a bare `_start` entry.
- Initial architecture: lexer/parser -> AST -> codegen/emitter -> NASM -> linker.
- Initial syntax direction: C-like blocks and semicolon-terminated statements.
- Initial implementation used Python as the prototype compiler.

### Early milestones

- M1: minimal pipeline, `exit(42)`.
- M2: arithmetic expressions.
- M3: variables.
- M4: functions.
- M5: branches.
- M6: loops.
- M7: strings.
- Added `runtests.py` to compile and run annotated examples.

### Toolchain

- Added NASM under `tools/`.
- Added `lld-link` support.
- Started `link.py` as a small custom PE linker.
- Fixed early linker issues around `_start` entrypoint resolution and short import names.

## 2026-06-26

### String/runtime redesign

- Changed string layout direction to `{ data, len }`.
- Reworked string literals to produce heap strings.
- Replaced older string helpers with `str_new(...)` and `itoa(...) -> str`.
- Fixed multiple stack alignment, temp-slot, volatile-register, and empty-string bugs.

### Review fixes

- Fixed temp pre-scan omissions for builtin/runtime paths.
- Fixed `&i8` subscript typing.
- Fixed empty string data emission.
- Renamed the old `str(...)` builtin to `str_new(...)`.
- Added regression examples around these issues.

### Structs

- Added top-level `struct Name { field: type; ... }` definitions.
- Added field reads and field writes.
- Moved toward heap/reference semantics for structs.

### Syntax cleanup

- Renamed `fn` to `fun`.
- Removed mandatory parentheses from `if` and `while` conditions.
- Continued standardizing the self-hosting source style.

### Heap objects and arrays

- Added `new Name` heap allocation.
- Added dynamic arrays with `.data`, `.len`, `.cap`, and `push`.
- Reworked older static-array examples toward dynamic arrays.
- Added support for arrays of primitives and references.

### Self-hosting support

- Added file and process builtins needed by compiler self-hosting.
- Split the Python compiler into lexer, parser, AST nodes, codegen, and driver files.
- Started Epic implementations of compiler components.

### Lexer/parser bootstrap

- Added `lexer.ep` and tests comparing Epic lexer output against the Python lexer.
- Added `parser.ep` and tests comparing self-hosted parser dumps against Python parser dumps.

## 2026-06-28

### Compiler driver

- Current driver file is `epic.py`.
- Default linker is `link.py` through `--linker py`.
- Added `--linker lld-link` as an alternate linker path.
- Added `--out-dir`.
- Added multi-file whole-program source merging with `--main`.

### Runtime and examples

- Added runtime helpers for strings, argv, process execution, and file I/O.
- Added examples through `m29_void.ep`.
- `python runtests.py --linker py`: 38 passed, 0 failed.

### Codegen bootstrap

- Added `codegen.ep` as a standalone self-hosting codegen step.
- Added `test_codegen_bootstrap.py` to compile examples through the Epic codegen path.

### Documentation cleanup

- Re-scoped `design.md` to language design and user-visible semantics.
- Added `impl.md` for current implementation notes.
- Reduced `worklog.md` to a chronological log.
- Fixed stale `epicc.py` references in current docs by using `epic.py`.
