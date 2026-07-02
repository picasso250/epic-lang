"""MIR runtime helpers — MirFunction implementations for selected builtins.

Each helper is a hand-coded MirFunction that replaces an x64-backed runtime
helper.  They use existing MIR ops (call/gep/load/store/ret) and call existing
x64 primitives (notably __epic_alloc).  The lowering pipeline emits them
through the normal _lower_function path.
"""

from mir import (
    I32,
    I64,
    VOID,
    ConstIntOperand,
    MirBlock,
    MirExtern,
    MirFunction,
    MirInst,
    MirParam,
    MirProgram,
    MirSignature,
    MirValue,
    Ret,
    ValueOperand,
    ptr,
    struct as mir_struct,
)


def emit_bytes_str(program: MirProgram) -> MirFunction:
    """Build a MirFunction for bytes_str.

    Behaviour (matching the old _emit_bytes_str x64 helper):
        fn bytes_str(%s: ptr<str>) -> ptr<_arr_i8> {
        entry:
            %raw = call ptr __epic_alloc(i64 24)

            %s.data.addr = gep struct str, ptr %s, i64 0, i32 0
            %s.data      = load ptr, ptr %s.data.addr

            %s.len.addr  = gep struct str, ptr %s, i64 0, i32 1
            %s.len       = load i64, ptr %s.len.addr

            %arr.data.addr = gep struct _arr_i8, ptr %raw, i64 0, i32 0
            store ptr %s.data, ptr %arr.data.addr

            %arr.len.addr = gep struct _arr_i8, ptr %raw, i64 0, i32 1
            store i64 %s.len, ptr %arr.len.addr

            %arr.cap.addr = gep struct _arr_i8, ptr %raw, i64 0, i32 2
            store i64 %s.len, ptr %arr.cap.addr

            ret ptr<_arr_i8> %raw
        }
    """
    fn = MirFunction(
        "bytes_str",
        [MirParam("%s", ptr(mir_struct("str")))],
        ptr(mir_struct("_arr_i8")),
    )

    entry = MirBlock("entry")
    fn.blocks.append(entry)

    def _inst(op, operands, result_type=None, type=None, callee=None):
        """Small local helper to build MirInst and append to entry."""
        result = MirValue(f"%v{len(entry.instructions)}", result_type) if result_type is not None else None
        inst = MirInst(op, operands, result=result, type=type, callee=callee)
        entry.instructions.append(inst)
        return result

    # %raw = call ptr __epic_alloc(i64 24)
    raw = _inst("call", [ConstIntOperand(I64, 24)], result_type=ptr(), type=ptr(), callee="__epic_alloc")

    # --- Load s.data ---
    s_data_addr = _inst(
        "gep",
        [ValueOperand(fn.params[0].value), ConstIntOperand(I64, 0), ConstIntOperand(I32, 0)],
        result_type=ptr(),
        type=mir_struct("str"),
    )
    s_data = _inst("load", [ValueOperand(s_data_addr)], result_type=ptr(), type=ptr())

    # --- Load s.len ---
    s_len_addr = _inst(
        "gep",
        [ValueOperand(fn.params[0].value), ConstIntOperand(I64, 0), ConstIntOperand(I32, 1)],
        result_type=ptr(),
        type=mir_struct("str"),
    )
    s_len = _inst("load", [ValueOperand(s_len_addr)], result_type=I64, type=I64)

    # --- Store arr.data = s.data ---
    arr_data_addr = _inst(
        "gep",
        [ValueOperand(raw), ConstIntOperand(I64, 0), ConstIntOperand(I32, 0)],
        result_type=ptr(),
        type=mir_struct("_arr_i8"),
    )
    _inst("store", [ValueOperand(s_data), ValueOperand(arr_data_addr)])

    # --- Store arr.len = s.len ---
    arr_len_addr = _inst(
        "gep",
        [ValueOperand(raw), ConstIntOperand(I64, 0), ConstIntOperand(I32, 1)],
        result_type=ptr(),
        type=mir_struct("_arr_i8"),
    )
    _inst("store", [ValueOperand(s_len), ValueOperand(arr_len_addr)])

    # --- Store arr.cap = s.len ---
    arr_cap_addr = _inst(
        "gep",
        [ValueOperand(raw), ConstIntOperand(I64, 0), ConstIntOperand(I32, 2)],
        result_type=ptr(),
        type=mir_struct("_arr_i8"),
    )
    _inst("store", [ValueOperand(s_len), ValueOperand(arr_cap_addr)])

    # ret ptr<_arr_i8> %raw
    entry.terminator = Ret(ValueOperand(raw))

    return fn


def inject_required_mir_helpers(program: MirProgram, helper_names: set[str]) -> None:
    """Inject MirFunction implementations for the given helper names.

    For each name in *helper_names*:
      1. Remove any matching MirExtern from *program.externs* so the
         validator does not see a duplicate symbol.
      2. Build the MirFunction and append it to *program.functions*.
    """
    if "bytes_str" in helper_names:
        # Remove the old extern so validate() doesn't choke on duplicate symbol.
        program.externs[:] = [e for e in program.externs if e.name != "bytes_str"]
        program.functions.append(emit_bytes_str(program))
