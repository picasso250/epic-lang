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

The nine compiler source files are compiled as one program:

```text
src/epic.ep
src/asm.ep
src/codegen.ep
src/lexer.ep
src/parser.ep
src/pe.ep
src/sema.ep
src/types.ep
src/utils.ep
```

The self-hosted generations do not invoke NASM or an external linker. NASM is
only part of the trusted Python stage-0 route used to create the first seed.

## Type model

Parser annotations, semantic signatures and locals, resolved AST values, and
code generation share one structural `TypeRef` representation from
`src/types.ep`. Builtin scalar, string, pointer, control, and `never` types have
distinct enum kinds. User products and enums are both nominal `Named(name)`
leaves; semantic declaration tables determine which declaration kind a name
denotes. Arrays recursively contain their element `TypeRef`, so equality walks
the structure and never depends on allocation identity. `Function(params,
result)` is likewise recursive and structural; hidden closure capture layouts
do not participate in public function type identity.

`TypeRef` values are immutable by convention and are not interned. Equal types
may therefore be separate allocations. `type_equal` is the semantic equality
operation, while `type_text` is used only at diagnostics and other text
boundaries. A null AST `resolved_type` means semantic analysis has not checked
that node; every real type, including internal `never`, is represented by a
non-null `TypeRef`.

Polymorphic builtins such as `len`, `is_null`, `push`, `pop`, and `extend` are
checked explicitly rather than encoding fake signature types. Backend layout
metadata remains separate: `StructInfo` owns product sizes, alignments, field
offsets, and field `TypeRef` values, while scalar and array element sizes are
derived from their structural kinds.

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

`Call` stores an arbitrary callee expression plus its argument list. Named
calls are not a separate AST or semantic path. `Closure` stores explicit
parameter/result types and its body; semantic analysis assigns a stable closure
ID and a first-lexical-use capture list. Resolved variable and assignment nodes
carry value-symbol IDs, allowing code generation to distinguish shadowed locals
and captured storage without redoing name lookup.

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

Every Epic callable value is one word pointing at an entry-first descriptor.
Top-level functions use static `[entry]` descriptors. Evaluating a closure
allocates `[entry, capture 0, capture 1, ...]` in managed storage and copies the
current values into fixed eight-byte capture slots. Closure entries receive
the descriptor/context pointer in volatile `R10`, save it in their stack frame,
and use ordinary Windows x64 lanes for source parameters. Nested calls may
therefore clobber `R10` without losing access to captures.

Known top-level and extern calls remain direct. General calls evaluate and spill
the callee first, evaluate arguments left-to-right, null-check the descriptor,
load its entry into `R11`, and use an indirect register call. A null descriptor
jumps to the allocation-free diagnostic in `runtime/callable.asm`. The private
assembler encodes both relative-symbol calls and AMD64 `call r/m64`.

Semantic value lookup is one lexical chain: current locals and captures, module
functions, then the builtin prelude. Block bindings are assigned stable IDs
after their initializer is checked, while module functions are collected before
bodies. An inner closure that reaches through multiple closure levels causes
each intermediate environment to capture the original symbol ID, so every
runtime construction copies from its immediate enclosing frame or context.

Address-taking is resolved in semantic analysis only for `ptr(top_level_fun)`.
The checker rejects `main`, externs, builtins, unknown names, and signatures that
use non-extern ABI types. Code generation lowers the marked function operand to
`lea rax, [function_symbol]`; it emits no trampoline. Direct calls and Windows
callbacks therefore share the same entry, prologue, parameter-copy logic, and
return-width behavior. Internal callable descriptors, indirect function values,
and closures never cross the extern ABI; semantic analysis accepts the callback
special case only when the operand directly resolves to a top-level function.

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
product, string, array, callable, and raw-pointer reference categories and lowered in value position to `test rax, rax` plus
`sete al`. Conditional code uses the ordinary bool path; the compiler adds
no builtin-specific branch optimization or implicit dereference guard.

Runtime assembly helpers implement strings, dynamic byte arrays, command-line
arguments, file I/O, and allocation-free panic reporting. `embed("path")` stores their raw bytes in the compiler
image at bootstrap time, so a built `epic.exe` parses them into its existing
`AsmProgram` without reading a repository `runtime` directory.

All managed allocation sites call the conservative, non-moving mark-and-sweep
collector in `runtime/gc.asm`. It records exact allocation bases in side
metadata, routes small objects through four slab classes, scans the active stack
and managed payloads conservatively, and reclaims unreachable objects. Closure
environments are ordinary managed payloads, so captured arrays, products,
strings, and nested closures remain reachable without a separate descriptor or
capture-count table. The
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
import. The driver emits `IMAGE_SUBSYSTEM_WINDOWS_CUI` by default and switches
the Optional Header to `IMAGE_SUBSYSTEM_WINDOWS_GUI` only for
`--windows-gui`; this PE-only option is rejected with `-S`. Determinism is part
of the bootstrap contract: identical compiler sources must produce
byte-identical fixed-point executables.

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
