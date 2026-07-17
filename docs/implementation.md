# Epic v1 compiler implementation

This document describes the compiler implementation. User-visible semantics
live in [`language.md`](language.md).

## Bootstrap

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 seed -> Epic v1 fixed point
```

`build_epic_v1.py` resolves the exact commit of the local `v0` branch, creates
a temporary detached worktree, and uses that Python compiler to build the v1
seed. `bootstrap_fixed_point.py` then checks that generations 1 and 2 are
byte-identical.

## Compiler pipeline

The normal v1 compiler is entirely written in Epic:

```text
source -> lexer -> parser -> x64 assembly text -> assembler -> PE writer
```

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
arguments, and file I/O. The compiler appends the required
helpers to its generated assembly.

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

The public examples are compiled and executed individually. End-to-end test
sources remain independent, but their runner generates one temporary bundle,
compiles it once, and starts that executable separately for each case. This
preserves process isolation without producing one tiny PE per regression.
