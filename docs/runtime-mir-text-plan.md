# Runtime helpers as MIR text plan

## Context

The self-hosted compiler currently keeps runtime helper generation as builder-style Epic code in `src/mir_runtime.ep`, originally generated from `bootstrap/mir_runtime_helpers.py` by `build/gen_mrh_ep.py`.

That path was useful during the fast bootstrap phase, but it has a large meta-code expansion cost:

```text
Python helper emitter
  -> generated Epic helper emitter
    -> compiler runtime constructs MirFunction/MirBlock/MirInst
```

Recent size work showed that many helpers are tiny in final runtime code, but very large as emitter code. Sharing emitters reduced the compiler executable from roughly `1,845,248` bytes to roughly `1,486,848` bytes, about a 19% reduction. This confirms the main size problem is not only final runtime helper duplication; it is also the builder-style meta-code used to construct helpers.

This document plans a larger architectural spike: represent runtime helpers directly as MIR text and parse them into `MirFunction` values.

## Goal

Move toward this path:

```text
runtime helpers written as MIR text
  -> Python bootstrap parses MIR text
  -> Epic self-hosted compiler parses MIR text
  -> parsed helpers are injected into MirProgram
```

The long-term objective is to retire or greatly shrink:

```text
build/gen_mrh_ep.py
bootstrap/mir_runtime_helpers.py builder emitters
src/mir_runtime.ep builder emitters
```

The immediate objective is smaller: prove whether this direction is worth pursuing.

The primary decision driver is still compiler executable size, not architectural elegance by itself. MIR text infrastructure is expected to create future positive value for reviewability, fixtures, roundtrips, and optimizer testing, but the spike should not assume that value is guaranteed. Treat parser size and compile-time cost as real costs that must be measured.

Because the MIR text parser has a fixed cost, do not judge the direction only after migrating a single helper. The first meaningful decision point is after migrating the complete word-slice group:

```text
__ep_slice_i64_new/get/set/push
__ep_slice_ptr_new/get/set/push
```

At that point, executable size should be close to flat or smaller, fixed-point compile time should not regress materially, and the MIR text should be clearly easier to review than builder-style emitter code.

## Questions to answer

The spike should answer these questions:

1. Can a MIR text format express current runtime helpers without losing information?
2. Can the MIR text parser stay small enough that code size still goes down?
3. Can Python bootstrap and Epic self-host consume the same MIR text format?
4. Does compiler executable size decrease after migrating real helpers?
5. Does fixed-point compile time remain acceptable?
6. Can this produce a cleaner workflow for testing MIR passes, MIR roundtrips, and future optimizers?

## Non-goals for the first spike

Do not immediately replace all of `src/mir_runtime.ep`.

Do not design a complete public MIR assembly language.

Do not support all possible MIR constructs. The initial parser only needs the subset required by runtime helpers.

Do not make the compiler depend on external runtime files in the first step. Prefer embedded text for the first self-hosted spike.

## Current runtime helper categories

Runtime helpers should be inventoried before migration.

Suggested categories:

```text
A. Tiny forwarding helpers
   __ep_slice_u8_from_str
   __ep_str_from_slice_u8

B. Word slice helpers
   __ep_slice_i64_new/get/set/push
   __ep_slice_ptr_new/get/set/push

C. Byte slice helpers
   __ep_slice_u8_alloc/get/set/push/slice/extend

D. String helpers
   __ep_str_eq
   __ep_str_cmp
   __ep_str_cat

E. Map helpers
   __ep_map_str_find_pos
   __ep_map_str_i64_new/get/set/has/del
   __ep_map_str_bool_new/get/set/has/del
   __ep_map_str_str_new/get/set/has/del

F. Runtime-adjacent helpers
   oob/null/panic/exit related helpers, if any
```

For each helper, collect:

```text
helper name
MIR instruction count
machine text bytes
has branches?
has loops?
has external calls?
uses slice/map/string helpers?
current emitter size in size_profile
```

Use `scripts/size_profile.py` plus a small temporary script for helper-level details.

## Proposed MIR text shape

Example target syntax:

```text
fn __ep_slice_i64_get(ptr %arr, i64 %idx) -> i64 {
entry:
  %gep0: ptr = gep ptr ptr %arr, i64 1
  %load1: i64 = load i64 ptr %gep0
  %cmp2: bool = icmp.sge i64 %idx, i64 0
  condbr bool %cmp2, label %check_high, label %fail

check_high:
  %cmp3: bool = icmp.slt i64 %idx, i64 %load1
  condbr bool %cmp3, label %ok, label %fail

ok:
  %gep4: ptr = gep ptr ptr %arr, i64 0
  %load5: ptr = load ptr ptr %gep4
  %gep6: ptr = gep i64 ptr %load5, i64 %idx
  %load7: i64 = load i64 ptr %gep6
  ret i64 %load7

fail:
  call void ExitProcess(i64 1)
  ret i64 0
}
```

The first parser should support only what current runtime helpers need:

```text
function signatures
basic block labels
result instructions
void/non-result instructions
ret
br
condbr
call
gep
load
store
icmp.*
binary ops used by helpers
constant integers
null operands
value operands
label operands
```

Avoid supporting advanced syntax until needed.

The parser should be deliberately narrow and fail-fast. It is an internal runtime-helper format, not a public MIR assembly language. Do not add syntax sugar, inference, optional annotations, or compatibility forms unless a migrated helper needs them.

Prefer the existing MIR dump text as the canonical syntax. Python already has `bootstrap/mir.py` `text()` methods, and Epic already has `src/mir.ep` `mir_*_text` helpers / dump printing. The MIR text parser should accept that existing dump shape unless a concrete problem makes the dump format unreasonable as parser input. Any divergence from dump syntax should be explicitly documented and justified.

## Embedding strategy

There are two possible ways to provide MIR text to the compiler.

### Option A: external `.mir` files

Pros:

```text
compiler executable is smaller
runtime helpers are easy to edit and diff
MIR text can be tested independently
```

Cons:

```text
compiler distribution depends on extra files
path handling becomes part of the compiler contract
fixed point needs stable file layout
```

### Option B: embedded MIR text strings

Pros:

```text
single executable remains self-contained
fixed point is simpler
runtime helper content is deterministic
```

Cons:

```text
MIR text lives in executable data
editing requires rebuilding compiler
```

Use Option B for the first self-hosted spike. Option A can be added later.

## Phase 0: inventory and baselines

Before writing parser code, record current baseline values:

```powershell
python scripts/size_profile.py 30
python test_bootstrap_fixed_point.py
```

Record:

```text
exe size
MIR function text bytes total
x64_items
machine text_bytes
fixed point stage time
```

Also create a runtime helper inventory table.

## Phase 1: Python-only MIR text parser spike

Use the existing small Python MIR parser as the Python-side parser:

```text
bootstrap/mir_parser.py
```

It already parses canonical MIR dump-style `MirProgram` text and is already wired into `bootstrap/mir_runtime_helpers.py` as an optional `runtime/mir/*.mir` override path. Do not add a second Python parser unless the existing one proves structurally wrong.

Add one MIR text file or embedded test string:

```text
runtime/mir/slice_i64_get.mir
```

The current Python parser API is:

```python
parse_mir_text(text: str, filename: str = "<mir>") -> MirProgram
parse_mir_file(path) -> MirProgram
```

Initial validation should be structural:

```text
function name
params
return type
block count
instruction count
terminators
selected op/operand checks
```

At first, do not change the runtime injection path. Just parse and test.

Suggested test:

```text
tests/mir_text_parser/test_slice_i64_get.py
```

## Phase 2: Python injection experiment

After parser-only tests pass, route one helper through MIR text in the Python bootstrap runtime injection path.

Start with:

```text
__ep_slice_i64_get
```

Keep all other helpers on the existing emitter path.

Validation:

```powershell
python tests/mir/run.py
python tests/ast_to_mir/run.py
python tests/run.py
python test_bootstrap_fixed_point.py
```

The goal is not size reduction yet. The goal is correctness and a clean integration seam.

## Phase 3: Epic-side parser spike

If the Python experiment is clean, implement the same subset parser in Epic. Python can use regular expressions, but Epic currently should not depend on regex. Prefer a tiny dedicated lexer plus parser:

```text
src/mir_lexer.ep
src/mir_parser.ep
```

Possible API:

```epic
fun parse_mir_text(text: str): MirProgram
```

The Epic parser should accept the same canonical dump-style syntax as the Python parser. Do not mechanically port the Python regex implementation; implement explicit tokenization and fail-fast parsing for the supported MIR subset. The Epic MIR lexer should be dedicated and tiny, not reused from the Epic source lexer. A line-oriented lexer/parser is acceptable and probably preferred for the first version. The Epic parser API may return `MirProgram` to match Python, but the first implementation should only parse `define` functions. Do not implement `import`, `declare`, `global`, or a full Epic-side `validate(program)` unless a runtime/mir fixture forces it. Prefer keeping Epic implementation simple and relying on existing end-to-end tests plus Python-side validation/tooling for deeper structural checks. Runtime helper `.mir` fixtures should contain `define` functions only in the first phase; do not put `declare`, `import`, or `global` records in `runtime/mir` unless the migration explicitly decides to widen the Epic parser.

For the first self-hosted experiment, embed the MIR helper text as a string constant or a small generated string-returning function.

Validation should compare Python/Epic parse output using an existing MIR dump or a new canonical MIR dump.

## Phase 4: migrate one medium helper

After both parsers exist, migrate one helper end-to-end.

Preferred order:

```text
1. __ep_slice_i64_get
2. __ep_slice_ptr_get
3. __ep_slice_i64_push
4. __ep_slice_ptr_push
```

This order covers:

```text
i64 return
ptr/null return
void return
bounds checks
external call ExitProcess
more complex control flow and stores
```

Each migration should be one commit or one very small group of commits.

## Phase 5: compare results

For each migration, record:

```text
exe size
MIR function text bytes total
x64_items
machine text_bytes
text reloc count
fixed point time
parser size contribution
```

Commands:

```powershell
python scripts/size_profile.py 30
python test_bootstrap_fixed_point.py
python tests/run.py
```

Decision rule:

```text
If parser + MIR text is smaller and not significantly slower, continue migrating.
If parser size overwhelms removed emitters, stop and keep current shared emitter approach.
```

## Phase 6: migrate by groups

If the spike succeeds, migrate helpers in groups.

### Group 1: word slices

```text
__ep_slice_i64_new/get/set/push
__ep_slice_ptr_new/get/set/push
```

### Group 2: byte slices and strings

```text
__ep_slice_u8_alloc/get/set/push/slice/extend
__ep_str_eq
__ep_str_cmp
__ep_str_cat
```

### Group 3: maps

```text
__ep_map_str_find_pos
__ep_map_str_i64_new/get/set/has/del
__ep_map_str_bool_new/get/set/has/del
__ep_map_str_str_new/get/set/has/del
```

### Group 4: cleanup

Remove migrated builder emitters from:

```text
src/mir_runtime.ep
bootstrap/mir_runtime_helpers.py
```

Eventually retire:

```text
build/gen_mrh_ep.py
```

## Testing requirements

Every migration step should pass:

```powershell
python tests/mir/run.py
python tests/ast_to_mir/run.py
python test_bootstrap_fixed_point.py
python tests/run.py
```

Add parser-specific tests:

```text
parse known helper
reject malformed function signature
reject missing terminator
reject unknown operand form
roundtrip through canonical MIR dump, if/when available
```

## Risks and mitigations

### Parser becomes too large

Mitigation:

```text
Keep syntax minimal.
Avoid a general-purpose language parser.
Only support runtime-helper MIR subset.
Measure parser contribution with size_profile.
```

### Python and Epic parser diverge

Mitigation:

```text
Use the same MIR fixture files.
Add Python/Epic dump comparison tests.
Keep grammar deliberately small.
```

### External files complicate distribution

Mitigation:

```text
Start with embedded text strings.
Add external file mode only later.
```

### MIR text format becomes unstable

Mitigation:

```text
Define a canonical dump format.
Make parse(dump(mir)) a testable invariant.
```

### Migration changes runtime semantics

Mitigation:

```text
Migrate one helper at a time.
Compare MIR dumps before/after when possible.
Run fixed point after every step.
Add direct tests for migrated helpers.
```

## Recommended first implementation step

Do not connect MIR text to runtime injection immediately.

First commit should only add or update:

```text
parser tests for existing bootstrap/mir_parser.py
runtime/mir/slice_i64_get.mir
a small injection-path test
```

Then inspect:

```text
parser complexity
syntax clarity
how hard it is to compare parsed helper with existing emitted helper
```

Only after that should the Python injection path use the parsed helper.

## Success criteria

The direction is considered worth continuing if:

```text
MIR text parser remains small
one helper can be parsed and injected correctly
fixed point still reaches stability
size either improves or has a clear path to improve after larger migrations
runtime helper MIR text is easier to read than builder-style emitter code
```

## Stop criteria

Stop the migration and continue with shared emitters if:

```text
parser code becomes larger than the emitters it replaces
MIR text needs too many special cases
Python/Epic parser divergence becomes painful
compile time regresses significantly
fixed point becomes unstable
```
