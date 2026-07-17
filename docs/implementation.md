# Epic v2 compiler implementation

This document describes the compiler implementation. User-visible semantics
live in [`language.md`](language.md).

## Bootstrap

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v2 seed -> Epic v2 fixed point
```

`build_epic.py` resolves the exact commit of the local `v1` branch. A cached
`build/epic-v1-<hash>.exe` is reused when available; otherwise the script
creates a detached v1 worktree and invokes its `build_epic.py`. That v1
compiler builds the current v2 sources. `bootstrap_fixed_point.py` then checks
that generations 1 and 2 are byte-identical.

## Compiler pipeline

The normal v2 compiler is entirely written in Epic:

```text
source -> lexer -> parser -> x64 assembly text -> assembler -> PE writer
```

The assembly text stays in memory during normal compilation. `-S` writes it
to disk and stops before the assembler; ordinary executable builds do not
create an assembly-file intermediate.

The six compiler source files are compiled as one program:

```text
src/epic.ep
src/lexer.ep
src/parser.ep
src/codegen.ep
src/asm.ep
src/pe.ep
```

The self-hosted generations do not invoke NASM or an external linker. NASM is
only part of the trusted Python stage-0 route used to create the first seed.

## Syntax model

The parser returns exact records for program structure, including programs,
product declarations, functions, parameters, fields, and blocks. Expressions
and statements use tagged records because those two categories flow through
large dispatches in code generation.

Unit-enum declarations and match arms are also exact records. Semantic
analysis resolves each qualified enum member to its declaration-order value,
checks nominal typing and match exhaustiveness, and records the resolved value
for code generation. Enums use one 64-bit scalar slot; match evaluates its
subject once and emits a linear comparison chain.

This keeps deterministic syntax records precise without creating a separate
wrapper allocation for every expression or statement.

## Code generation

The backend emits private x64 assembly text for Windows x64. Calls follow the
Windows x64 ABI and the v0 language limits calls and functions to four
arguments.

Each function receives a statically sized stack frame. A pre-scan computes
local storage and the peak number of compiler temporary slots; there is no
fixed temporary-slot limit.

Runtime assembly helpers implement strings, dynamic byte arrays, command-line
arguments, and file I/O. `embed("path")` stores their raw bytes in the compiler
image at bootstrap time, so a built `epic.exe` appends them without reading a
repository `runtime` directory.

All managed allocation sites call the conservative, non-moving mark-and-sweep
collector in `runtime/gc.asm`. It records exact allocation bases in side
metadata, routes small objects through four slab classes, scans the active stack
and managed payloads conservatively, and reclaims unreachable objects. The
detailed runtime contract is documented in [`gc.md`](gc.md).

## Assembler and PE writer

`src/asm.ep` parses the compiler's private assembly subset and encodes AMD64
instructions into text and data sections. It records symbols and relocations
needed by the executable writer.

`src/pe.ep` writes a deterministic Windows PE executable, including headers,
sections, imports, and relocations. Determinism is part of the bootstrap
contract: identical compiler sources must produce byte-identical fixed-point
executables.

## Acceptance

Run the maintained checks in this order:

```powershell
python tests/run.py
python tests/examples/run.py
python bootstrap_fixed_point.py
```

The self-contained suite first copies only `epic.exe` into an isolated
directory and verifies that it can compile a program using an embedded byte
resource. The public examples are compiled and executed individually. End-to-end test
sources remain independent, but their runner generates one temporary bundle,
compiles it once, and starts that executable separately for each case. This
preserves process isolation without producing one tiny PE per regression. The
GC suite separately exercises retained stack and heap references under bounded
memory pressure.
