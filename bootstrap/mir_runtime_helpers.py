"""MIR runtime helpers — MirFunction implementations for selected builtins.

Each helper is a hand-coded MirFunction that replaces an x64-backed runtime
helper.  They use existing MIR ops (call/gep/load/store/ret) and call existing
x64 primitives (notably __epic_alloc).  The lowering pipeline emits them
through the normal _lower_function path.
"""

from mir import (
    BOOL,
    I32,
    I64,
    I8,
    VOID,
    Br,
    CondBr,
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


# ── MirHelperBuilder ──────────────────────────────────────────────────────


class MirHelperBuilder:
    """Small builder that reduces MIR boilerplate when constructing helpers."""

    def __init__(self, name: str, params: list[MirParam], ret_type):
        self.fn = MirFunction(name, params, ret_type)
        self.entry = MirBlock("entry")
        self.fn.blocks.append(self.entry)
        self._value_counter = 0

    @staticmethod
    def _op(val):
        """Wrap a bare MirValue in ValueOperand if needed."""
        if isinstance(val, MirValue):
            return ValueOperand(val)
        return val

    @staticmethod
    def _ops(*args):
        """Wrap each arg that is a MirValue."""
        return [MirHelperBuilder._op(a) for a in args]

    def value(self, typ, hint="v"):
        """Create a new %vN value with the given type."""
        n = self._value_counter
        self._value_counter += 1
        return MirValue(f"%{hint}{n}", typ)

    def const_i64(self, n):
        return ConstIntOperand(I64, n)

    def const_i32(self, n):
        return ConstIntOperand(I32, n)

    def call(self, callee, args, ret_type):
        """Append a call and return the result value (or None if void)."""
        result = self.value(ret_type, "call") if ret_type != VOID else None
        inst = MirInst("call", self._ops(*args), result=result, type=ret_type, callee=callee)
        self.entry.instructions.append(inst)
        return result

    def gep(self, source_type, base, indices, result_type=None):
        """Append a gep and return the result ptr value."""
        if result_type is None:
            result_type = ptr()
        r = self.value(result_type, "gep")
        ops = self._ops(base) + self._ops(*indices)
        self.entry.instructions.append(MirInst("gep", ops, result=r, type=source_type))
        return r

    def load(self, access_type, addr, result_type=None):
        """Append a load and return the result value."""
        if result_type is None:
            result_type = access_type
        r = self.value(result_type, "load")
        self.entry.instructions.append(
            MirInst("load", self._ops(addr), result=r, type=access_type)
        )
        return r

    def store(self, value, addr):
        """Append a store.  No result."""
        self.entry.instructions.append(MirInst("store", self._ops(value, addr)))

    def icmp(self, cond, left, right):
        """Append an icmp.<cond> and return the bool result value."""
        r = self.value(BOOL, "cmp")
        self.entry.instructions.append(
            MirInst(f"icmp.{cond}", self._ops(left, right), result=r, type=BOOL)
        )
        return r

    def binop(self, op, left, right):
        """Append an integer binary op (add/sub/and/…)."""
        r = self.value(I64, "binop")
        self.entry.instructions.append(
            MirInst(op, self._ops(left, right), result=r, type=I64)
        )
        return r

    def alloca(self, elem_type):
        """Append an alloca and return the address."""
        r = self.value(ptr(elem_type), "slot")
        self.entry.instructions.append(MirInst("alloca", result=r, type=elem_type))
        return r

    def gep_field(self, base, struct_name, field_index, result_type=None):
        """Convenience: gep into a struct field by index (0/1/2)."""
        return self.gep(
            mir_struct(struct_name),
            self._op(base),
            [self.const_i64(0), self.const_i32(field_index)],
            result_type=result_type,
        )

    def new_block(self, prefix):
        block = MirBlock(prefix)
        self.fn.blocks.append(block)
        return block

    def br(self, target):
        """Set br terminator on the current working block (entry)."""
        self.entry.terminator = Br(target)
        # Switch builder to the target block for subsequent instructions
        self.entry = self.fn.blocks[-1]

    def ret(self, value=None):
        """Set ret terminator on entry.  Call this last."""
        if value is not None:
            self.entry.terminator = Ret(value)
        else:
            self.entry.terminator = Ret()


# ── Helper emitters ───────────────────────────────────────────────────────


def emit_bytes_str(program: MirProgram) -> MirFunction:
    """Build a MirFunction for bytes_str.

    Behaviour (matching the old _emit_bytes_str x64 helper):
        fn bytes_str(%s: ptr<str>) -> ptr<_arr_i8> {
        entry:
            %raw = call ptr __epic_alloc(i64 24)
            ; copy str.{data,len} → _arr_i8.{data,len,cap}
        }
    """
    b = MirHelperBuilder(
        "bytes_str",
        [MirParam("%s", ptr(mir_struct("str")))],
        ptr(mir_struct("_arr_i8")),
    )

    raw = b.call("__epic_alloc", [b.const_i64(24)], ptr())
    s_val = ValueOperand(b.fn.params[0].value)

    # Load str.data
    s_data_addr = b.gep_field(s_val, "str", 0)
    s_data = b.load(ptr(), s_data_addr)

    # Load str.len
    s_len_addr = b.gep_field(s_val, "str", 1)
    s_len = b.load(I64, s_len_addr)

    # Write _arr_i8 fields
    b.store(s_data, b.gep_field(ValueOperand(raw), "_arr_i8", 0))
    b.store(s_len, b.gep_field(ValueOperand(raw), "_arr_i8", 1))
    b.store(s_len, b.gep_field(ValueOperand(raw), "_arr_i8", 2))

    b.ret(ValueOperand(raw))
    return b.fn


def emit_str_arr_i8() -> MirFunction:
    """Identity: returns the input ptr<_arr_i8> as ptr<str>.

    x64: mov rax, rcx; ret
    """
    b = MirHelperBuilder(
        "str_arr_i8",
        [MirParam("%input", ptr(mir_struct("_arr_i8")))],
        ptr(mir_struct("str")),
    )
    b.ret(ValueOperand(b.fn.params[0].value))
    return b.fn


def emit_new_arr_i8() -> MirFunction:
    """Allocate header + data for a new u8[] of length n.

    fn new_arr_i8(i64 %n) -> ptr<_arr_i8>
    """
    b = MirHelperBuilder(
        "new_arr_i8",
        [MirParam("%n", I64)],
        ptr(mir_struct("_arr_i8")),
    )
    n_val = ValueOperand(b.fn.params[0].value)

    header_raw = b.call("__epic_alloc", [b.const_i64(24)], ptr())
    data_raw = b.call("__epic_alloc", [n_val], ptr())

    # header.data = data
    b.store(data_raw, b.gep_field(ValueOperand(header_raw), "_arr_i8", 0))
    # header.len = n
    b.store(n_val, b.gep_field(ValueOperand(header_raw), "_arr_i8", 1))
    # header.cap = n
    b.store(n_val, b.gep_field(ValueOperand(header_raw), "_arr_i8", 2))

    b.ret(ValueOperand(header_raw))
    return b.fn


def emit_new_arr_i8_empty() -> MirFunction:
    """Allocate header + data, len=0, cap=n.

    fn new_arr_i8_empty(i64 %n) -> ptr<_arr_i8>
    """
    b = MirHelperBuilder(
        "new_arr_i8_empty",
        [MirParam("%n", I64)],
        ptr(mir_struct("_arr_i8")),
    )
    n_val = ValueOperand(b.fn.params[0].value)

    header_raw = b.call("__epic_alloc", [b.const_i64(24)], ptr())
    data_raw = b.call("__epic_alloc", [n_val], ptr())

    # header.data = data
    b.store(data_raw, b.gep_field(ValueOperand(header_raw), "_arr_i8", 0))
    # header.len = 0
    b.store(b.const_i64(0), b.gep_field(ValueOperand(header_raw), "_arr_i8", 1))
    # header.cap = n
    b.store(n_val, b.gep_field(ValueOperand(header_raw), "_arr_i8", 2))

    b.ret(ValueOperand(header_raw))
    return b.fn


def emit_arr_i8_get() -> MirFunction:
    """Bounds-checked byte read from u8[].

    fn arr_i8_get(ptr<_arr_i8> %arr, i64 %idx) -> i64
    """
    b = MirHelperBuilder(
        "arr_i8_get",
        [MirParam("%arr", ptr(mir_struct("_arr_i8"))), MirParam("%idx", I64)],
        I64,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)

    # Load arr.len
    len_addr = b.gep_field(arr_val, "_arr_i8", 1)
    arr_len = b.load(I64, len_addr)

    # Check idx >= 0
    ge_zero = b.icmp("ge", idx_val, b.const_i64(0))
    check_block = b.new_block("check_high")
    ok_block = b.new_block("ok")
    fail_block = b.new_block("fail")
    b.entry.terminator = CondBr(ValueOperand(ge_zero), check_block.name, fail_block.name)

    # check_high: idx < arr.len
    b.entry = check_block
    lt_len = b.icmp("lt", idx_val, arr_len)
    b.entry.terminator = CondBr(ValueOperand(lt_len), ok_block.name, fail_block.name)

    # ok: load byte
    b.entry = ok_block
    data_addr = b.gep_field(arr_val, "_arr_i8", 0)
    data = b.load(ptr(), data_addr)
    byte_addr = b.gep(I8, data, [idx_val])
    result = b.load(I8, byte_addr, result_type=I64)
    b.ret(ValueOperand(result))

    # fail: exit(1)
    b.entry = fail_block
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret(b.const_i64(0))  # dummy, unreachable

    return b.fn


def emit_arr_i8_set() -> MirFunction:
    """Bounds-checked byte write to u8[].

    fn arr_i8_set(ptr<_arr_i8> %arr, i64 %idx, i64 %val) -> void
    """
    b = MirHelperBuilder(
        "arr_i8_set",
        [
            MirParam("%arr", ptr(mir_struct("_arr_i8"))),
            MirParam("%idx", I64),
            MirParam("%val", I64),
        ],
        VOID,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)
    val_val = ValueOperand(b.fn.params[2].value)

    # Load arr.len
    len_addr = b.gep_field(arr_val, "_arr_i8", 1)
    arr_len = b.load(I64, len_addr)

    # Check idx >= 0
    ge_zero = b.icmp("ge", idx_val, b.const_i64(0))
    check_block = b.new_block("check_high")
    ok_block = b.new_block("ok")
    fail_block = b.new_block("fail")
    b.entry.terminator = CondBr(ValueOperand(ge_zero), check_block.name, fail_block.name)

    # check_high: idx < arr.len
    b.entry = check_block
    lt_len = b.icmp("lt", idx_val, arr_len)
    b.entry.terminator = CondBr(ValueOperand(lt_len), ok_block.name, fail_block.name)

    # ok: store byte (truncate i64 to i8 via alloca roundtrip)
    b.entry = ok_block
    trunc_slot = b.alloca(I64)
    b.store(val_val, ValueOperand(trunc_slot))
    byte_val = b.load(I8, ValueOperand(trunc_slot), result_type=I8)

    data_addr = b.gep_field(arr_val, "_arr_i8", 0)
    data = b.load(ptr(), data_addr)
    byte_addr = b.gep(I8, data, [idx_val])
    b.store(ValueOperand(byte_val), byte_addr)
    b.ret()

    # fail: exit(1)
    b.entry = fail_block
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret()  # dummy, unreachable

    return b.fn


# ── Injection ─────────────────────────────────────────────────────────────


_HELPER_EMITTERS = {
    "bytes_str": emit_bytes_str,
    "str_arr_i8": lambda p: emit_str_arr_i8(),
    "new_arr_i8": lambda p: emit_new_arr_i8(),
    "new_arr_i8_empty": lambda p: emit_new_arr_i8_empty(),
    "arr_i8_get": lambda p: emit_arr_i8_get(),
    "arr_i8_set": lambda p: emit_arr_i8_set(),
}


def inject_required_mir_helpers(program: MirProgram, helper_names: set[str]) -> None:
    """Inject MirFunction implementations for the given helper names.

    For each name in *helper_names*:
      1. Remove any matching MirExtern from *program.externs* so the
         validator does not see a duplicate symbol.
      2. Build the MirFunction and append it to *program.functions*.
    """
    if not helper_names:
        return

    # Remove any matching externs in one pass
    program.externs[:] = [e for e in program.externs if e.name not in helper_names]

    for name in helper_names:
        emitter = _HELPER_EMITTERS.get(name)
        if emitter is not None:
            program.functions.append(emitter(program))
