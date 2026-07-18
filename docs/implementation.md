# Epic v3 compiler implementation

This document describes the compiler implementation. User-visible semantics
live in [`language.md`](language.md).

## Bootstrap

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v2 -> Epic v3 seed -> Epic v3 fixed point
```

`build_epic.py` resolves the exact commit of the local `v2` branch. A cached
`build/epic-v2-<hash>.exe` is reused when available; otherwise the script
creates a detached v2 worktree and invokes its `build_epic.py`. That v2
compiler builds the current v3 sources. `bootstrap_fixed_point.py` then checks
that generations 1 and 2 are byte-identical.

## Compiler pipeline

The normal v3 compiler is entirely written in Epic:

```text
source -> lexer -> parser -> semantic analysis -> AsmProgram -> encoder -> PE writer
                                                    |
                                                    +-> renderer for -S
```

Code generation constructs a typed, ordered `AsmProgram` directly; ordinary
executable builds never create or parse an assembly-text intermediate. The
embedded `runtime/*.asm` sources are the only textual input to the assembler
parser, which converts them into the same `AsmProgram`. `-S` renders that
program as canonical private-NASM-subset text with one semantic item per line.

The eight compiler source files are compiled as one program:

```text
src/epic.ep
src/utils.ep
src/lexer.ep
src/parser.ep
src/sema.ep
src/codegen.ep
src/asm.ep
src/pe.ep
```

The self-hosted generations do not invoke NASM or an external linker. NASM is
only part of the trusted Python stage-0 route used to create the first seed.

## Syntax model

The lexer and parser dogfood nominal enums directly. `Token.kind` is a
`TokenKind`; expression and statement nodes use `AstExprKind` and
`AstStmtKind`; assignment targets use `AssignTargetKind`; and unary and binary
operators use `OperatorKind`. Dispatches that own the complete domain use
exhaustive `match` statements without an `else` arm. Helpers that deliberately
accept only a documented subset, such as unary, comparison, or integer-value
operator lowering, use `else` to reject violations of that narrower contract.

The parser returns exact records for program structure, including programs,
product declarations, functions, parameters, fields, and blocks. Every
expression and statement is created by a constructor for its exact shape;
there is no empty or invalid AST kind. Truly optional expressions, currently
bare `ret` values and unsized-array counts, use `AstExprOption` with
`None | Some`. Assignment statements carry one `AstAssignTarget`, so variable,
field, and subscript assignment share the same statement kinds and lowering
path.

Unit-enum declarations and match arms are also exact records. Semantic
analysis resolves each qualified enum member to its declaration-order value,
checks nominal typing and match exhaustiveness, and records the resolved value
for code generation. Enums use one 64-bit scalar slot; match evaluates its
subject once and emits a linear comparison chain.

Integer range loops retain a `ForRange` statement in the AST. Semantic
analysis checks both bounds before introducing a read-only iterator scope.
Code generation stores the end bound in a private stack slot, so both bounds
are evaluated once, and gives `continue` a dedicated iterator-step target.

Unary expressions are recursive AST nodes checked as `i64`. Negation maps to
the assembler's existing `neg` instruction. Logical not materializes `0` or
`1`; conditional branches invert their jump sense directly instead.

This keeps deterministic syntax records precise without creating a separate
wrapper allocation for every expression or statement.

## Code generation

The backend builds private x64 assembly records for Windows x64. Instructions
use concrete builders such as `asm_mov`, `asm_call`, and `asm_ret`; registers,
immediates, symbols, and memory addresses are typed operands rather than text.
Calls follow the Windows x64 ABI and the v0 language limits calls and functions
to four arguments.

Each function receives a statically sized stack frame. A pre-scan computes
local storage and the peak number of compiler temporary slots; there is no
fixed temporary-slot limit.

Runtime assembly helpers implement strings, dynamic byte arrays, command-line
arguments, and file I/O. `embed("path")` stores their raw bytes in the compiler
image at bootstrap time, so a built `epic.exe` parses them into its existing
`AsmProgram` without reading a repository `runtime` directory.

All managed allocation sites call the conservative, non-moving mark-and-sweep
collector in `runtime/gc.asm`. It records exact allocation bases in side
metadata, routes small objects through four slab classes, scans the active stack
and managed payloads conservatively, and reclaims unreachable objects. The
detailed runtime contract is documented in [`gc.md`](gc.md).

## Assembler and PE writer

`src/asm.ep` defines the shared structured assembly representation. An
`AsmProgram` is one ordered stream of section changes, externs, labels,
instructions, and the data forms actually used by Epic. `AsmOperand` is a flat
tagged record for registers, immediates, memory, and symbols; memory addressing
fields are stored directly without a nested allocation. Entry selection is an
explicit program field, and local runtime labels are qualified while parsing.

The encoder consumes only `AsmProgram` and writes AMD64 text/data bytes while
recording symbols and relocations. The text parser exists only for embedded
runtime assembly. Comments, blank lines, and original formatting are discarded;
the renderer produces canonical `-S` text that can be parsed and encoded again.

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
