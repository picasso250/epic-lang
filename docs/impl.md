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
