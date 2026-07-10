"""MIR runtime helpers loaded from the committed runtime MIR bundle."""

from __future__ import annotations

from pathlib import Path

from mir import MirGlobal, MirProgram, ptr
from mir_parser import parse_mir_file


IMPLEMENTED_MIR_HELPERS = (
    "__ep_runtime_panic",
    "__ep_str_cat",
    "__ep_slice_u8_alloc",
    "__ep_slice_u8_get",
    "__ep_slice_u8_pop",
    "__ep_slice_i64_new",
    "__ep_slice_i64_get",
    "__ep_slice_i64_set",
    "__ep_slice_i64_push",
    "__ep_slice_i64_pop",
    "__ep_slice_i64_extend",
    "__ep_slice_ptr_new",
    "__ep_slice_ptr_get",
    "__ep_slice_ptr_set",
    "__ep_slice_ptr_push",
    "__ep_slice_ptr_pop",
    "__ep_slice_ptr_extend",
    "__ep_slice_u8_set",
    "__ep_slice_u8_push",
    "__ep_slice_u8_slice",
    "__ep_slice_u8_extend",
    "__ep_str_cmp",
    "__ep_map_str_find_pos",
    "__ep_map_str_len",
    "__ep_map_str_key_at",
    "__ep_map_str_i64_new",
    "__ep_map_str_i64_get",
    "__ep_map_str_i64_set",
    "__ep_map_str_i64_has",
    "__ep_map_str_i64_del",
    "__ep_map_str_bool_new",
    "__ep_map_str_bool_get",
    "__ep_map_str_bool_set",
    "__ep_map_str_bool_has",
    "__ep_map_str_bool_del",
    "__ep_map_str_str_new",
    "__ep_map_str_str_get",
    "__ep_map_str_str_set",
    "__ep_map_str_str_has",
    "__ep_map_str_str_del",
    "__ep_map_str_ptr_new",
    "__ep_map_str_ptr_get",
    "__ep_map_str_ptr_set",
    "__ep_map_str_ptr_has",
    "__ep_map_str_ptr_del",
    "__ep_debug_i64",
)


_RUNTIME_STRING_GLOBALS = (
    ("str.runtime.bool.true", "true"),
    ("str.runtime.bool.false", "false"),
    ("str.runtime.empty", ""),
    ("str.runtime.panic.prefix", "runtime panic: "),
    ("str.runtime.slice.oob", "slice index out of bounds"),
    ("str.runtime.map.missing", "map missing key"),
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
    helpers = {fn.name: fn for fn in parsed.functions}
    expected = set(IMPLEMENTED_MIR_HELPERS)
    missing = [name for name in IMPLEMENTED_MIR_HELPERS if name not in helpers]
    extra = sorted(name for name in helpers if name not in expected)
    if missing or extra:
        raise RuntimeError(f"MIR runtime helper bundle mismatch: missing={missing}, extra={extra}")

    _PARSED_RUNTIME_PROGRAM = parsed
    return parsed


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
