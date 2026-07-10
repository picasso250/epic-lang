"""MIR runtime helpers loaded from the committed runtime MIR bundle."""

from __future__ import annotations

from pathlib import Path

from mir import MirGlobal, MirProgram, ptr
from mir_parser import parse_mir_file



_RUNTIME_STRING_GLOBALS = (
    ("str.runtime.bool.true", "true"),
    ("str.runtime.bool.false", "false"),
    ("str.runtime.empty", ""),
    ("str.runtime.panic.prefix", "runtime panic: "),
    ("str.runtime.slice.oob", "slice index out of bounds"),
)


_RUNTIME_MIR_BUNDLE = Path(__file__).resolve().parent.parent / "runtime" / "mir" / "helpers.mir"
_PARSED_RUNTIME_PROGRAM = None


def _parsed_runtime_program():
    global _PARSED_RUNTIME_PROGRAM
    if _PARSED_RUNTIME_PROGRAM is not None:
        return _PARSED_RUNTIME_PROGRAM
    if not _RUNTIME_MIR_BUNDLE.exists():
        raise RuntimeError(f"missing MIR runtime helper bundle: {_RUNTIME_MIR_BUNDLE}")

    parsed = parse_mir_file(_RUNTIME_MIR_BUNDLE, validate_program=False)
    _PARSED_RUNTIME_PROGRAM = parsed
    return parsed


def runtime_mir_helper_names() -> tuple[str, ...]:
    """Return helper names in the canonical bundle order."""
    return tuple(fn.name for fn in _parsed_runtime_program().functions)


def inject_all_mir_helpers(program: MirProgram) -> None:
    """Inject the runtime MIR module exactly once."""

    runtime = _parsed_runtime_program()
    existing_functions = {fn.name for fn in program.functions}
    for fn in runtime.functions:
        if fn.name not in existing_functions:
            program.functions.append(fn)
            existing_functions.add(fn.name)

    # A definition replaces the source-stage extern declaration.
    program.externs[:] = [ext for ext in program.externs if ext.name not in existing_functions]

    declared = {item.name for item in program.externs}
    for ext in runtime.externs:
        if ext.name not in existing_functions and ext.name not in declared:
            program.externs.append(ext)
            declared.add(ext.name)

    global_names = {g.name for g in program.globals}
    for name, text in _RUNTIME_STRING_GLOBALS:
        if name not in global_names:
            program.globals.append(MirGlobal(name, ptr(), text))
            global_names.add(name)
