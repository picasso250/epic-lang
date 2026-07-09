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
- common embedded fields in all ADT variants still using tag dispatch;
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

`AstProgram` top-level buckets are already narrow:

- `program.funcs` is `AstFunDef[]`.
- `program.structs` is `AstStructDef[]`.
- `program.globals` is `AstLet[]`.
- `program.unions` is `AstUnionDef[]`.

This pattern still applies to remaining homogeneous `AstNode[]` lists:

- `struct.fields` contains `AstStructField`.
- `match.fields` contains `AstMatchCase`.

Bad shape:

```epic
for i in program.funcs {
    match program.funcs[i] {
        AstFunDef f: {
            st.current_fn = f.name
            sema_block(st, f.body)
        }
        _: { sema_die("internal: expected function definition") }
    }
}
```

Better shape:

```epic
for i in program.funcs {
    let f = program.funcs[i]
    st.current_fn = f.name
    sema_block(st, f.body)
}
```

Once a container field has a concrete element type, downstream code should trust that type instead of re-matching every element.

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

- every union member has a direct embedded field with the same name;
- the field has the same MIR type in every member;
- the field has the same field index in every member;
- non-uniform, promoted, or partial cases fall back to the old dispatch.

This handles `node.AstMeta` in the AST ADT without special-casing `AstMeta` by name.

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

During the full parser AST ADT work, the compiler became much larger because common AST knowledge was lost. The worst generated code came from `ast_kind()` chains, `AstNode` helper parameters, homogeneous `AstNode[]` lists, and uniform embedded projections.

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
