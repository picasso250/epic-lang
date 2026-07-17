# Epic v0 Python stage-0

This branch contains the frozen Python reference compiler for the smallest Epic language used to bootstrap v1. It is deliberately not self-hosted and contains no Epic compiler implementation.

Compile and run the acceptance suite on Windows x64:

```powershell
python runtests.py --linker py
```

Compile one program:

```powershell
python epic.py examples/00_hello_world.ep
```

Product types use `type Name { ... }`. The `struct` keyword and sum declarations are not part of v0.

## Documentation

- [Language reference](docs/language.md), including built-in data structures and functions
- [Implementation notes](docs/implementation.md)

`examples/` contains five small, ordered learning programs. Broader regression coverage lives under `tests/e2e/pass/`; `runtests.py` combines both suites into one executable and selects each case at process startup.

The intended bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v1 fixed point
```

The historical Epic v0 self-hosted compiler remains available in Git history; it is not a maintained implementation on this branch.
