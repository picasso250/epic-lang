"""MIR runtime helpers — MirFunction implementations for selected builtins.

Each helper is a hand-coded MirFunction that replaces an x64-backed runtime
helper.  They use existing MIR ops (call/gep/load/store/ret) and call existing
x64 primitives (notably __epic_alloc).  The codegen pipeline injects all
implemented helpers, and the lowering pipeline emits them through the normal
_lower_function path.
"""

from mir import (
    BOOL,
    I32,
    I64,
    I8,
    VOID,
    Br,
    CondBr,
    ConstBoolOperand,
    ConstIntOperand,
    ConstNullOperand,
    MirBlock,
    MirFunction,
    MirInst,
    MirParam,
    MirProgram,
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

    def ret(self, value=None):
        """Set ret terminator on entry.  Call this last."""
        if value is not None:
            self.entry.terminator = Ret(value)
        else:
            self.entry.terminator = Ret()

    def br(self, target):
        self.entry.terminator = Br(target.name if isinstance(target, MirBlock) else target)


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


def emit_str_eq() -> MirFunction:
    """Compare two strings for byte-for-byte equality.

    fn str_eq(ptr<str> %left, ptr<str> %right) -> bool
    """
    b = MirHelperBuilder(
        "str_eq",
        [
            MirParam("%left", ptr(mir_struct("str"))),
            MirParam("%right", ptr(mir_struct("str"))),
        ],
        BOOL,
    )
    left_val = ValueOperand(b.fn.params[0].value)
    right_val = ValueOperand(b.fn.params[1].value)

    left_len = b.load(I64, b.gep_field(left_val, "str", 1))
    right_len = b.load(I64, b.gep_field(right_val, "str", 1))
    same_len = b.icmp("eq", left_len, right_len)
    loop_init = b.new_block("loop_init")
    false_block = b.new_block("false")
    b.entry.terminator = CondBr(ValueOperand(same_len), loop_init.name, false_block.name)

    b.entry = loop_init
    left_data = b.load(ptr(), b.gep_field(left_val, "str", 0))
    right_data = b.load(ptr(), b.gep_field(right_val, "str", 0))
    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    loop_check = b.new_block("loop_check")
    b.br(loop_check)

    b.entry = loop_check
    i = b.load(I64, ValueOperand(i_slot))
    keep_checking = b.icmp("lt", i, left_len)
    loop_body = b.new_block("loop_body")
    true_block = b.new_block("true")
    b.entry.terminator = CondBr(ValueOperand(keep_checking), loop_body.name, true_block.name)

    b.entry = loop_body
    left_byte_addr = b.gep(I8, left_data, [i])
    left_byte = b.load(I8, left_byte_addr, result_type=I8)
    right_byte_addr = b.gep(I8, right_data, [i])
    right_byte = b.load(I8, right_byte_addr, result_type=I8)
    bytes_eq = b.icmp("eq", left_byte, right_byte)
    loop_next = b.new_block("loop_next")
    b.entry.terminator = CondBr(ValueOperand(bytes_eq), loop_next.name, false_block.name)

    b.entry = loop_next
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(loop_check)

    b.entry = true_block
    b.ret(ConstBoolOperand(True))

    b.entry = false_block
    b.ret(ConstBoolOperand(False))

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


def emit_arr_i8_push() -> MirFunction:
    """Push a byte value onto a u8[] array.

    fn arr_i8_push(ptr<_arr_i8> %arr, i64 %val) -> void

    Grows by doubling capacity when full, using __epic_alloc for new
    backing storage.  Matches the old _emit_arr_i8_push x64 behaviour.
    """
    b = MirHelperBuilder(
        "arr_i8_push",
        [
            MirParam("%arr", ptr(mir_struct("_arr_i8"))),
            MirParam("%val", I64),
        ],
        VOID,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    val_val = ValueOperand(b.fn.params[1].value)

    # Load old_len (field 1) and old_cap (field 2)
    len_addr = b.gep_field(arr_val, "_arr_i8", 1)
    old_len = b.load(I64, len_addr)
    cap_addr = b.gep_field(arr_val, "_arr_i8", 2)
    old_cap = b.load(I64, cap_addr)

    # Check if grow needed
    need_grow = b.icmp("ge", old_len, old_cap)
    grow_block = b.new_block("grow")
    store_block = b.new_block("store")
    b.entry.terminator = CondBr(ValueOperand(need_grow), grow_block.name, store_block.name)

    # grow: allocate slots for grow results, dispatch zero vs double
    b.entry = grow_block
    new_cap_slot = b.alloca(I64)
    new_data_slot = b.alloca(ptr())
    i_slot = b.alloca(I64)

    cap_zero = b.icmp("eq", old_cap, b.const_i64(0))
    zero_block = b.new_block("grow_zero")
    double_block = b.new_block("grow_double")
    b.entry.terminator = CondBr(ValueOperand(cap_zero), zero_block.name, double_block.name)

    # grow_zero: new_cap = 2
    b.entry = zero_block
    nc0 = b.const_i64(2)
    b.store(nc0, ValueOperand(new_cap_slot))
    nd0 = b.call("__epic_alloc", [nc0], ptr())
    b.store(nd0, ValueOperand(new_data_slot))
    copy_entry = b.new_block("copy_entry")
    b.entry.terminator = CondBr(ValueOperand(cap_zero), copy_entry.name, copy_entry.name)

    # grow_double: new_cap = old_cap * 2
    b.entry = double_block
    nc1 = b.binop("add", old_cap, old_cap)
    b.store(nc1, ValueOperand(new_cap_slot))
    nd1 = b.call("__epic_alloc", [nc1], ptr())
    b.store(nd1, ValueOperand(new_data_slot))
    b.entry.terminator = CondBr(ValueOperand(cap_zero), copy_entry.name, copy_entry.name)

    # copy_entry: load data pointer, init copy loop
    b.entry = copy_entry
    old_data = b.load(ptr(), b.gep_field(arr_val, "_arr_i8", 0))
    new_data = b.load(ptr(), ValueOperand(new_data_slot))
    b.store(b.const_i64(0), ValueOperand(i_slot))
    copy_check = b.new_block("copy_check")
    b.entry.terminator = CondBr(ValueOperand(cap_zero), copy_check.name, copy_check.name)

    # copy_check: loop condition i < old_len
    b.entry = copy_check
    i = b.load(I64, ValueOperand(i_slot))
    cond = b.icmp("lt", i, old_len)
    copy_body = b.new_block("copy_body")
    swap_block = b.new_block("swap")
    b.entry.terminator = CondBr(ValueOperand(cond), copy_body.name, swap_block.name)

    # copy_body: copy one byte
    b.entry = copy_body
    old_byte_addr = b.gep(I8, old_data, [i])
    old_byte = b.load(I8, old_byte_addr, result_type=I8)
    new_byte_addr = b.gep(I8, new_data, [i])
    b.store(ValueOperand(old_byte), new_byte_addr)
    i_next = b.binop("add", i, b.const_i64(1))
    b.store(i_next, ValueOperand(i_slot))
    b.entry.terminator = CondBr(ValueOperand(cap_zero), copy_check.name, copy_check.name)

    # swap: update arr.data and arr.cap
    b.entry = swap_block
    b.store(new_data, b.gep_field(arr_val, "_arr_i8", 0))
    final_cap = b.load(I64, ValueOperand(new_cap_slot))
    b.store(final_cap, b.gep_field(arr_val, "_arr_i8", 2))
    b.entry.terminator = CondBr(ValueOperand(cap_zero), store_block.name, store_block.name)

    # store: write byte and update len
    b.entry = store_block
    trunc_slot = b.alloca(I64)
    b.store(val_val, ValueOperand(trunc_slot))
    byte_val = b.load(I8, ValueOperand(trunc_slot), result_type=I8)
    data = b.load(ptr(), b.gep_field(arr_val, "_arr_i8", 0))
    byte_addr = b.gep(I8, data, [old_len])
    b.store(ValueOperand(byte_val), byte_addr)
    new_len = b.binop("add", old_len, b.const_i64(1))
    b.store(new_len, b.gep_field(arr_val, "_arr_i8", 1))
    b.ret()

    return b.fn


def emit_arr_i8_slice() -> MirFunction:
    """Copy a half-open u8[] slice [start:end].

    fn arr_i8_slice(ptr<_arr_i8> %arr, i64 %start, i64 %end) -> ptr<_arr_i8>

    Bounds failures exit with code 1, matching the old x64 helper.
    """
    b = MirHelperBuilder(
        "arr_i8_slice",
        [
            MirParam("%arr", ptr(mir_struct("_arr_i8"))),
            MirParam("%start", I64),
            MirParam("%end", I64),
        ],
        ptr(mir_struct("_arr_i8")),
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    start_val = ValueOperand(b.fn.params[1].value)
    end_val = ValueOperand(b.fn.params[2].value)

    arr_len = b.load(I64, b.gep_field(arr_val, "_arr_i8", 1))

    start_ok = b.icmp("ge", start_val, b.const_i64(0))
    check_order = b.new_block("check_order")
    check_len = b.new_block("check_len")
    alloc_block = b.new_block("alloc")
    copy_check = b.new_block("copy_check")
    copy_body = b.new_block("copy_body")
    done_block = b.new_block("done")
    fail_block = b.new_block("fail")
    b.entry.terminator = CondBr(ValueOperand(start_ok), check_order.name, fail_block.name)

    b.entry = check_order
    order_ok = b.icmp("ge", end_val, start_val)
    b.entry.terminator = CondBr(ValueOperand(order_ok), check_len.name, fail_block.name)

    b.entry = check_len
    len_ok = b.icmp("ge", arr_len, end_val)
    b.entry.terminator = CondBr(ValueOperand(len_ok), alloc_block.name, fail_block.name)

    b.entry = alloc_block
    slice_len = b.binop("sub", end_val, start_val)
    result_arr = b.call("new_arr_i8", [slice_len], ptr(mir_struct("_arr_i8")))
    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    src_data = b.load(ptr(), b.gep_field(arr_val, "_arr_i8", 0))
    src_start = b.gep(I8, src_data, [start_val])
    dst_data = b.load(ptr(), b.gep_field(ValueOperand(result_arr), "_arr_i8", 0))
    b.br(copy_check)

    b.entry = copy_check
    i = b.load(I64, ValueOperand(i_slot))
    keep_copying = b.icmp("lt", i, slice_len)
    b.entry.terminator = CondBr(ValueOperand(keep_copying), copy_body.name, done_block.name)

    b.entry = copy_body
    src_byte_addr = b.gep(I8, src_start, [i])
    byte = b.load(I8, src_byte_addr, result_type=I8)
    dst_byte_addr = b.gep(I8, dst_data, [i])
    b.store(ValueOperand(byte), dst_byte_addr)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(copy_check)

    b.entry = done_block
    b.ret(ValueOperand(result_arr))

    b.entry = fail_block
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret(ConstNullOperand())

    return b.fn


def emit_extend_i8() -> MirFunction:
    """Append src bytes into dst, snapshotting src.len before the loop.

    fn extend_i8(ptr<_arr_i8> %dst, ptr<_arr_i8> %src) -> void
    """
    b = MirHelperBuilder(
        "extend_i8",
        [
            MirParam("%dst", ptr(mir_struct("_arr_i8"))),
            MirParam("%src", ptr(mir_struct("_arr_i8"))),
        ],
        VOID,
    )
    dst_val = ValueOperand(b.fn.params[0].value)
    src_val = ValueOperand(b.fn.params[1].value)

    src_len = b.load(I64, b.gep_field(src_val, "_arr_i8", 1))
    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    loop_check = b.new_block("loop_check")
    loop_body = b.new_block("loop_body")
    done = b.new_block("done")
    b.br(loop_check)

    b.entry = loop_check
    i = b.load(I64, ValueOperand(i_slot))
    keep_copying = b.icmp("lt", i, src_len)
    b.entry.terminator = CondBr(ValueOperand(keep_copying), loop_body.name, done.name)

    b.entry = loop_body
    byte = b.call("arr_i8_get", [src_val, i], I64)
    b.call("arr_i8_push", [dst_val, ValueOperand(byte)], VOID)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(loop_check)

    b.entry = done
    b.ret()

    return b.fn


# ── Injection ─────────────────────────────────────────────────────────────


_HELPER_EMITTERS = {
    "bytes_str": emit_bytes_str,
    "str_arr_i8": lambda p: emit_str_arr_i8(),
    "str_eq": lambda p: emit_str_eq(),
    "new_arr_i8": lambda p: emit_new_arr_i8(),
    "new_arr_i8_empty": lambda p: emit_new_arr_i8_empty(),
    "arr_i8_get": lambda p: emit_arr_i8_get(),
    "arr_i8_set": lambda p: emit_arr_i8_set(),
    "arr_i8_push": lambda p: emit_arr_i8_push(),
    "arr_i8_slice": lambda p: emit_arr_i8_slice(),
    "extend_i8": lambda p: emit_extend_i8(),
}

_HELPER_ORDER = [
    "bytes_str",
    "str_arr_i8",
    "str_eq",
    "new_arr_i8",
    "new_arr_i8_empty",
    "arr_i8_get",
    "arr_i8_set",
    "arr_i8_push",
    "arr_i8_slice",
    "extend_i8",
]


IMPLEMENTED_MIR_HELPERS = tuple(_HELPER_ORDER)


def inject_all_mir_helpers(program: MirProgram) -> None:
    """Inject every implemented MIR helper in deterministic order."""
    implemented = set(IMPLEMENTED_MIR_HELPERS)

    # Remove matching externs so validate() doesn't see duplicate symbols.
    program.externs[:] = [e for e in program.externs if e.name not in implemented]

    for name in IMPLEMENTED_MIR_HELPERS:
        program.functions.append(_HELPER_EMITTERS[name](program))
