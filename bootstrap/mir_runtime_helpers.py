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
_PARSED_HELPERS = None


def _parsed_runtime_helpers():
    global _PARSED_HELPERS
    if _PARSED_HELPERS is not None:
        return _PARSED_HELPERS
    if not _RUNTIME_MIR_BUNDLE.exists():
        raise RuntimeError(f"missing MIR runtime helper bundle: {_RUNTIME_MIR_BUNDLE}")

    helpers = {}
    parsed = parse_mir_file(_RUNTIME_MIR_BUNDLE, validate_program=False)
    for fn in parsed.functions:
        if fn.name in helpers:
            raise RuntimeError(f"duplicate parsed MIR helper: {fn.name}")
        helpers[fn.name] = fn

    expected = set(IMPLEMENTED_MIR_HELPERS)
    missing = [name for name in IMPLEMENTED_MIR_HELPERS if name not in helpers]
    extra = sorted(name for name in helpers if name not in expected)
    if missing or extra:
        raise RuntimeError(f"MIR runtime helper bundle mismatch: missing={missing}, extra={extra}")

    _PARSED_HELPERS = helpers
    return helpers


def inject_all_mir_helpers(program: MirProgram) -> None:
    """Inject every implemented MIR helper in deterministic order."""
    implemented = set(IMPLEMENTED_MIR_HELPERS)

    # Remove matching externs so validate() doesn't see duplicate symbols.
    program.externs[:] = [e for e in program.externs if e.name not in implemented]

    global_names = {g.name for g in program.globals}
    for name, text in _RUNTIME_STRING_GLOBALS:
        if name not in global_names:
            program.globals.append(MirGlobal(name, ptr(), text))
            global_names.add(name)

    parsed_helpers = _parsed_runtime_helpers()
    for name in IMPLEMENTED_MIR_HELPERS:
        program.functions.append(parsed_helpers[name])
