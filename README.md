# Epic v3

Epic v3 starts from the sealed v2 compiler and dogfoods the language surface
implemented there: unary operators, compound assignment, integer range loops,
nominal unit enums, and exhaustive matching. It adds block tail values, implicit
function tail returns, expression-form `if` and `match`, and an internal `never`
type for no-return control flow, including allocation-free `panic(message)`.
v3 also implements distinct `bool` plus signed and unsigned 8-, 16-, 32-, and
64-bit integers, typed integer literals, explicit `T(value)` conversions, and
compact integer storage. The v3 compiler source remains on the previous
surface; v4 is the dogfood generation for these additions.
It also provides `is_null(reference)` for explicit zero-address tests without
inserting implicit dereference checks. Dynamic arrays are opaque and use
`len`, checked subscripting, `push`, `pop`, and `extend`; `str(byte_array)`
copies a mutable byte array into an immutable string.
It retains the self-contained AMD64 assembler,
deterministic PE writer, and conservative garbage collector.

The bootstrap chain is:

```text
Python v0 stage-0 -> Epic v1 -> Epic v2 -> Epic v3 -> Epic v3 fixed point
```

## Build

```powershell
python build_epic.py
```

The script resolves the current local `v2` branch to an exact commit. It reuses
`build/epic-v2-<hash>.exe` when present; otherwise it creates a detached v2
worktree and calls that generation's `build_epic.py`. The resulting v2 compiler
then compiles the current v3 working tree.

The default output is `build/epic-v3.exe`. Pass `-o PATH` to copy only the
final v3 executable elsewhere; relative paths are resolved from the calling
working directory.

## Documentation

- [Language reference](docs/language.md), including built-in data structures and functions
- [Compiler implementation](docs/implementation.md)
- [Garbage collector](docs/gc.md)

Verify the self-hosted fixed point:

```powershell
python bootstrap_fixed_point.py
```

The v2-built v3 seed compiles generation 1, then generation 1 compiles
generation 2. The check succeeds only when generations 1 and 2 are
byte-identical.

## Test

```powershell
python tests/run.py
```

`examples/` contains the small learning sequence. Broader regression coverage
lives under `tests/e2e/pass/`.
