# Epic implementation notes

The current implementation is split between a Python reference compiler and the
self-hosted Epic compiler.

## Python Reference Compiler

`bootstrap/` contains the Python implementation:

```text
bootstrap/epic.py
bootstrap/lexer.py
bootstrap/parser.py
bootstrap/ast_nodes.py
bootstrap/codegen.py
```

The driver reads sources from the repository root, writes build output under
`build/`, appends runtime helpers from `runtime/`, assembles with
`tools/nasm.exe`, and links with either root `link.py` or `tools/lld-link.exe`.

## Epic Compiler

`src/` contains the self-hosted compiler:

```text
src/epic.ep
src/lexer.ep
src/parser.ep
src/codegen_support.ep
src/codegen.ep
```

`src/link.ep` is the Epic linker implementation. It is current Epic production
code, but it is not part of the compiler fixed-point source set.

## Acceptance

The core acceptance checks are:

```powershell
python runtests.py --linker py
python test_bootstrap_fixed_point.py
```

`runtests.py` checks the Python reference compiler against annotated examples.
`test_bootstrap_fixed_point.py` checks that the Python compiler can build the
Epic compiler and that repeated Epic-built compilers are byte-identical.

## Brace Disambiguation — Implementation Notes

The parser does not classify `{ ... }` by identifier spelling. A postfix
`{ ... }` in expression or pattern position is always parsed as an
initializer or pattern-payload candidate; the semantic pass and codegen are
responsible for rejecting invalid uses.

Match cases use mandatory colon syntax (`pattern: body`). The parser
should enforce this at the syntax level: after parsing the pattern, expect
a colon token before the case body. This is a flat grammar rule with no
look-ahead ambiguity.

### Struct Init Syntax

`StructName {}` is the preferred syntax for zero/default struct
initialization. `new StructName` is deprecated and will be removed.
`new T[n]` and `new map[str]T` remain valid for now.

## Acceptance

When changing parser or AST code related to braces or match cases, verify:

1. All examples in `v2/examples/` parse without error.
2. No match case uses the old double-brace form.
3. Every match case has a colon between pattern and body.
4. Tests that depend on uppercase-name heuristics for init detection are
   updated to rely on grammar position only.
