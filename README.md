# Epic

Epic is a small self-hosting systems language experiment targeting Windows x64.

This repository keeps each language generation as a directory on `main`:

- `v0/`: Python bootstrap compiler and the first fixed-point Epic compiler.
- `v1/`: v1 compiler sources, compiled by the v0 compiler anchor.
- `v2/`: reserved for sources compiled by the v1 compiler anchor; no distinct v2 feature work yet.

The repository root is not a language version. Version sources, examples,
runtime files, tests, and implementation notes live inside the version
directories.

## Root Layout

- `AGENTS.md`: repository-wide development rules.
- `README.md`: this overview.
- `worklog.md`: cross-version chronological project log.
- `epic-bootstrap.py`: top-level bootstrap chain.
- `tools/`: local shared Windows tool binaries such as `nasm.exe` and `lld-link.exe`.
- `tree-sitter-epic/`: shared editor/parser support.
- `v0/`, `v1/`, `v2/`: version source trees.

`tools/` and `build/` are local directories and are ignored by git.

## Bootstrap

Run the top-level bootstrap chain from the repository root:

```powershell
python epic-bootstrap.py
```

The script:

1. runs the v0 fixed-point bootstrap in `v0/`
2. copies the resulting compiler to `build/v0.exe`
3. uses `build/v0.exe` to compile the v1 compiler sources
4. copies that compiler to `build/v1.exe`

It intentionally does not build v2 yet. Current v2 has no new feature surface,
and v1 sources are still written in the v0-accepted source shape.

## Version Tests

Run version-specific tests inside the corresponding directory:

```powershell
cd v0
python runtests.py

cd ..\v1
python runtests.py
```

The root bootstrap script is a cross-version chain check, not a replacement for
each version's own tests.

## Development Rule

Do not preserve forward compatibility for its own sake. When the language
changes, compiler sources should move with the current design.
