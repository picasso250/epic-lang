# Epic v4 compiler implementation

This document describes the compiler implementation. User-visible semantics
live in [`language.md`](language.md).

## Bootstrap

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v2 -> Epic v3 -> Epic v4 seed -> Epic v4 fixed point
```

`build_epic.py` resolves the exact commit of the sealed local `v3` branch. A
cached `build/epic-v3-<hash>.exe` is reused when available; otherwise the script
creates a detached v3 worktree and invokes its `build_epic.py`. That v3 compiler
builds the current v4 sources. `bootstrap_fixed_point.py` then checks
that generations 1 and 2 are byte-identical.

## Compiler pipeline

The normal v4 compiler is entirely written in Epic:

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
Calls follow the Windows x64 ABI. The first four integer, pointer, or reference
arguments use `RCX`, `RDX`, `R8`, and `R9`; later arguments occupy 8-byte caller
stack slots after the 32-byte shadow space. One lowering path serves ordinary
Epic functions, source externs, and the transitional `os.*` bindings. Callees
copy both register and stack parameters into their statically assigned local
slots.

Address-taking is resolved in semantic analysis only for `ptr(top_level_fun)`.
The checker rejects `main`, externs, builtins, unknown names, and signatures that
use non-extern ABI types. Code generation lowers the marked function operand to
`lea rax, [function_symbol]`; it emits no trampoline. Direct calls and Windows
callbacks therefore share the same entry, prologue, parameter-copy logic, and
return-width behavior.

Each function receives a statically sized stack frame. A pre-scan computes
local storage and the peak number of compiler temporary slots; there is no
fixed temporary-slot limit.

Integer and bool locals/parameters use 8-byte stack slots, while product fields
and array elements use their natural 1-, 2-, 4-, or 8-byte size and alignment.
The low N bits of an integer expression are authoritative; upper register bits
need not be canonical. Code generation extends only at an explicit widening
conversion, when forming a 64-bit address, or for division lowering. The
private assembler encodes 16-bit operands plus `movzx`,
`movsx`, and `movsxd` for these boundaries.

The polymorphic `is_null` builtin is checked in semantic analysis against the
reference categories and lowered in value position to `test rax, rax` plus
`sete al`. Conditional code uses the ordinary bool path; the compiler adds
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

Raw callback entries rely on the same single active-stack boundary initialized
by `main`. They are therefore supported only for synchronous reentry on the
owner OS thread. That stack remains below `_gc_stack_high`, so callback code may
allocate and trigger collection. The runtime does not register foreign threads,
scan multiple stacks, serialize concurrent callbacks, or validate the calling
thread.

The runtime string header is `{owner, offset, len}`. `owner` is always the exact
base of the managed byte allocation, which matters because the collector does
not treat interior pointers as roots. String slicing allocates a header, keeps
the same owner, adds to the offset, and changes the length. `bytes(str)` and
`str(u8[])` currently copy to preserve snapshot semantics in both directions;
the opaque array mutation surface leaves room for a later copy-on-write
implementation without changing observable behavior. `cstr(str)` is separate:
it allocates a fresh byte region and appends the terminator required by C.

v4 dogfoods string slicing for lexer token views, type-name suffix removal,
integer suffix parsing, assembler substrings, and relative embed paths. The
transitional v3 `str_new`, `.data`, and `.len` source interfaces are removed;
there is no compiler-source exception. `ptr` is now the single public opaque
address type. Integer conversions preserve its 64-bit pattern, array conversion
loads the backing-data field, product conversion preserves the payload address,
and `cstr(str)` returns a fresh terminated allocation. `ptr(str)` is rejected.

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
`-S` rendering; parser output after the text boundary is index-based. External
symbols may additionally carry their exact source DLL and export names. Source
externs use anonymous internal symbols, so they cannot collide with transitional
runtime imports that happen to use the same export spelling. Canonical assembly
renders the DLL and export bytes in an `extern_dll` directive as hexadecimal,
so `-S` render/parse/encode preserves both names without quoting ambiguity.

The encoder consumes only `AsmProgram`, fills symbol section/offset data, and
writes AMD64 text/data bytes while recording already-indexed relocations. It
validates referenced symbols in one linear pass instead of recovering indexes
with relocation-by-symbol string searches. Comments, blank lines, and original
runtime formatting are discarded; the renderer produces canonical `-S` text
that can be parsed and encoded again.

`src/pe.ep` writes a deterministic Windows PE executable, including headers,
sections, imports, and relocations. Referenced source externs are grouped by DLL
in deterministic relocation order. The writer emits import descriptors, ILT,
IAT, hint/name entries, and DLL names, then patches each generated text thunk to
jump indirectly through its IAT slot. Unreferenced declarations create no PE
import. Determinism is part of the bootstrap contract: identical compiler
sources must produce byte-identical fixed-point executables.

## Acceptance

Run the maintained checks in this order:

```powershell
python tests/run.py
python tests/examples/run.py
python bootstrap_fixed_point.py
```

The self-contained suite first copies only `epic.exe` into an isolated
directory and verifies that it can compile a program using an embedded byte
resource. Public examples are compiled individually and normally executed;
`# COMPILE_ONLY` examples must produce an executable but are not started. End-to-end test
sources remain independent, but their runner generates one temporary bundle,
compiles it once, and starts that executable separately for each case. This
preserves process isolation without producing one tiny PE per regression. The
GC suite separately exercises retained stack and heap references under bounded
memory pressure.
