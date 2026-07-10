# Finding Silly Code

This document records a practical performance triage method for Epic's compiler and self-hosted compiler.

The goal is not to chase every large function. The goal is to find code where the source program already knows a fact, but the generated MIR still spends a lot of control flow proving it again.

## What “silly code” means

“Silly” code is not merely slow code. It is code with an information gap:

- the source-level program already knows the shape or type of a value;
- the implementation loses that knowledge across an expression, helper boundary, container, or projection;
- the generated MIR reconstructs the same fact with repeated tags, strings, branches, or field dispatch.

In this project, the strongest examples appeared after dogfooding the full AST as an ADT. Many AST values were semantically known to be `AstCall`, `AstFunDef`, `AstMatchCase`, and so on, but the code kept treating them as `AstNode` and paid for large union projections.

The key question is:

> Is this function large because it is doing real compiler work, or because it forgot something the source already knew?

## Primary signals

Start with generated size, not wall time. Wall time is noisy; generated size is usually more stable.

Useful signals:

- MIR function instruction count.
- MIR function block count.
- Total MIR instructions and blocks.
- X64 item count.
- X64 instruction count.
- Assembly bytes.
- Fixed-point compiler time, after size changes are understood.

The normal workflow is:

```text
measure total MIR / x64 size
sort MIR functions by instruction count
inspect top functions for repeated dispatch
make the smallest source-level narrowing change
measure again
run fixed point
```

## How to measure

Use the checked-in triage tool from the repository root:

```powershell
python tools/mir_top_funcs.py --top 40
```

It prints:

- parse/sema/AST-to-MIR timings;
- total MIR blocks and instructions;
- the largest MIR functions by instruction count;
- x64 lowering time, items, instructions, labels, data items, and asm bytes.

For before/after comparisons, save a baseline and compare against it:

```powershell
python tools/mir_top_funcs.py --json build/before.json
python tools/mir_top_funcs.py --compare build/before.json
```

For quick iteration where x64 size is not needed:

```powershell
python tools/mir_top_funcs.py --no-x64 --top 60
```

For correctness and fixed-point validation, use the normal test entry points:

```powershell
python tests/run.py
python test_examples.py
python test_bootstrap_fixed_point.py
```

## Ranking a large function

A large function is not automatically bad. Classify it first.

Likely real work:

- lexer state machines;
- backend instruction emission;
- runtime helper assembly/data emission;
- unavoidable language-level dispatch in a central pass.

Likely silly work:

- many blocks that all load the same field at the same offset;
- repeated `ast_kind()` checks in code that could use `match`;
- helper functions taking `AstNode` after the caller already matched a concrete variant;
- arrays typed as `AstNode[]` even though a specific accessor returns only one variant kind;
- common direct fields in all ADT variants still using tag dispatch;
- guarded field access that redoes the guard's work.

The ranking rule is:

1. Prefer changes that remove duplicated proof work.
2. Prefer changes whose correctness follows from existing language rules or layout contracts.
3. Prefer local source rewrites before backend cleverness.
4. Stop when the remaining large functions are doing real compiler work.

## Pattern 1: string kind dispatch instead of `match`

Bad shape:

```epic
if ast_kind(expr) == "Binary" {
    ret emit_binary(expr.left, expr.right)
}
```

Better shape:

```epic
match expr {
    AstBinary n: {
        ret emit_binary(n.left, n.right)
    }
    _: {}
}
```

Why it matters:

- `ast_kind()` itself is a tag-to-string dispatcher.
- The subsequent `expr.left` access often performs another union projection.
- The string comparison adds work and obscures the compiler's knowledge.

Use `match` when the code is branching on an ADT variant and then accesses fields from that variant.

## Pattern 2: lost narrowing across helper boundaries

Bad shape:

```epic
match expr {
    AstCall n: {
        ret sema_call_type(st, expr)
    }
    _: {}
}

fun sema_call_type(st: SemaState, node: AstNode): str {
    if node.name == "print" { ... }
    ...
}
```

Better shape:

```epic
match expr {
    AstCall n: {
        ret sema_call_type(st, n)
    }
    _: {}
}

fun sema_call_type(st: SemaState, node: AstCall): str {
    if node.name == "print" { ... }
    ...
}
```

The caller already proved `AstCall`. Passing the original `AstNode` throws that proof away and makes the callee rediscover it through union field projection.

This also applies to MIR helpers:

```epic
fun mir_emit_struct_init(st: MirCodegenState, block: MirBlock, expr: AstStructInit): MirValueFlow
fun mir_emit_match(st: MirCodegenState, block: MirBlock, stmt: AstMatch): MirBlockFlow
```

## Pattern 3: homogeneous `AstNode[]` without element narrowing

Some lists are truly heterogeneous, for example call arguments or block statements. Other lists are semantically homogeneous and should be represented with the narrowest element type practical.

The core AST buckets and homogeneous child lists are narrow:

- `program.funcs` is `AstFunDef[]`.
- `program.structs` is `AstStructDef[]`.
- `program.globals` is `AstLet[]`.
- `program.unions` is `AstUnionDef[]`.
- `struct.fields` is `AstStructField[]`.
- `fun.params` is `AstParam[]`.
- `match.fields` is `AstMatchCase[]`.
- `struct_init.fields` is `AstInitField[]`.
- function, loop, and match-case bodies are `AstBlock`.
- `if.then_block` is `AstBlock`.

Keep `AstNode[]` for truly heterogeneous lists, such as block statements, call arguments, array literal expressions, and f-string parts. Keep `AstNode` for optional block slots such as `else_block` until there is a dedicated optional-block representation.

Bad shape:

```epic
let field = ast_new_struct_field()
ast_set_name(field, token_text(fname))
ast_fields(node).push(field)
```

Better shape:

```epic
let field = ast_new_struct_field()
field.name = token_text(fname)
node.fields.push(field)
```

Once the parser knows a child has a concrete type, keep that type until the value actually crosses into a heterogeneous AST position. Downstream code should trust concrete container element types instead of re-matching every element.

The same rule applies to AST constructors. `ast_new_*` should return the concrete payload type, not `AstNode`. Wrap with `new AstNode(payload)` only at heterogeneous boundaries such as block statements, expression operands, call arguments, and optional expression fields.

Single-use AST constructors should usually be deleted and replaced with direct struct literals at the construction site. Keep only constructors that are reused or encode a real semantic sentinel, such as common default block/param/literal builders.

## Pattern 4: uniform union projection still using tag dispatch

Bad generated shape:

```text
if tag == AstLet:
    meta = load [payload + 0]
elif tag == AstVar:
    meta = load [payload + 0]
elif tag == AstBinary:
    meta = load [payload + 0]
...
```

Better generated shape:

```text
payload = load [node + payload]
meta    = load [payload + 0]
```

This is safe only under a strict uniformity rule:

- every union member has a direct field with the same name;
- the field has the same MIR type in every member;
- the field has the same field index in every member;
- non-uniform direct fields fall back to tag dispatch; partial fields are rejected.

This handles `node.meta` in the AST ADT without special-casing `AstMeta` by name.

## Pattern 5: repeated proof after a guard

Bad shape:

```epic
if ast_kind(node) == "FieldAccess" {
    if ast_kind(node.object) == "Var" {
        ... node.object.name ...
    }
}
```

Better shape:

```epic
match node {
    AstFieldAccess field: {
        match field.object {
            AstVar receiver: {
                ... receiver.name ...
            }
            _: {}
        }
    }
    _: {}
}
```

The point is not only style. The nested `match` preserves the payload identity all the way down.

## Measurement discipline

After each change, record both local and global numbers:

- the targeted functions before and after;
- total MIR blocks/instructions;
- total x64 items/instructions;
- assembly bytes;
- fixed-point times;
- executable size.

Do not overfit to one noisy wall-time run. Treat size reductions and repeated fixed-point runs as stronger evidence than a single elapsed time number.

A good change usually has this signature:

```text
target function blocks drop sharply
target function instructions drop sharply
total MIR drops proportionally
x64 items and asm bytes drop similarly
fixed point still reaches equality
```

## Case study: AST ADT dogfood

During the full parser AST ADT work, the compiler became much larger because common AST knowledge was lost. The worst generated code came from `ast_kind()` chains, `AstNode` helper parameters, homogeneous `AstNode[]` lists, and uniform common-field projections.

The cleanup series used this method to find and remove those losses. The exact wall time varies by run, but the size trend was stable:

| Metric | Before | After | Change |
|---|---:|---:|---:|
| MIR instructions | 105,254 | 49,189 | -53.3% |
| MIR blocks | 18,866 | 7,798 | -58.7% |
| x64 items | 610,327 | 286,544 | -53.1% |
| x64 instructions | 587,944 | 275,211 | -53.2% |
| asm bytes | 15,297,109 | 7,194,510 | -53.0% |
| MIR -> x64 time | 2.271s | 1.119s | -50.7% |
| self-hosted exe size | 2.06 MiB | 1.24 MiB | -39.8% |

Representative local wins:

| Function | Before | After |
|---|---:|---:|
| `mir_emit_expr` | 9,469 inst / 1,710 blocks | 1,636 inst / 155 blocks |
| `sema_call_type` | 6,837 inst / 1,337 blocks | 417 inst / 79 blocks |
| `sema_build_types` | 4,523 inst / 864 blocks | 425 inst / 60 blocks |
| `ast_resolved_type` | 459 inst / 91 blocks | 9 inst / 1 block |
| `mir_emit_match` | 1,148 inst / 183 blocks | 502 inst / 59 blocks |
| `sema_expr_is_exit` | 558 inst / 116 blocks | 46 inst / 15 blocks |

The most important lesson was not any single optimization. The lesson was to preserve semantic knowledge as close as possible to the source construct that established it.

## When to stop

Stop this style of cleanup when the top functions are large because they do real work.

Examples of “probably real work”:

- central semantic dispatch that has already switched from string kind checks to `match`;
- central MIR emit dispatch that already preserves narrowing;
- machine instruction encoding;
- linker and COFF symbol construction;
- runtime helper emission.

At that point, switch from “silly code” cleanup to normal profiling, data-structure design, or backend optimization.

### Pattern 4: string keys hiding structured layout

Bad shape:

```epic
let key = str_cat2(str_cat2(struct_name, "."), field_name)
struct_field_keys.push(key)
```

If the key is only encoding multiple known fields, introduce a small record instead. Prefer `MirStructFieldLayout { struct_name, field_name, field_type, field_index }` over parallel arrays keyed by `"Struct.field"` strings. String labels are fine for diagnostics, but they should not be the internal representation of typed layout data.

### Pattern 5: type-name special cases before structural rules

Bad shape:

```epic
if base_type == "AstNode" {
    ret special_union_field_path(...)
}
```

Prefer structural rules over type-name exceptions. For union field access, allow only common direct fields, then reject variant-only fields through the normal union rules. If source code needs a variant-only field from a union value, make the variant explicit with `match` instead of adding a type-name special case to sema or MIR lowering.

### Pattern 6: numeric identity disguised as a string

If a value is created by a monotonic counter and its text name is used only as a lookup key, keep the counter value as the identity. MIR locals use positive numeric IDs; `%1` is text syntax, while the object model stores `1`. This lets MIR→x64 index slot, liveness and definition-block arrays directly instead of formatting generated names and maintaining several string-keyed maps.
