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
there is no empty or invalid AST kind. `AstBlock` stores ordinary statements
separately from an optional tail expression. Truly optional expressions,
including bare `ret` values, unsized-array counts, and block tails, use
`AstExprOption` with `None | Some`. Assignment statements carry one
`AstAssignTarget`, so variable, field, and subscript assignment share the same
statement kinds and lowering path.

`if` and `match` live only in `AstExprKind`; there are no parallel statement
nodes. Their statement forms are ordinary expression statements whose result is
discarded. Semantic analysis assigns every block and expression a resolved type,
using internal `never` as the bottom type when control cannot complete normally.
Branch and arm types are joined in value context. Statement/`void` context
checks every branch but discards their tail values.

Unit-enum declarations and match arms are exact records. Semantic analysis
resolves each qualified enum member to its declaration-order value, checks
nominal typing and match exhaustiveness, records the resolved value for code
generation, and joins all arm block types. Enums use one 64-bit scalar slot;
match evaluates its subject once and emits a linear comparison chain whose
selected arm leaves its value in `rax`.

Integer range loops retain a `ForRange` statement in the AST. Semantic
analysis checks both bounds before introducing a read-only iterator scope.
Code generation stores the end bound in a private stack slot, so both bounds
are evaluated once, and gives `continue` a dedicated iterator-step target.

Integer literals stay as raw token text through lexing and parsing. Semantic
analysis resolves suffixes or contextual types, checks the mathematical range,
and records the low 64-bit pattern on the AST. Unary negation and integer
operations retain their operand width; logical results are `bool`.

This keeps deterministic syntax records precise without creating a separate
wrapper allocation for every expression or statement. `Slice` expressions
carry an exact base, start, and end. They deliberately have no assignment-target
counterpart.

## Code generation

The backend builds private x64 assembly records for Windows x64. Instructions
use concrete builders such as `asm_mov`, `asm_call`, and `asm_ret`; registers,
immediates, symbols, and memory addresses are typed operands rather than text.
Calls follow the Windows x64 ABI and the v0 language limits calls and functions
to four arguments.

Each function receives a statically sized stack frame. A pre-scan computes
local storage and the peak number of compiler temporary slots; there is no
fixed temporary-slot limit.

Integer and bool locals/parameters use 8-byte stack slots, while product fields
and array elements use their natural 1-, 2-, 4-, or 8-byte size and alignment.
The low N bits of an integer expression are authoritative; upper register bits
need not be canonical. Code generation extends only at a widening conversion,
when forming a 64-bit address, at an approved v3 compatibility boundary, or for
division lowering. The private assembler encodes 16-bit operands plus `movzx`,
`movsx`, and `movsxd` for these boundaries.

The polymorphic `is_null` builtin is checked in semantic analysis against the
reference categories and lowered in value position to `test rax, rax` plus
`sete al`. Conditional code uses the ordinary bool path; v3 deliberately adds
no builtin-specific branch optimization or implicit dereference guard.

Runtime assembly helpers implement strings, dynamic byte arrays, command-line
arguments, file I/O, and allocation-free panic reporting. `embed("path")` stores their raw bytes in the compiler
image at bootstrap time, so a built `epic.exe` parses them into its existing
`AsmProgram` without reading a repository `runtime` directory.

All managed allocation sites call the conservative, non-moving mark-and-sweep
collector in `runtime/gc.asm`. It records exact allocation bases in side
metadata, routes small objects through four slab classes, scans the active stack
and managed payloads conservatively, and reclaims unreachable objects. The
detailed runtime contract is documented in [`gc.md`](gc.md).

The runtime string header is `{owner, offset, len}`. `owner` is always the exact
base of the managed byte allocation, which matters because the collector does
not treat interior pointers as roots. String slicing allocates a header, keeps
the same owner, adds to the offset, and changes the length. `bytes(str)` and
`str(u8[])` currently copy to preserve snapshot semantics in both directions;
the opaque array mutation surface leaves room for a later copy-on-write
implementation without changing observable behavior. `cstr(str)` is separate:
it allocates a fresh byte region and appends the terminator required by C.

The v3 source still uses private `str_new`, `.data`, and `.len` bridges in the
files compiled by the v2 seed. Semantic analysis exposes those bridges only to
the known compiler source paths. They are scheduled to disappear when v4 can
dogfood slicing and `cstr()` directly.

## Assembler and PE writer

`src/asm.ep` defines the shared structured assembly representation. An
`AsmProgram` owns one symbol table plus an ordered stream of section changes,
externs, labels, instructions, and the data forms actually used by Epic.
`AsmOperand`, symbol-bearing items, entry selection, and relocations carry
stable symbol indexes rather than repeating symbol-name strings. Memory
addressing fields are stored directly without a nested allocation.

Code generation allocates anonymous labels directly by index. The embedded
runtime text parser interns names when they first appear, so forward references
receive an index immediately and definitions later complete the same symbol.
Names remain on symbol-table entries for imports, diagnostics, and canonical
`-S` rendering; parser output after the text boundary is index-based.

The encoder consumes only `AsmProgram`, fills symbol section/offset data, and
writes AMD64 text/data bytes while recording already-indexed relocations. It
validates referenced symbols in one linear pass instead of recovering indexes
with relocation-by-symbol string searches. Comments, blank lines, and original
runtime formatting are discarded; the renderer produces canonical `-S` text
that can be parsed and encoded again.

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
