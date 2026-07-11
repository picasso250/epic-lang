"""MIR runtime loading and target-neutral preparation."""

from __future__ import annotations

from pathlib import Path

from mir import (
    VOID,
    ConstNullOperand,
    MirInst,
    MirProgram,
    SymbolOperand,
    ValueOperand,
)
from mir_parser import parse_mir_file


_RUNTIME_MIR_BUNDLE = Path(__file__).resolve().parent.parent / "runtime" / "mir" / "helpers.mir"


def _parsed_runtime_program():
    if not _RUNTIME_MIR_BUNDLE.exists():
        raise RuntimeError(f"missing MIR runtime helper bundle: {_RUNTIME_MIR_BUNDLE}")
    # Preparation mutates function instruction lists, so every compilation gets
    # a fresh parse rather than sharing cached runtime DTOs.
    return parse_mir_file(_RUNTIME_MIR_BUNDLE, validate_program=False)


def runtime_mir_helper_names() -> tuple[str, ...]:
    """Return helper names in canonical bundle order."""
    return tuple(fn.name for fn in _parsed_runtime_program().functions)


def _insert_runtime_start(program: MirProgram) -> None:
    main = next((fn for fn in program.functions if fn.name == "main"), None)
    if main is None or not main.blocks:
        return
    entry = main.blocks[0]
    if entry.instructions and entry.instructions[0].op == "call" and entry.instructions[0].callee == "__ep_runtime_start":
        return
    entry.instructions.insert(0, MirInst("call", [], type=VOID, callee="__ep_runtime_start"))


def _dynamic_address_needs_check(operand, safe_ids: set[int], checked_ids: set[int]) -> bool:
    if isinstance(operand, SymbolOperand):
        return False
    if isinstance(operand, ValueOperand):
        value_id = operand.value.id
        return value_id not in safe_ids and value_id not in checked_ids
    return not isinstance(operand, ConstNullOperand)


def _insert_explicit_null_checks(program: MirProgram) -> None:
    """Make null-dereference behavior explicit in MIR before x64 lowering."""

    for fn in program.functions:
        safe_ids = {
            inst.result.id
            for block in fn.blocks
            for inst in block.instructions
            if inst.op == "alloca" and inst.result is not None
        }
        safe_ids.update(
            inst.result.id
            for block in fn.blocks
            for inst in block.instructions
            if inst.op == "gep"
            and inst.result is not None
            and inst.operands
            and not isinstance(inst.operands[0], ConstNullOperand)
        )

        for block in fn.blocks:
            checked_ids: set[int] = set()
            rewritten = []
            for inst in block.instructions:
                address = None
                if inst.op == "gep" and inst.operands and not isinstance(inst.operands[0], ConstNullOperand):
                    address = inst.operands[0]
                elif inst.op == "load" and inst.operands:
                    address = inst.operands[0]
                elif inst.op == "store" and len(inst.operands) == 2:
                    address = inst.operands[1]

                if address is not None and _dynamic_address_needs_check(address, safe_ids, checked_ids):
                    rewritten.append(MirInst("call", [address], type=VOID, callee="__ep_require_nonnull"))
                    if isinstance(address, ValueOperand):
                        checked_ids.add(address.value.id)
                rewritten.append(inst)
            block.instructions[:] = rewritten


def inject_all_mir_helpers(program: MirProgram) -> None:
    """Inject runtime definitions, globals, startup, and explicit safety checks."""

    runtime = _parsed_runtime_program()
    existing_functions = {fn.name for fn in program.functions}
    for fn in runtime.functions:
        if fn.name not in existing_functions:
            program.functions.append(fn)
            existing_functions.add(fn.name)

    program.externs[:] = [ext for ext in program.externs if ext.name not in existing_functions]

    declared = {item.name for item in program.externs}
    for ext in runtime.externs:
        if ext.name not in existing_functions and ext.name not in declared:
            program.externs.append(ext)
            declared.add(ext.name)

    global_names = {glob.name for glob in program.globals}
    for glob in runtime.globals:
        if glob.name not in global_names:
            program.globals.append(glob)
            global_names.add(glob.name)

    _insert_runtime_start(program)
    _insert_explicit_null_checks(program)
