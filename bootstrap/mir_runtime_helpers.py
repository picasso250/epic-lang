"""MIR runtime helpers loaded from the committed runtime MIR bundle.

The runtime helper bodies live in ``runtime/mir/helpers.mir`` so the Python and
self-hosted compilers consume the same helper text during development.
"""

from pathlib import Path

from mir_builder import MirFunctionBuilder
from mir import (
    BOOL,
    I32,
    I64,
    I8,
    VOID,
    ConstBoolOperand,
    ConstIntOperand,
    ConstNullOperand,
    MirFunction,
    MirGlobal,
    MirParam,
    MirProgram,
    MirValue,
    SymbolOperand,
    ValueOperand,
    ptr,
    struct as mir_struct,
)
from mir_parser import parse_mir_file


# ── MirHelperBuilder ──────────────────────────────────────────────────────


class MirHelperBuilder(MirFunctionBuilder):
    """Small builder that reduces MIR boilerplate when constructing helpers."""

    def __init__(self, name: str, params: list[MirParam], ret_type):
        super().__init__(
            name,
            params,
            ret_type,
            numbered_blocks=False,
            preincrement_values=False,
            create_entry=True,
        )

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

    def const_i64(self, n):
        return ConstIntOperand(I64, n)

    def const_i32(self, n):
        return ConstIntOperand(I32, n)

    def const_i8(self, n):
        return ConstIntOperand(I8, n)

    def call(self, callee, args, ret_type):
        """Append a call and return the result value (or None if void)."""
        result_type = ret_type if ret_type != VOID else None
        return self.inst("call", self._ops(*args), result_type=result_type, type=ret_type, callee=callee)

    def gep(self, source_type, base, indices, result_type=None):
        """Append a gep and return the result ptr value."""
        if result_type is None:
            result_type = ptr()
        ops = self._ops(base) + self._ops(*indices)
        return self.inst("gep", ops, result_type=result_type, type=source_type)

    def load(self, access_type, addr, result_type=None):
        """Append a load and return the result value."""
        if result_type is None:
            result_type = access_type
        return self.inst("load", self._ops(addr), result_type=result_type, type=access_type)

    def store(self, value, addr):
        """Append a store.  No result."""
        self.inst("store", self._ops(value, addr))

    def icmp(self, cond, left, right):
        """Append an icmp.<cond> and return the bool result value."""
        return self.inst(f"icmp.{cond}", self._ops(left, right), result_type=BOOL, type=BOOL)

    def binop(self, op, left, right):
        """Append an integer binary op (add/sub/and/…)."""
        return self.inst(op, self._ops(left, right), result_type=I64, type=I64)

    def alloca(self, elem_type):
        """Append an alloca and return the address."""
        return self.inst("alloca", result_type=ptr(), type=elem_type)

    def gep_field(self, base, struct_name, field_index, result_type=None):
        """Convenience: gep into a struct field by index (0/1/2)."""
        return self.gep(
            mir_struct(struct_name),
            self._op(base),
            [self.const_i64(0), self.const_i32(field_index)],
            result_type=result_type,
        )

# ── Helper emitters ───────────────────────────────────────────────────────

def emit_slice_u8_from_str() -> MirFunction:
    """View/convert str as u8[].

    fn __ep_slice_u8_from_str(ptr %s) -> ptr
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_from_str",
        [MirParam("s", ptr())],
        ptr(),
    )
    b.ret(ValueOperand(b.fn.params[0].value))
    return b.fn


def emit_str_from_slice_u8() -> MirFunction:
    """View/convert u8[] as str.

    fn __ep_str_from_slice_u8(ptr %input) -> ptr
    """
    b = MirHelperBuilder(
        "__ep_str_from_slice_u8",
        [MirParam("input", ptr())],
        ptr(),
    )
    b.ret(ValueOperand(b.fn.params[0].value))
    return b.fn

def emit___ep_str_cat() -> MirFunction:
    """Concatenate two strings into a newly allocated str.

    fn __ep_str_cat(ptr<str> %left, ptr<str> %right) -> ptr<str>
    """
    b = MirHelperBuilder(
        "__ep_str_cat",
        [
            MirParam("left", ptr()),
            MirParam("right", ptr()),
        ],
        ptr(),
    )
    left_val = ValueOperand(b.fn.params[0].value)
    right_val = ValueOperand(b.fn.params[1].value)

    left_len = b.load(I64, b.gep_field(left_val, "str", 1))
    right_len = b.load(I64, b.gep_field(right_val, "str", 1))
    result_len = b.binop("add", left_len, right_len)

    result_str = b.call("__epx_alloc", [b.const_i64(24)], ptr())
    data_len = b.binop("add", result_len, b.const_i64(1))
    result_data = b.call("__epx_alloc", [data_len], ptr())
    b.store(result_data, b.gep_field(ValueOperand(result_str), "str", 0))
    b.store(result_len, b.gep_field(ValueOperand(result_str), "str", 1))
    b.store(result_len, b.gep_field(ValueOperand(result_str), "str", 2))

    left_data = b.load(ptr(), b.gep_field(left_val, "str", 0))
    right_data = b.load(ptr(), b.gep_field(right_val, "str", 0))
    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    left_check = b.new_block("left_check")
    left_body = b.new_block("left_body")
    right_init = b.new_block("right_init")
    right_check = b.new_block("right_check")
    right_body = b.new_block("right_body")
    done = b.new_block("done")
    b.br(left_check)

    b.set_block(left_check)
    i = b.load(I64, ValueOperand(i_slot))
    keep_left = b.icmp("slt", i, left_len)
    b.condbr(ValueOperand(keep_left), left_body.name, right_init.name)

    b.set_block(left_body)
    src_addr = b.gep(I8, left_data, [i])
    byte = b.load(I8, src_addr, result_type=I8)
    dst_addr = b.gep(I8, ValueOperand(result_data), [i])
    b.store(ValueOperand(byte), dst_addr)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(left_check)

    b.set_block(right_init)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    b.br(right_check)

    b.set_block(right_check)
    i = b.load(I64, ValueOperand(i_slot))
    keep_right = b.icmp("slt", i, right_len)
    b.condbr(ValueOperand(keep_right), right_body.name, done.name)

    b.set_block(right_body)
    src_addr = b.gep(I8, right_data, [i])
    byte = b.load(I8, src_addr, result_type=I8)
    dst_index = b.binop("add", left_len, i)
    dst_addr = b.gep(I8, ValueOperand(result_data), [dst_index])
    b.store(ValueOperand(byte), dst_addr)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(right_check)

    b.set_block(done)
    nul_addr = b.gep(I8, ValueOperand(result_data), [result_len])
    b.store(b.const_i8(0), nul_addr)
    b.ret(ValueOperand(result_str))

    return b.fn




def emit_slice_u8_alloc() -> MirFunction:
    """Allocate header + data for u8[], with separate len and cap.

    fn __ep_slice_u8_alloc(i64 %len, i64 %cap) -> ptr<_slice_u8>
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_alloc",
        [MirParam("len", I64), MirParam("cap", I64)],
        ptr(),
    )
    len_val = ValueOperand(b.fn.params[0].value)
    cap_val = ValueOperand(b.fn.params[1].value)

    header_raw = b.call("__epx_alloc", [b.const_i64(24)], ptr())
    cap_zero = b.icmp("eq", cap_val, b.const_i64(0))
    zero_block = b.new_block("data_zero")
    alloc_block = b.new_block("data_alloc")
    init_block = b.new_block("init")
    b.condbr(ValueOperand(cap_zero), zero_block.name, alloc_block.name)

    b.set_block(zero_block)
    b.store(ConstNullOperand(), b.gep_field(ValueOperand(header_raw), "_slice_u8", 0))
    b.br(init_block.name)

    b.set_block(alloc_block)
    data_raw = b.call("__epx_alloc", [cap_val], ptr())
    b.store(data_raw, b.gep_field(ValueOperand(header_raw), "_slice_u8", 0))
    b.br(init_block.name)

    b.set_block(init_block)
    # header.len = len
    b.store(len_val, b.gep_field(ValueOperand(header_raw), "_slice_u8", 1))
    # header.cap = cap
    b.store(cap_val, b.gep_field(ValueOperand(header_raw), "_slice_u8", 2))

    b.ret(ValueOperand(header_raw))
    return b.fn


def emit_slice_u8_get() -> MirFunction:
    """Bounds-checked byte read from u8[].

    fn __ep_slice_u8_get(ptr<_slice_u8> %arr, i64 %idx) -> i64
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_get",
        [MirParam("arr", ptr()), MirParam("idx", I64)],
        I64,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)

    # Load arr.len
    len_addr = b.gep_field(arr_val, "_slice_u8", 1)
    arr_len = b.load(I64, len_addr)

    # Check idx >= 0
    ge_zero = b.icmp("sge", idx_val, b.const_i64(0))
    check_block = b.new_block("check_high")
    ok_block = b.new_block("ok")
    fail_block = b.new_block("fail")
    b.condbr(ValueOperand(ge_zero), check_block.name, fail_block.name)

    # check_high: idx < arr.len
    b.set_block(check_block)
    lt_len = b.icmp("slt", idx_val, arr_len)
    b.condbr(ValueOperand(lt_len), ok_block.name, fail_block.name)

    # ok: load byte
    b.set_block(ok_block)
    data_addr = b.gep_field(arr_val, "_slice_u8", 0)
    data = b.load(ptr(), data_addr)
    byte_addr = b.gep(I8, data, [idx_val])
    result = b.load(I8, byte_addr, result_type=I64)
    b.ret(ValueOperand(result))

    # fail: exit(1)
    b.set_block(fail_block)
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret(b.const_i64(0))  # dummy, unreachable

    return b.fn


def emit_slice_word_new(name: str) -> MirFunction:
    """Allocate a word-sized slice header.

    fn {name}(i64 %cap) -> ptr

    The argument is both the initial length and capacity.
    """
    b = MirHelperBuilder(
        name,
        [MirParam("cap", I64)],
        ptr(),
    )
    cap_val = ValueOperand(b.fn.params[0].value)

    header_raw = b.call("__epx_alloc", [b.const_i64(24)], ptr())
    cap_zero = b.icmp("eq", cap_val, b.const_i64(0))
    zero_block = b.new_block("data_zero")
    alloc_block = b.new_block("data_alloc")
    init_block = b.new_block("init")
    b.condbr(ValueOperand(cap_zero), zero_block.name, alloc_block.name)

    b.set_block(zero_block)
    b.store(ConstNullOperand(), b.gep(ptr(), ValueOperand(header_raw), [b.const_i64(0)]))
    b.br(init_block)

    b.set_block(alloc_block)
    bytes_len = b.binop("add", cap_val, cap_val)
    bytes_len = b.binop("add", ValueOperand(bytes_len), ValueOperand(bytes_len))
    bytes_len = b.binop("add", ValueOperand(bytes_len), ValueOperand(bytes_len))
    data_raw = b.call("__epx_alloc", [ValueOperand(bytes_len)], ptr())
    b.store(data_raw, b.gep(ptr(), ValueOperand(header_raw), [b.const_i64(0)]))
    b.br(init_block)

    b.set_block(init_block)
    b.store(cap_val, b.gep(ptr(), ValueOperand(header_raw), [b.const_i64(1)]))
    b.store(cap_val, b.gep(ptr(), ValueOperand(header_raw), [b.const_i64(2)]))
    b.ret(ValueOperand(header_raw))

    return b.fn


def emit_slice_word_get(name: str, elem_type) -> MirFunction:
    """Bounds-checked read from a word-sized slice."""
    b = MirHelperBuilder(
        name,
        [MirParam("arr", ptr()), MirParam("idx", I64)],
        elem_type,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)

    len_addr = b.gep(ptr(), arr_val, [b.const_i64(1)])
    arr_len = b.load(I64, len_addr)

    ge_zero = b.icmp("sge", idx_val, b.const_i64(0))
    check_block = b.new_block("check_high")
    ok_block = b.new_block("ok")
    fail_block = b.new_block("fail")
    b.condbr(ValueOperand(ge_zero), check_block.name, fail_block.name)

    b.set_block(check_block)
    lt_len = b.icmp("slt", idx_val, arr_len)
    b.condbr(ValueOperand(lt_len), ok_block.name, fail_block.name)

    b.set_block(ok_block)
    data_addr = b.gep(ptr(), arr_val, [b.const_i64(0)])
    data = b.load(ptr(), data_addr)
    elem_addr = b.gep(ptr(), data, [idx_val])
    result = b.load(elem_type, elem_addr)
    b.ret(ValueOperand(result))

    b.set_block(fail_block)
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    if elem_type.kind == "ptr":
        b.ret(ConstNullOperand())
    else:
        b.ret(b.const_i64(0))

    return b.fn


def emit_slice_word_set(name: str, elem_type) -> MirFunction:
    """Bounds-checked write to a word-sized slice."""
    b = MirHelperBuilder(
        name,
        [
            MirParam("arr", ptr()),
            MirParam("idx", I64),
            MirParam("val", elem_type),
        ],
        VOID,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)
    val_val = ValueOperand(b.fn.params[2].value)

    len_addr = b.gep(ptr(), arr_val, [b.const_i64(1)])
    arr_len = b.load(I64, len_addr)

    ge_zero = b.icmp("sge", idx_val, b.const_i64(0))
    check_block = b.new_block("check_high")
    ok_block = b.new_block("ok")
    fail_block = b.new_block("fail")
    b.condbr(ValueOperand(ge_zero), check_block.name, fail_block.name)

    b.set_block(check_block)
    lt_len = b.icmp("slt", idx_val, arr_len)
    b.condbr(ValueOperand(lt_len), ok_block.name, fail_block.name)

    b.set_block(ok_block)
    data_addr = b.gep(ptr(), arr_val, [b.const_i64(0)])
    data = b.load(ptr(), data_addr)
    elem_addr = b.gep(ptr(), data, [idx_val])
    b.store(val_val, elem_addr)
    b.ret()

    b.set_block(fail_block)
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret()

    return b.fn


def emit_slice_word_push(name: str, elem_type) -> MirFunction:
    """Push one word-sized element, growing from zero capacity to four."""
    b = MirHelperBuilder(
        name,
        [
            MirParam("arr", ptr()),
            MirParam("val", elem_type),
        ],
        VOID,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    val_val = ValueOperand(b.fn.params[1].value)

    len_addr = b.gep(ptr(), arr_val, [b.const_i64(1)])
    old_len = b.load(I64, len_addr)
    cap_addr = b.gep(ptr(), arr_val, [b.const_i64(2)])
    old_cap = b.load(I64, cap_addr)

    need_grow = b.icmp("sge", old_len, old_cap)
    grow_block = b.new_block("grow")
    store_block = b.new_block("store")
    b.condbr(ValueOperand(need_grow), grow_block.name, store_block.name)

    b.set_block(grow_block)
    new_cap_slot = b.alloca(I64)
    new_data_slot = b.alloca(ptr())
    i_slot = b.alloca(I64)

    cap_zero = b.icmp("eq", old_cap, b.const_i64(0))
    zero_block = b.new_block("grow_zero")
    double_block = b.new_block("grow_double")
    b.condbr(ValueOperand(cap_zero), zero_block.name, double_block.name)

    b.set_block(zero_block)
    nc0 = b.const_i64(4)
    b.store(nc0, ValueOperand(new_cap_slot))
    bytes0 = b.const_i64(32)
    nd0 = b.call("__epx_alloc", [bytes0], ptr())
    b.store(nd0, ValueOperand(new_data_slot))
    copy_entry = b.new_block("copy_entry")
    b.br(copy_entry)

    b.set_block(double_block)
    nc1 = b.binop("add", old_cap, old_cap)
    b.store(nc1, ValueOperand(new_cap_slot))
    bytes1 = b.binop("add", ValueOperand(nc1), ValueOperand(nc1))
    bytes1 = b.binop("add", ValueOperand(bytes1), ValueOperand(bytes1))
    bytes1 = b.binop("add", ValueOperand(bytes1), ValueOperand(bytes1))
    nd1 = b.call("__epx_alloc", [ValueOperand(bytes1)], ptr())
    b.store(nd1, ValueOperand(new_data_slot))
    b.br(copy_entry)

    b.set_block(copy_entry)
    old_data = b.load(ptr(), b.gep(ptr(), arr_val, [b.const_i64(0)]))
    new_data = b.load(ptr(), ValueOperand(new_data_slot))
    b.store(b.const_i64(0), ValueOperand(i_slot))
    copy_check = b.new_block("copy_check")
    b.br(copy_check)

    b.set_block(copy_check)
    i = b.load(I64, ValueOperand(i_slot))
    cond = b.icmp("slt", i, old_len)
    copy_body = b.new_block("copy_body")
    swap_block = b.new_block("swap")
    b.condbr(ValueOperand(cond), copy_body.name, swap_block.name)

    b.set_block(copy_body)
    old_elem_addr = b.gep(ptr(), old_data, [i])
    old_elem = b.load(elem_type, old_elem_addr)
    new_elem_addr = b.gep(ptr(), new_data, [i])
    b.store(ValueOperand(old_elem), new_elem_addr)
    i_next = b.binop("add", i, b.const_i64(1))
    b.store(i_next, ValueOperand(i_slot))
    b.br(copy_check)

    b.set_block(swap_block)
    b.store(new_data, b.gep(ptr(), arr_val, [b.const_i64(0)]))
    final_cap = b.load(I64, ValueOperand(new_cap_slot))
    b.store(final_cap, cap_addr)
    b.br(store_block)

    b.set_block(store_block)
    data = b.load(ptr(), b.gep(ptr(), arr_val, [b.const_i64(0)]))
    elem_addr = b.gep(ptr(), data, [old_len])
    b.store(val_val, elem_addr)
    new_len = b.binop("add", old_len, b.const_i64(1))
    b.store(new_len, len_addr)
    b.ret()

    return b.fn


def emit_slice_u8_set() -> MirFunction:
    """Bounds-checked byte write to u8[].

    fn __ep_slice_u8_set(ptr<_slice_u8> %arr, i64 %idx, i64 %val) -> void
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_set",
        [
            MirParam("arr", ptr()),
            MirParam("idx", I64),
            MirParam("val", I64),
        ],
        VOID,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)
    val_val = ValueOperand(b.fn.params[2].value)

    # Load arr.len
    len_addr = b.gep_field(arr_val, "_slice_u8", 1)
    arr_len = b.load(I64, len_addr)

    # Check idx >= 0
    ge_zero = b.icmp("sge", idx_val, b.const_i64(0))
    check_block = b.new_block("check_high")
    ok_block = b.new_block("ok")
    fail_block = b.new_block("fail")
    b.condbr(ValueOperand(ge_zero), check_block.name, fail_block.name)

    # check_high: idx < arr.len
    b.set_block(check_block)
    lt_len = b.icmp("slt", idx_val, arr_len)
    b.condbr(ValueOperand(lt_len), ok_block.name, fail_block.name)

    # ok: store byte (truncate i64 to i8 via alloca roundtrip)
    b.set_block(ok_block)
    trunc_slot = b.alloca(I64)
    b.store(val_val, ValueOperand(trunc_slot))
    byte_val = b.load(I8, ValueOperand(trunc_slot), result_type=I8)

    data_addr = b.gep_field(arr_val, "_slice_u8", 0)
    data = b.load(ptr(), data_addr)
    byte_addr = b.gep(I8, data, [idx_val])
    b.store(ValueOperand(byte_val), byte_addr)
    b.ret()

    # fail: exit(1)
    b.set_block(fail_block)
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret()  # dummy, unreachable

    return b.fn


def emit_slice_u8_push() -> MirFunction:
    """Push a byte value onto a u8[] array.

    fn __ep_slice_u8_push(ptr<_slice_u8> %arr, i64 %val) -> void

    Grows by doubling capacity when full, using __epx_alloc for new
    backing storage.  Matches the old _emit_slice_u8_push x64 behaviour.
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_push",
        [
            MirParam("arr", ptr()),
            MirParam("val", I64),
        ],
        VOID,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    val_val = ValueOperand(b.fn.params[1].value)

    # Load old_len (field 1) and old_cap (field 2)
    len_addr = b.gep_field(arr_val, "_slice_u8", 1)
    old_len = b.load(I64, len_addr)
    cap_addr = b.gep_field(arr_val, "_slice_u8", 2)
    old_cap = b.load(I64, cap_addr)

    # Check if grow needed
    need_grow = b.icmp("sge", old_len, old_cap)
    grow_block = b.new_block("grow")
    store_block = b.new_block("store")
    b.condbr(ValueOperand(need_grow), grow_block.name, store_block.name)

    # grow: allocate slots for grow results, dispatch zero vs double
    b.set_block(grow_block)
    new_cap_slot = b.alloca(I64)
    new_data_slot = b.alloca(ptr())
    i_slot = b.alloca(I64)

    cap_zero = b.icmp("eq", old_cap, b.const_i64(0))
    zero_block = b.new_block("grow_zero")
    double_block = b.new_block("grow_double")
    b.condbr(ValueOperand(cap_zero), zero_block.name, double_block.name)

    # grow_zero: new_cap = 4
    b.set_block(zero_block)
    nc0 = b.const_i64(4)
    b.store(nc0, ValueOperand(new_cap_slot))
    nd0 = b.call("__epx_alloc", [nc0], ptr())
    b.store(nd0, ValueOperand(new_data_slot))
    copy_entry = b.new_block("copy_entry")
    b.condbr(ValueOperand(cap_zero), copy_entry.name, copy_entry.name)

    # grow_double: new_cap = old_cap * 2
    b.set_block(double_block)
    nc1 = b.binop("add", old_cap, old_cap)
    b.store(nc1, ValueOperand(new_cap_slot))
    nd1 = b.call("__epx_alloc", [nc1], ptr())
    b.store(nd1, ValueOperand(new_data_slot))
    b.condbr(ValueOperand(cap_zero), copy_entry.name, copy_entry.name)

    # copy_entry: load data pointer, init copy loop
    b.set_block(copy_entry)
    old_data = b.load(ptr(), b.gep_field(arr_val, "_slice_u8", 0))
    new_data = b.load(ptr(), ValueOperand(new_data_slot))
    b.store(b.const_i64(0), ValueOperand(i_slot))
    copy_check = b.new_block("copy_check")
    b.condbr(ValueOperand(cap_zero), copy_check.name, copy_check.name)

    # copy_check: loop condition i < old_len
    b.set_block(copy_check)
    i = b.load(I64, ValueOperand(i_slot))
    cond = b.icmp("slt", i, old_len)
    copy_body = b.new_block("copy_body")
    swap_block = b.new_block("swap")
    b.condbr(ValueOperand(cond), copy_body.name, swap_block.name)

    # copy_body: copy one byte
    b.set_block(copy_body)
    old_byte_addr = b.gep(I8, old_data, [i])
    old_byte = b.load(I8, old_byte_addr, result_type=I8)
    new_byte_addr = b.gep(I8, new_data, [i])
    b.store(ValueOperand(old_byte), new_byte_addr)
    i_next = b.binop("add", i, b.const_i64(1))
    b.store(i_next, ValueOperand(i_slot))
    b.condbr(ValueOperand(cap_zero), copy_check.name, copy_check.name)

    # swap: update arr.data and arr.cap
    b.set_block(swap_block)
    b.store(new_data, b.gep_field(arr_val, "_slice_u8", 0))
    final_cap = b.load(I64, ValueOperand(new_cap_slot))
    b.store(final_cap, b.gep_field(arr_val, "_slice_u8", 2))
    b.condbr(ValueOperand(cap_zero), store_block.name, store_block.name)

    # store: write byte and update len
    b.set_block(store_block)
    trunc_slot = b.alloca(I64)
    b.store(val_val, ValueOperand(trunc_slot))
    byte_val = b.load(I8, ValueOperand(trunc_slot), result_type=I8)
    data = b.load(ptr(), b.gep_field(arr_val, "_slice_u8", 0))
    byte_addr = b.gep(I8, data, [old_len])
    b.store(ValueOperand(byte_val), byte_addr)
    new_len = b.binop("add", old_len, b.const_i64(1))
    b.store(new_len, b.gep_field(arr_val, "_slice_u8", 1))
    b.ret()

    return b.fn


def emit_slice_u8_slice() -> MirFunction:
    """Copy a half-open u8[] slice [start:end].

    fn __ep_slice_u8_slice(ptr<_slice_u8> %arr, i64 %start, i64 %end) -> ptr<_slice_u8>

    Bounds failures exit with code 1, matching the old x64 helper.
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_slice",
        [
            MirParam("arr", ptr()),
            MirParam("start", I64),
            MirParam("end", I64),
        ],
        ptr(),
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    start_val = ValueOperand(b.fn.params[1].value)
    end_val = ValueOperand(b.fn.params[2].value)

    arr_len = b.load(I64, b.gep_field(arr_val, "_slice_u8", 1))

    start_ok = b.icmp("sge", start_val, b.const_i64(0))
    check_order = b.new_block("check_order")
    check_len = b.new_block("check_len")
    alloc_block = b.new_block("alloc")
    copy_check = b.new_block("copy_check")
    copy_body = b.new_block("copy_body")
    done_block = b.new_block("done")
    fail_block = b.new_block("fail")
    b.condbr(ValueOperand(start_ok), check_order.name, fail_block.name)

    b.set_block(check_order)
    order_ok = b.icmp("sge", end_val, start_val)
    b.condbr(ValueOperand(order_ok), check_len.name, fail_block.name)

    b.set_block(check_len)
    len_ok = b.icmp("sge", arr_len, end_val)
    b.condbr(ValueOperand(len_ok), alloc_block.name, fail_block.name)

    b.set_block(alloc_block)
    slice_len = b.binop("sub", end_val, start_val)
    result_arr = b.call("__ep_slice_u8_alloc", [slice_len, slice_len], ptr())
    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    src_data = b.load(ptr(), b.gep_field(arr_val, "_slice_u8", 0))
    src_start = b.gep(I8, src_data, [start_val])
    dst_data = b.load(ptr(), b.gep_field(ValueOperand(result_arr), "_slice_u8", 0))
    b.br(copy_check)

    b.set_block(copy_check)
    i = b.load(I64, ValueOperand(i_slot))
    keep_copying = b.icmp("slt", i, slice_len)
    b.condbr(ValueOperand(keep_copying), copy_body.name, done_block.name)

    b.set_block(copy_body)
    src_byte_addr = b.gep(I8, src_start, [i])
    byte = b.load(I8, src_byte_addr, result_type=I8)
    dst_byte_addr = b.gep(I8, dst_data, [i])
    b.store(ValueOperand(byte), dst_byte_addr)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(copy_check)

    b.set_block(done_block)
    b.ret(ValueOperand(result_arr))

    b.set_block(fail_block)
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret(ConstNullOperand())

    return b.fn


def emit_extend_slice_u8() -> MirFunction:
    """Append src bytes into dst, snapshotting src.len before the loop.

    fn __ep_slice_u8_extend(ptr<_slice_u8> %dst, ptr<_slice_u8> %src) -> void
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_extend",
        [
            MirParam("dst", ptr()),
            MirParam("src", ptr()),
        ],
        VOID,
    )
    dst_val = ValueOperand(b.fn.params[0].value)
    src_val = ValueOperand(b.fn.params[1].value)

    src_len = b.load(I64, b.gep_field(src_val, "_slice_u8", 1))
    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    loop_check = b.new_block("loop_check")
    loop_body = b.new_block("loop_body")
    done = b.new_block("done")
    b.br(loop_check)

    b.set_block(loop_check)
    i = b.load(I64, ValueOperand(i_slot))
    keep_copying = b.icmp("slt", i, src_len)
    b.condbr(ValueOperand(keep_copying), loop_body.name, done.name)

    b.set_block(loop_body)
    byte = b.call("__ep_slice_u8_get", [src_val, i], I64)
    b.call("__ep_slice_u8_push", [dst_val, ValueOperand(byte)], VOID)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(loop_check)

    b.set_block(done)
    b.ret()

    return b.fn


# ── Map helpers ────────────────────────────────────────────────────────────


def emit_map_str_word_new(name: str, map_type) -> MirFunction:
    """Allocate an empty map header with no backing entries.

    The backing entry array is allocated lazily by set.  The header layout is
    {entries, len, cap}.  Entries are three word-sized slots: {key, value,
    occupied}.
    """
    b = MirHelperBuilder(name, [], map_type)
    header_raw = b.call("__epx_alloc", [b.const_i64(24)], ptr())
    header = ValueOperand(header_raw)
    b.store(ConstNullOperand(), b.gep(ptr(), header, [b.const_i64(0)]))
    b.store(b.const_i64(0), b.gep(ptr(), header, [b.const_i64(1)]))
    b.store(b.const_i64(0), b.gep(ptr(), header, [b.const_i64(2)]))
    b.ret(header)
    return b.fn


def _map_entry_word_index(b: MirHelperBuilder, index):
    twice = b.binop("add", index, index)
    return b.binop("add", ValueOperand(twice), index)


def _map_entry_addr(b: MirHelperBuilder, data, index):
    word_index = _map_entry_word_index(b, index)
    return b.gep(ptr(), data, [ValueOperand(word_index)])


def _map_zero_operand(value_type):
    if value_type.kind == "ptr":
        return SymbolOperand(ptr(), "str.runtime.empty")
    if value_type == BOOL:
        return ConstBoolOperand(False)
    return ConstIntOperand(value_type, 0)



def emit___ep_str_cmp() -> MirFunction:
    """Compare two Epic strings bytewise. Return -1, 0, or 1."""
    b = MirHelperBuilder(
        "__ep_str_cmp",
        [MirParam("left", ptr()), MirParam("right", ptr())],
        I64,
    )
    left_val = ValueOperand(b.fn.params[0].value)
    right_val = ValueOperand(b.fn.params[1].value)

    left_data = b.load(ptr(), b.gep_field(left_val, "str", 0))
    left_len = b.load(I64, b.gep_field(left_val, "str", 1))
    right_data = b.load(ptr(), b.gep_field(right_val, "str", 0))
    right_len = b.load(I64, b.gep_field(right_val, "str", 1))

    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    loop_check = b.new_block("loop_check")
    check_right = b.new_block("check_right")
    body = b.new_block("body")
    left_done = b.new_block("left_done")
    next_block = b.new_block("next")
    less = b.new_block("less")
    greater = b.new_block("greater")
    equal = b.new_block("equal")
    right_done = b.new_block("right_done")
    check_gt = b.new_block("check_gt")
    b.br(loop_check)

    b.set_block(loop_check)
    i = b.load(I64, ValueOperand(i_slot))
    left_has = b.icmp("slt", ValueOperand(i), ValueOperand(left_len))
    b.condbr(ValueOperand(left_has), check_right.name, left_done.name)

    b.set_block(check_right)
    i2 = b.load(I64, ValueOperand(i_slot))
    right_has = b.icmp("slt", ValueOperand(i2), ValueOperand(right_len))
    b.condbr(ValueOperand(right_has), body.name, greater.name)

    b.set_block(body)
    i3 = b.load(I64, ValueOperand(i_slot))
    left_byte_addr = b.gep(I8, ValueOperand(left_data), [ValueOperand(i3)])
    left_byte = b.load(I8, ValueOperand(left_byte_addr), result_type=I8)
    right_byte_addr = b.gep(I8, ValueOperand(right_data), [ValueOperand(i3)])
    right_byte = b.load(I8, ValueOperand(right_byte_addr), result_type=I8)
    is_less = b.icmp("ult", ValueOperand(left_byte), ValueOperand(right_byte))
    b.condbr(ValueOperand(is_less), less.name, check_gt.name)

    b.set_block(check_gt)
    is_greater = b.icmp("ugt", ValueOperand(left_byte), ValueOperand(right_byte))
    b.condbr(ValueOperand(is_greater), greater.name, next_block.name)

    b.set_block(next_block)
    next_i = b.binop("add", ValueOperand(i3), b.const_i64(1))
    b.store(ValueOperand(next_i), ValueOperand(i_slot))
    b.br(loop_check)

    b.set_block(left_done)
    i4 = b.load(I64, ValueOperand(i_slot))
    right_has_more = b.icmp("slt", ValueOperand(i4), ValueOperand(right_len))
    b.condbr(ValueOperand(right_has_more), less.name, equal.name)

    b.set_block(less)
    b.ret(b.const_i64(-1))

    b.set_block(greater)
    b.ret(b.const_i64(1))

    b.set_block(equal)
    b.ret(b.const_i64(0))

    b.set_block(right_done)
    b.ret(b.const_i64(1))
    return b.fn


def emit_map_str_find_pos() -> MirFunction:
    """Binary search a sorted str-keyed word map. Return index or -(lo + 1)."""
    b = MirHelperBuilder(
        "__ep_map_str_find_pos",
        [MirParam("map", ptr()), MirParam("key", ptr())],
        I64,
    )
    map_val = ValueOperand(b.fn.params[0].value)
    key_val = ValueOperand(b.fn.params[1].value)

    len_addr = b.gep(ptr(), map_val, [b.const_i64(1)])
    map_len = b.load(I64, len_addr)
    data_addr = b.gep(ptr(), map_val, [b.const_i64(0)])
    data = b.load(ptr(), data_addr)

    lo_slot = b.alloca(I64)
    hi_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(lo_slot))
    b.store(ValueOperand(map_len), ValueOperand(hi_slot))

    loop_check = b.new_block("loop_check")
    loop_body = b.new_block("loop_body")
    found = b.new_block("found")
    check_less = b.new_block("check_less")
    move_lo = b.new_block("move_lo")
    move_hi = b.new_block("move_hi")
    miss = b.new_block("miss")
    b.br(loop_check)

    b.set_block(loop_check)
    lo = b.load(I64, ValueOperand(lo_slot))
    hi = b.load(I64, ValueOperand(hi_slot))
    keep_going = b.icmp("slt", ValueOperand(lo), ValueOperand(hi))
    b.condbr(ValueOperand(keep_going), loop_body.name, miss.name)

    b.set_block(loop_body)
    lo2 = b.load(I64, ValueOperand(lo_slot))
    hi2 = b.load(I64, ValueOperand(hi_slot))
    sum_v = b.binop("add", ValueOperand(lo2), ValueOperand(hi2))
    mid = b.binop("sdiv", ValueOperand(sum_v), b.const_i64(2))
    entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(mid))
    key_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(0)])
    entry_key = b.load(ptr(), ValueOperand(key_addr))
    cmp = b.call("__ep_str_cmp", [ValueOperand(entry_key), key_val], I64)
    is_equal = b.icmp("eq", ValueOperand(cmp), b.const_i64(0))
    b.condbr(ValueOperand(is_equal), found.name, check_less.name)

    b.set_block(check_less)
    is_less = b.icmp("slt", ValueOperand(cmp), b.const_i64(0))
    b.condbr(ValueOperand(is_less), move_lo.name, move_hi.name)

    b.set_block(move_lo)
    next_lo = b.binop("add", ValueOperand(mid), b.const_i64(1))
    b.store(ValueOperand(next_lo), ValueOperand(lo_slot))
    b.br(loop_check)

    b.set_block(move_hi)
    b.store(ValueOperand(mid), ValueOperand(hi_slot))
    b.br(loop_check)

    b.set_block(found)
    b.ret(ValueOperand(mid))

    b.set_block(miss)
    final_lo = b.load(I64, ValueOperand(lo_slot))
    neg_lo = b.binop("sub", b.const_i64(0), ValueOperand(final_lo))
    encoded = b.binop("sub", ValueOperand(neg_lo), b.const_i64(1))
    b.ret(ValueOperand(encoded))
    return b.fn


def emit_map_str_word_get(name: str, map_type, value_type) -> MirFunction:
    """Lookup a str key in a sorted word-valued map, returning value zero on miss."""
    b = MirHelperBuilder(
        name,
        [MirParam("map", map_type), MirParam("key", ptr())],
        value_type,
    )
    map_val = ValueOperand(b.fn.params[0].value)
    key_val = ValueOperand(b.fn.params[1].value)
    data = b.load(ptr(), b.gep(ptr(), map_val, [b.const_i64(0)]))
    pos = b.call("__ep_map_str_find_pos", [map_val, key_val], I64)
    found = b.icmp("sge", ValueOperand(pos), b.const_i64(0))
    found_block = b.new_block("found")
    miss = b.new_block("miss")
    b.condbr(ValueOperand(found), found_block.name, miss.name)

    b.set_block(found_block)
    entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(pos))
    value_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(1)])
    result = b.load(value_type, ValueOperand(value_addr))
    b.ret(ValueOperand(result))

    b.set_block(miss)
    b.ret(_map_zero_operand(value_type))
    return b.fn


def emit_map_str_word_has(name: str, map_type) -> MirFunction:
    """Return true when a key exists in a sorted str-keyed map."""
    b = MirHelperBuilder(
        name,
        [MirParam("map", map_type), MirParam("key", ptr())],
        BOOL,
    )
    map_val = ValueOperand(b.fn.params[0].value)
    key_val = ValueOperand(b.fn.params[1].value)
    pos = b.call("__ep_map_str_find_pos", [map_val, key_val], I64)
    found = b.icmp("sge", ValueOperand(pos), b.const_i64(0))
    b.ret(ValueOperand(found))
    return b.fn


def emit_map_str_word_set(name: str, map_type, value_type) -> MirFunction:
    """Insert or update a key/value entry in a sorted str-keyed word map."""
    b = MirHelperBuilder(
        name,
        [MirParam("map", map_type), MirParam("key", ptr()), MirParam("val", value_type)],
        VOID,
    )
    map_val = ValueOperand(b.fn.params[0].value)
    key_val = ValueOperand(b.fn.params[1].value)
    val_val = ValueOperand(b.fn.params[2].value)

    len_addr = b.gep(ptr(), map_val, [b.const_i64(1)])
    old_len = b.load(I64, len_addr)
    cap_addr = b.gep(ptr(), map_val, [b.const_i64(2)])
    old_cap = b.load(I64, cap_addr)
    data_addr = b.gep(ptr(), map_val, [b.const_i64(0)])
    old_data = b.load(ptr(), data_addr)

    pos = b.call("__ep_map_str_find_pos", [map_val, key_val], I64)
    found = b.icmp("sge", ValueOperand(pos), b.const_i64(0))
    update = b.new_block("update")
    insert_prep = b.new_block("insert_prep")
    b.condbr(ValueOperand(found), update.name, insert_prep.name)

    b.set_block(update)
    update_entry = _map_entry_addr(b, ValueOperand(old_data), ValueOperand(pos))
    update_value_addr = b.gep(ptr(), ValueOperand(update_entry), [b.const_i64(1)])
    b.store(val_val, ValueOperand(update_value_addr))
    b.ret()

    b.set_block(insert_prep)
    insert_at_slot = b.alloca(I64)
    neg_pos = b.binop("sub", b.const_i64(0), ValueOperand(pos))
    insert_at = b.binop("sub", ValueOperand(neg_pos), b.const_i64(1))
    b.store(ValueOperand(insert_at), ValueOperand(insert_at_slot))
    need_grow = b.icmp("sge", ValueOperand(old_len), ValueOperand(old_cap))
    grow = b.new_block("grow")
    shift_init = b.new_block("shift_init")
    b.condbr(ValueOperand(need_grow), grow.name, shift_init.name)

    b.set_block(grow)
    new_cap_slot = b.alloca(I64)
    new_data_slot = b.alloca(ptr())
    copy_i_slot = b.alloca(I64)
    cap_zero = b.icmp("eq", ValueOperand(old_cap), b.const_i64(0))
    grow_zero = b.new_block("grow_zero")
    grow_double = b.new_block("grow_double")
    copy_init = b.new_block("copy_init")
    b.condbr(ValueOperand(cap_zero), grow_zero.name, grow_double.name)

    b.set_block(grow_zero)
    b.store(b.const_i64(4), ValueOperand(new_cap_slot))
    b.br(copy_init)

    b.set_block(grow_double)
    doubled = b.binop("add", ValueOperand(old_cap), ValueOperand(old_cap))
    b.store(ValueOperand(doubled), ValueOperand(new_cap_slot))
    b.br(copy_init)

    b.set_block(copy_init)
    new_cap = b.load(I64, ValueOperand(new_cap_slot))
    bytes_count = b.binop("mul", ValueOperand(new_cap), b.const_i64(24))
    new_data = b.call("__epx_alloc", [ValueOperand(bytes_count)], ptr())
    b.store(ValueOperand(new_data), ValueOperand(new_data_slot))
    b.store(b.const_i64(0), ValueOperand(copy_i_slot))
    copy_check = b.new_block("copy_check")
    copy_body = b.new_block("copy_body")
    swap = b.new_block("swap")
    b.br(copy_check)

    b.set_block(copy_check)
    copy_i = b.load(I64, ValueOperand(copy_i_slot))
    total_words = b.binop("mul", ValueOperand(old_len), b.const_i64(3))
    keep_copying = b.icmp("slt", ValueOperand(copy_i), ValueOperand(total_words))
    b.condbr(ValueOperand(keep_copying), copy_body.name, swap.name)

    b.set_block(copy_body)
    old_word_addr = b.gep(ptr(), ValueOperand(old_data), [ValueOperand(copy_i)])
    old_word = b.load(I64, ValueOperand(old_word_addr))
    new_data_for_copy = b.load(ptr(), ValueOperand(new_data_slot))
    new_word_addr = b.gep(ptr(), ValueOperand(new_data_for_copy), [ValueOperand(copy_i)])
    b.store(ValueOperand(old_word), ValueOperand(new_word_addr))
    copy_next = b.binop("add", ValueOperand(copy_i), b.const_i64(1))
    b.store(ValueOperand(copy_next), ValueOperand(copy_i_slot))
    b.br(copy_check)

    b.set_block(swap)
    final_data = b.load(ptr(), ValueOperand(new_data_slot))
    b.store(ValueOperand(final_data), ValueOperand(data_addr))
    final_cap = b.load(I64, ValueOperand(new_cap_slot))
    b.store(ValueOperand(final_cap), ValueOperand(cap_addr))
    b.br(shift_init)

    b.set_block(shift_init)
    data = b.load(ptr(), ValueOperand(data_addr))
    j_slot = b.alloca(I64)
    b.store(ValueOperand(old_len), ValueOperand(j_slot))
    shift_check = b.new_block("shift_check")
    shift_body = b.new_block("shift_body")
    write_entry = b.new_block("write_entry")
    b.br(shift_check)

    b.set_block(shift_check)
    j = b.load(I64, ValueOperand(j_slot))
    insert_at_now = b.load(I64, ValueOperand(insert_at_slot))
    should_shift = b.icmp("sgt", ValueOperand(j), ValueOperand(insert_at_now))
    b.condbr(ValueOperand(should_shift), shift_body.name, write_entry.name)

    b.set_block(shift_body)
    j2 = b.load(I64, ValueOperand(j_slot))
    src_index = b.binop("sub", ValueOperand(j2), b.const_i64(1))
    src_entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(src_index))
    dst_entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(j2))
    src_key_addr = b.gep(ptr(), ValueOperand(src_entry), [b.const_i64(0)])
    src_key = b.load(I64, ValueOperand(src_key_addr))
    dst_key_addr = b.gep(ptr(), ValueOperand(dst_entry), [b.const_i64(0)])
    b.store(ValueOperand(src_key), ValueOperand(dst_key_addr))
    src_value_addr = b.gep(ptr(), ValueOperand(src_entry), [b.const_i64(1)])
    src_value = b.load(I64, ValueOperand(src_value_addr))
    dst_value_addr = b.gep(ptr(), ValueOperand(dst_entry), [b.const_i64(1)])
    b.store(ValueOperand(src_value), ValueOperand(dst_value_addr))
    src_occ_addr = b.gep(ptr(), ValueOperand(src_entry), [b.const_i64(2)])
    src_occ = b.load(I64, ValueOperand(src_occ_addr))
    dst_occ_addr = b.gep(ptr(), ValueOperand(dst_entry), [b.const_i64(2)])
    b.store(ValueOperand(src_occ), ValueOperand(dst_occ_addr))
    prev_j = b.binop("sub", ValueOperand(j2), b.const_i64(1))
    b.store(ValueOperand(prev_j), ValueOperand(j_slot))
    b.br(shift_check)

    b.set_block(write_entry)
    insert_at_final = b.load(I64, ValueOperand(insert_at_slot))
    data_final = b.load(ptr(), ValueOperand(data_addr))
    new_entry = _map_entry_addr(b, ValueOperand(data_final), ValueOperand(insert_at_final))
    new_key_addr = b.gep(ptr(), ValueOperand(new_entry), [b.const_i64(0)])
    b.store(key_val, ValueOperand(new_key_addr))
    new_value_addr = b.gep(ptr(), ValueOperand(new_entry), [b.const_i64(1)])
    b.store(val_val, ValueOperand(new_value_addr))
    new_occ_addr = b.gep(ptr(), ValueOperand(new_entry), [b.const_i64(2)])
    b.store(b.const_i64(1), ValueOperand(new_occ_addr))
    new_len = b.binop("add", ValueOperand(old_len), b.const_i64(1))
    b.store(ValueOperand(new_len), ValueOperand(len_addr))
    b.ret()
    return b.fn


def emit_map_str_word_del(name: str, map_type) -> MirFunction:
    """Delete a key from a sorted str-keyed word map by shifting entries left."""
    b = MirHelperBuilder(
        name,
        [MirParam("map", map_type), MirParam("key", ptr())],
        BOOL,
    )
    map_val = ValueOperand(b.fn.params[0].value)
    key_val = ValueOperand(b.fn.params[1].value)

    len_addr = b.gep(ptr(), map_val, [b.const_i64(1)])
    old_len = b.load(I64, len_addr)
    data_addr = b.gep(ptr(), map_val, [b.const_i64(0)])
    data = b.load(ptr(), data_addr)
    pos = b.call("__ep_map_str_find_pos", [map_val, key_val], I64)
    found = b.icmp("sge", ValueOperand(pos), b.const_i64(0))
    shift_init = b.new_block("shift_init")
    no = b.new_block("no")
    b.condbr(ValueOperand(found), shift_init.name, no.name)

    b.set_block(shift_init)
    last_index = b.binop("sub", ValueOperand(old_len), b.const_i64(1))
    i_slot = b.alloca(I64)
    b.store(ValueOperand(pos), ValueOperand(i_slot))
    shift_check = b.new_block("shift_check")
    shift_body = b.new_block("shift_body")
    clear_last = b.new_block("clear_last")
    b.br(shift_check)

    b.set_block(shift_check)
    i = b.load(I64, ValueOperand(i_slot))
    keep_shifting = b.icmp("slt", ValueOperand(i), ValueOperand(last_index))
    b.condbr(ValueOperand(keep_shifting), shift_body.name, clear_last.name)

    b.set_block(shift_body)
    i2 = b.load(I64, ValueOperand(i_slot))
    src_index = b.binop("add", ValueOperand(i2), b.const_i64(1))
    src_entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(src_index))
    dst_entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(i2))
    src_key_addr = b.gep(ptr(), ValueOperand(src_entry), [b.const_i64(0)])
    src_key = b.load(I64, ValueOperand(src_key_addr))
    dst_key_addr = b.gep(ptr(), ValueOperand(dst_entry), [b.const_i64(0)])
    b.store(ValueOperand(src_key), ValueOperand(dst_key_addr))
    src_value_addr = b.gep(ptr(), ValueOperand(src_entry), [b.const_i64(1)])
    src_value = b.load(I64, ValueOperand(src_value_addr))
    dst_value_addr = b.gep(ptr(), ValueOperand(dst_entry), [b.const_i64(1)])
    b.store(ValueOperand(src_value), ValueOperand(dst_value_addr))
    src_occ_addr = b.gep(ptr(), ValueOperand(src_entry), [b.const_i64(2)])
    src_occ = b.load(I64, ValueOperand(src_occ_addr))
    dst_occ_addr = b.gep(ptr(), ValueOperand(dst_entry), [b.const_i64(2)])
    b.store(ValueOperand(src_occ), ValueOperand(dst_occ_addr))
    next_i = b.binop("add", ValueOperand(i2), b.const_i64(1))
    b.store(ValueOperand(next_i), ValueOperand(i_slot))
    b.br(shift_check)

    b.set_block(clear_last)
    last_entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(last_index))
    clear_key_addr = b.gep(ptr(), ValueOperand(last_entry), [b.const_i64(0)])
    b.store(b.const_i64(0), ValueOperand(clear_key_addr))
    clear_value_addr = b.gep(ptr(), ValueOperand(last_entry), [b.const_i64(1)])
    b.store(b.const_i64(0), ValueOperand(clear_value_addr))
    clear_occ_addr = b.gep(ptr(), ValueOperand(last_entry), [b.const_i64(2)])
    b.store(b.const_i64(0), ValueOperand(clear_occ_addr))
    b.store(ValueOperand(last_index), ValueOperand(len_addr))
    b.ret(ConstBoolOperand(True))

    b.set_block(no)
    b.ret(ConstBoolOperand(False))
    return b.fn


# ── Injection ─────────────────────────────────────────────────────────────


_HELPER_EMITTERS = {
    "__ep_slice_u8_from_str": lambda p: emit_slice_u8_from_str(),
    "__ep_str_from_slice_u8": lambda p: emit_str_from_slice_u8(),
    "__ep_str_cat": lambda p: emit___ep_str_cat(),
    "__ep_slice_u8_alloc": lambda p: emit_slice_u8_alloc(),
    "__ep_slice_u8_get": lambda p: emit_slice_u8_get(),
    "__ep_slice_i64_new": lambda p: emit_slice_word_new("__ep_slice_i64_new"),
    "__ep_slice_i64_get": lambda p: emit_slice_word_get("__ep_slice_i64_get", I64),
    "__ep_slice_i64_set": lambda p: emit_slice_word_set("__ep_slice_i64_set", I64),
    "__ep_slice_i64_push": lambda p: emit_slice_word_push("__ep_slice_i64_push", I64),
    "__ep_slice_ptr_new": lambda p: emit_slice_word_new("__ep_slice_ptr_new"),
    "__ep_slice_ptr_get": lambda p: emit_slice_word_get("__ep_slice_ptr_get", ptr()),
    "__ep_slice_ptr_set": lambda p: emit_slice_word_set("__ep_slice_ptr_set", ptr()),
    "__ep_slice_ptr_push": lambda p: emit_slice_word_push("__ep_slice_ptr_push", ptr()),
    "__ep_slice_u8_set": lambda p: emit_slice_u8_set(),
    "__ep_slice_u8_push": lambda p: emit_slice_u8_push(),
    "__ep_slice_u8_slice": lambda p: emit_slice_u8_slice(),
    "__ep_slice_u8_extend": lambda p: emit_extend_slice_u8(),
    "__ep_str_cmp": lambda p: emit___ep_str_cmp(),
    "__ep_map_str_find_pos": lambda p: emit_map_str_find_pos(),
    "__ep_map_str_i64_new": lambda p: emit_map_str_word_new("__ep_map_str_i64_new", ptr()),
    "__ep_map_str_i64_get": lambda p: emit_map_str_word_get("__ep_map_str_i64_get", ptr(), I64),
    "__ep_map_str_i64_set": lambda p: emit_map_str_word_set("__ep_map_str_i64_set", ptr(), I64),
    "__ep_map_str_i64_has": lambda p: emit_map_str_word_has("__ep_map_str_i64_has", ptr()),
    "__ep_map_str_i64_del": lambda p: emit_map_str_word_del("__ep_map_str_i64_del", ptr()),
    "__ep_map_str_bool_new": lambda p: emit_map_str_word_new("__ep_map_str_bool_new", ptr()),
    "__ep_map_str_bool_get": lambda p: emit_map_str_word_get("__ep_map_str_bool_get", ptr(), BOOL),
    "__ep_map_str_bool_set": lambda p: emit_map_str_word_set("__ep_map_str_bool_set", ptr(), BOOL),
    "__ep_map_str_bool_has": lambda p: emit_map_str_word_has("__ep_map_str_bool_has", ptr()),
    "__ep_map_str_bool_del": lambda p: emit_map_str_word_del("__ep_map_str_bool_del", ptr()),
    "__ep_map_str_str_new": lambda p: emit_map_str_word_new("__ep_map_str_str_new", ptr()),
    "__ep_map_str_str_get": lambda p: emit_map_str_word_get("__ep_map_str_str_get", ptr(), ptr()),
    "__ep_map_str_str_set": lambda p: emit_map_str_word_set("__ep_map_str_str_set", ptr(), ptr()),
    "__ep_map_str_str_has": lambda p: emit_map_str_word_has("__ep_map_str_str_has", ptr()),
    "__ep_map_str_str_del": lambda p: emit_map_str_word_del("__ep_map_str_str_del", ptr()),
}

_HELPER_ORDER = [
    "__ep_slice_u8_from_str",
    "__ep_str_from_slice_u8",
    "__ep_str_cat",
    "__ep_slice_u8_alloc",
    "__ep_slice_u8_get",
    "__ep_slice_i64_new",
    "__ep_slice_i64_get",
    "__ep_slice_i64_set",
    "__ep_slice_i64_push",
    "__ep_slice_ptr_new",
    "__ep_slice_ptr_get",
    "__ep_slice_ptr_set",
    "__ep_slice_ptr_push",
    "__ep_slice_u8_set",
    "__ep_slice_u8_push",
    "__ep_slice_u8_slice",
    "__ep_slice_u8_extend",
    "__ep_str_cmp",
    "__ep_map_str_find_pos",
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
    "__ep_debug_i64",
]


IMPLEMENTED_MIR_HELPERS = tuple(_HELPER_ORDER)


_RUNTIME_STRING_GLOBALS = (
    ("str.runtime.bool.true", "true"),
    ("str.runtime.bool.false", "false"),
    ("str.runtime.empty", ""),
)


_RUNTIME_MIR_BUNDLE = Path(__file__).resolve().parent.parent / "runtime" / "mir" / "helpers.mir"
_PARSED_HELPERS = None


def _parsed_runtime_helpers():
    global _PARSED_HELPERS
    if _PARSED_HELPERS is not None:
        return _PARSED_HELPERS
    if not _RUNTIME_MIR_BUNDLE.exists():
        raise RuntimeError(
            f"missing MIR runtime helper bundle: {_RUNTIME_MIR_BUNDLE}; "
            "run scripts/write_mir_runtime_bundle.py"
        )
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

