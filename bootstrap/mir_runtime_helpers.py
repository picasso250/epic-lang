"""MIR runtime helpers — MirFunction implementations for selected builtins.

Each helper is a hand-coded MirFunction that replaces an x64-backed runtime
helper.  They use existing MIR ops (call/gep/load/store/ret) and call existing
x64 primitives (notably __epx_alloc).  The codegen pipeline injects all
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
    MirGlobal,
    MirInst,
    MirParam,
    MirProgram,
    MirValue,
    Ret,
    SymbolOperand,
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

    def const_i8(self, n):
        return ConstIntOperand(I8, n)

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


def emit_bytes_slice_u8() -> MirFunction:
    """Identity cast: str and _slice_u8 now have identical layout {data, len, cap}.

    fn __ep_slice_u8_from_str(%s: ptr<str>) -> ptr<_slice_u8> {
        entry:
            ret %s   ; reinterpret same pointer as ptr<_slice_u8>
        }
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_from_str",
        [MirParam("%s", ptr(mir_struct("str")))],
        ptr(mir_struct("_slice_u8")),
    )
    b.ret(ValueOperand(b.fn.params[0].value))
    return b.fn


def emit_str_slice_u8() -> MirFunction:
    """Identity: returns the input ptr<_slice_u8> as ptr<str>.

    x64: mov rax, rcx; ret
    """
    b = MirHelperBuilder(
        "__ep_str_from_slice_u8",
        [MirParam("%input", ptr(mir_struct("_slice_u8")))],
        ptr(mir_struct("str")),
    )
    b.ret(ValueOperand(b.fn.params[0].value))
    return b.fn


def emit_str_bool() -> MirFunction:
    """Return the static runtime string for a bool value.

    fn __ep_str_from_bool(bool %value) -> ptr<str>
    """
    b = MirHelperBuilder(
        "__ep_str_from_bool",
        [MirParam("%value", BOOL)],
        ptr(mir_struct("str")),
    )
    value = ValueOperand(b.fn.params[0].value)
    true_block = b.new_block("true")
    false_block = b.new_block("false")
    b.entry.terminator = CondBr(value, true_block.name, false_block.name)

    b.entry = true_block
    b.ret(SymbolOperand(ptr(mir_struct("str")), "@str.runtime.bool.true"))

    b.entry = false_block
    b.ret(SymbolOperand(ptr(mir_struct("str")), "@str.runtime.bool.false"))

    return b.fn


def emit___ep_str_eq() -> MirFunction:
    """Compare two strings for byte-for-byte equality.

    fn __ep_str_eq(ptr<str> %left, ptr<str> %right) -> bool
    """
    b = MirHelperBuilder(
        "__ep_str_eq",
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


def emit___ep_str_cat() -> MirFunction:
    """Concatenate two strings into a newly allocated str.

    fn __ep_str_cat(ptr<str> %left, ptr<str> %right) -> ptr<str>
    """
    b = MirHelperBuilder(
        "__ep_str_cat",
        [
            MirParam("%left", ptr(mir_struct("str"))),
            MirParam("%right", ptr(mir_struct("str"))),
        ],
        ptr(mir_struct("str")),
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

    b.entry = left_check
    i = b.load(I64, ValueOperand(i_slot))
    keep_left = b.icmp("lt", i, left_len)
    b.entry.terminator = CondBr(ValueOperand(keep_left), left_body.name, right_init.name)

    b.entry = left_body
    src_addr = b.gep(I8, left_data, [i])
    byte = b.load(I8, src_addr, result_type=I8)
    dst_addr = b.gep(I8, ValueOperand(result_data), [i])
    b.store(ValueOperand(byte), dst_addr)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(left_check)

    b.entry = right_init
    b.store(b.const_i64(0), ValueOperand(i_slot))
    b.br(right_check)

    b.entry = right_check
    i = b.load(I64, ValueOperand(i_slot))
    keep_right = b.icmp("lt", i, right_len)
    b.entry.terminator = CondBr(ValueOperand(keep_right), right_body.name, done.name)

    b.entry = right_body
    src_addr = b.gep(I8, right_data, [i])
    byte = b.load(I8, src_addr, result_type=I8)
    dst_index = b.binop("add", left_len, i)
    dst_addr = b.gep(I8, ValueOperand(result_data), [dst_index])
    b.store(ValueOperand(byte), dst_addr)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(right_check)

    b.entry = done
    nul_addr = b.gep(I8, ValueOperand(result_data), [result_len])
    b.store(b.const_i8(0), nul_addr)
    b.ret(ValueOperand(result_str))

    return b.fn


def emit___ep_str_slice() -> MirFunction:
    """Copy a half-open string slice [start:end].

    fn __ep_str_slice(ptr<str> %s, i64 %start, i64 %end) -> ptr<str>

    Bounds failures exit with code 1, matching migrated string/array helpers.
    """
    b = MirHelperBuilder(
        "__ep_str_slice",
        [
            MirParam("%s", ptr(mir_struct("str"))),
            MirParam("%start", I64),
            MirParam("%end", I64),
        ],
        ptr(mir_struct("str")),
    )
    s_val = ValueOperand(b.fn.params[0].value)
    start_val = ValueOperand(b.fn.params[1].value)
    end_val = ValueOperand(b.fn.params[2].value)

    s_len = b.load(I64, b.gep_field(s_val, "str", 1))

    start_ok = b.icmp("ge", start_val, b.const_i64(0))
    check_order = b.new_block("check_order")
    check_len = b.new_block("check_len")
    alloc_block = b.new_block("alloc")
    copy_check = b.new_block("copy_check")
    copy_body = b.new_block("copy_body")
    done = b.new_block("done")
    fail = b.new_block("fail")
    b.entry.terminator = CondBr(ValueOperand(start_ok), check_order.name, fail.name)

    b.entry = check_order
    order_ok = b.icmp("ge", end_val, start_val)
    b.entry.terminator = CondBr(ValueOperand(order_ok), check_len.name, fail.name)

    b.entry = check_len
    len_ok = b.icmp("ge", s_len, end_val)
    b.entry.terminator = CondBr(ValueOperand(len_ok), alloc_block.name, fail.name)

    b.entry = alloc_block
    slice_len = b.binop("sub", end_val, start_val)
    result_str = b.call("__epx_alloc", [b.const_i64(24)], ptr())
    data_len = b.binop("add", slice_len, b.const_i64(1))
    result_data = b.call("__epx_alloc", [data_len], ptr())
    b.store(result_data, b.gep_field(ValueOperand(result_str), "str", 0))
    b.store(slice_len, b.gep_field(ValueOperand(result_str), "str", 1))
    b.store(slice_len, b.gep_field(ValueOperand(result_str), "str", 2))
    src_data = b.load(ptr(), b.gep_field(s_val, "str", 0))
    src_start = b.gep(I8, src_data, [start_val])
    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    b.br(copy_check)

    b.entry = copy_check
    i = b.load(I64, ValueOperand(i_slot))
    keep_copying = b.icmp("lt", i, slice_len)
    b.entry.terminator = CondBr(ValueOperand(keep_copying), copy_body.name, done.name)

    b.entry = copy_body
    src_addr = b.gep(I8, src_start, [i])
    byte = b.load(I8, src_addr, result_type=I8)
    dst_addr = b.gep(I8, ValueOperand(result_data), [i])
    b.store(ValueOperand(byte), dst_addr)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(copy_check)

    b.entry = done
    nul_addr = b.gep(I8, ValueOperand(result_data), [slice_len])
    b.store(b.const_i8(0), nul_addr)
    b.ret(ValueOperand(result_str))

    b.entry = fail
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret(ConstNullOperand())

    return b.fn


def emit___ep_str_starts_with() -> MirFunction:
    """Return 1 if s starts with prefix, otherwise 0.

    fn __ep_str_starts_with(ptr<str> %s, ptr<str> %prefix) -> i64
    """
    b = MirHelperBuilder(
        "__ep_str_starts_with",
        [
            MirParam("%s", ptr(mir_struct("str"))),
            MirParam("%prefix", ptr(mir_struct("str"))),
        ],
        I64,
    )
    s_val = ValueOperand(b.fn.params[0].value)
    prefix_val = ValueOperand(b.fn.params[1].value)

    s_len = b.load(I64, b.gep_field(s_val, "str", 1))
    prefix_len = b.load(I64, b.gep_field(prefix_val, "str", 1))
    long_enough = b.icmp("ge", s_len, prefix_len)
    loop_init = b.new_block("loop_init")
    false_block = b.new_block("false")
    b.entry.terminator = CondBr(ValueOperand(long_enough), loop_init.name, false_block.name)

    b.entry = loop_init
    s_data = b.load(ptr(), b.gep_field(s_val, "str", 0))
    prefix_data = b.load(ptr(), b.gep_field(prefix_val, "str", 0))
    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    loop_check = b.new_block("loop_check")
    b.br(loop_check)

    b.entry = loop_check
    i = b.load(I64, ValueOperand(i_slot))
    keep_checking = b.icmp("lt", i, prefix_len)
    loop_body = b.new_block("loop_body")
    true_block = b.new_block("true")
    b.entry.terminator = CondBr(ValueOperand(keep_checking), loop_body.name, true_block.name)

    b.entry = loop_body
    s_byte_addr = b.gep(I8, s_data, [i])
    s_byte = b.load(I8, s_byte_addr, result_type=I8)
    prefix_byte_addr = b.gep(I8, prefix_data, [i])
    prefix_byte = b.load(I8, prefix_byte_addr, result_type=I8)
    bytes_eq = b.icmp("eq", s_byte, prefix_byte)
    loop_next = b.new_block("loop_next")
    b.entry.terminator = CondBr(ValueOperand(bytes_eq), loop_next.name, false_block.name)

    b.entry = loop_next
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(loop_check)

    b.entry = true_block
    b.ret(b.const_i64(1))

    b.entry = false_block
    b.ret(b.const_i64(0))

    return b.fn


def emit___ep_str_get() -> MirFunction:
    """Bounds-checked byte read from str.

    fn __ep_str_get(ptr<str> %s, i64 %idx) -> i64
    """
    b = MirHelperBuilder(
        "__ep_str_get",
        [MirParam("%s", ptr(mir_struct("str"))), MirParam("%idx", I64)],
        I64,
    )
    s_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)

    s_len = b.load(I64, b.gep_field(s_val, "str", 1))

    ge_zero = b.icmp("ge", idx_val, b.const_i64(0))
    check_block = b.new_block("check_high")
    ok_block = b.new_block("ok")
    fail_block = b.new_block("fail")
    b.entry.terminator = CondBr(ValueOperand(ge_zero), check_block.name, fail_block.name)

    b.entry = check_block
    lt_len = b.icmp("lt", idx_val, s_len)
    b.entry.terminator = CondBr(ValueOperand(lt_len), ok_block.name, fail_block.name)

    b.entry = ok_block
    data = b.load(ptr(), b.gep_field(s_val, "str", 0))
    byte_addr = b.gep(I8, data, [idx_val])
    result = b.load(I8, byte_addr, result_type=I64)
    b.ret(ValueOperand(result))

    b.entry = fail_block
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret(b.const_i64(0))  # dummy, unreachable

    return b.fn


def emit___ep_str_find() -> MirFunction:
    """Find the first occurrence of needle in s.

    Empty needle returns 0. Missing needle returns -1.

    fn __ep_str_find(ptr<str> %s, ptr<str> %needle) -> i64
    """
    b = MirHelperBuilder(
        "__ep_str_find",
        [
            MirParam("%s", ptr(mir_struct("str"))),
            MirParam("%needle", ptr(mir_struct("str"))),
        ],
        I64,
    )
    s_val = ValueOperand(b.fn.params[0].value)
    needle_val = ValueOperand(b.fn.params[1].value)

    s_len = b.load(I64, b.gep_field(s_val, "str", 1))
    needle_len = b.load(I64, b.gep_field(needle_val, "str", 1))
    empty_needle = b.icmp("eq", needle_len, b.const_i64(0))
    empty_block = b.new_block("empty")
    nonempty_block = b.new_block("nonempty")
    absent_block = b.new_block("absent")
    b.entry.terminator = CondBr(
        ValueOperand(empty_needle), empty_block.name, nonempty_block.name
    )

    b.entry = empty_block
    b.ret(b.const_i64(0))

    b.entry = nonempty_block
    long_enough = b.icmp("ge", s_len, needle_len)
    init_block = b.new_block("init")
    b.entry.terminator = CondBr(ValueOperand(long_enough), init_block.name, absent_block.name)

    b.entry = init_block
    s_data = b.load(ptr(), b.gep_field(s_val, "str", 0))
    needle_data = b.load(ptr(), b.gep_field(needle_val, "str", 0))
    last_start = b.binop("sub", s_len, needle_len)
    i_slot = b.alloca(I64)
    j_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    outer_check = b.new_block("outer_check")
    b.br(outer_check)

    b.entry = outer_check
    i = b.load(I64, ValueOperand(i_slot))
    in_outer_range = b.icmp("le", i, last_start)
    inner_init = b.new_block("inner_init")
    b.entry.terminator = CondBr(
        ValueOperand(in_outer_range), inner_init.name, absent_block.name
    )

    b.entry = inner_init
    b.store(b.const_i64(0), ValueOperand(j_slot))
    inner_check = b.new_block("inner_check")
    b.br(inner_check)

    b.entry = inner_check
    j = b.load(I64, ValueOperand(j_slot))
    matched_all = b.icmp("ge", j, needle_len)
    found_block = b.new_block("found")
    compare_block = b.new_block("compare")
    b.entry.terminator = CondBr(
        ValueOperand(matched_all), found_block.name, compare_block.name
    )

    b.entry = compare_block
    src_idx = b.binop("add", i, j)
    s_byte_addr = b.gep(I8, s_data, [src_idx])
    s_byte = b.load(I8, s_byte_addr, result_type=I8)
    needle_byte_addr = b.gep(I8, needle_data, [j])
    needle_byte = b.load(I8, needle_byte_addr, result_type=I8)
    bytes_eq = b.icmp("eq", s_byte, needle_byte)
    inner_next = b.new_block("inner_next")
    outer_next = b.new_block("outer_next")
    b.entry.terminator = CondBr(ValueOperand(bytes_eq), inner_next.name, outer_next.name)

    b.entry = inner_next
    next_j = b.binop("add", j, b.const_i64(1))
    b.store(next_j, ValueOperand(j_slot))
    b.br(inner_check)

    b.entry = outer_next
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(outer_check)

    b.entry = found_block
    b.ret(ValueOperand(i))

    b.entry = absent_block
    b.ret(b.const_i64(-1))

    return b.fn


def emit_slice_u8_alloc() -> MirFunction:
    """Allocate header + data for u8[], with separate len and cap.

    fn __ep_slice_u8_alloc(i64 %len, i64 %cap) -> ptr<_slice_u8>
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_alloc",
        [MirParam("%len", I64), MirParam("%cap", I64)],
        ptr(mir_struct("_slice_u8")),
    )
    len_val = ValueOperand(b.fn.params[0].value)
    cap_val = ValueOperand(b.fn.params[1].value)

    header_raw = b.call("__epx_alloc", [b.const_i64(24)], ptr())
    cap_zero = b.icmp("eq", cap_val, b.const_i64(0))
    zero_block = b.new_block("data_zero")
    alloc_block = b.new_block("data_alloc")
    init_block = b.new_block("init")
    b.entry.terminator = CondBr(ValueOperand(cap_zero), zero_block.name, alloc_block.name)

    b.entry = zero_block
    b.store(ConstNullOperand(), b.gep_field(ValueOperand(header_raw), "_slice_u8", 0))
    b.entry.terminator = Br(init_block.name)

    b.entry = alloc_block
    data_raw = b.call("__epx_alloc", [cap_val], ptr())
    b.store(data_raw, b.gep_field(ValueOperand(header_raw), "_slice_u8", 0))
    b.entry.terminator = Br(init_block.name)

    b.entry = init_block
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
        [MirParam("%arr", ptr(mir_struct("_slice_u8"))), MirParam("%idx", I64)],
        I64,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)

    # Load arr.len
    len_addr = b.gep_field(arr_val, "_slice_u8", 1)
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
    data_addr = b.gep_field(arr_val, "_slice_u8", 0)
    data = b.load(ptr(), data_addr)
    byte_addr = b.gep(I8, data, [idx_val])
    result = b.load(I8, byte_addr, result_type=I64)
    b.ret(ValueOperand(result))

    # fail: exit(1)
    b.entry = fail_block
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret(b.const_i64(0))  # dummy, unreachable

    return b.fn


def emit_slice_word_new(name: str) -> MirFunction:
    """Allocate a word-sized slice header.

    fn {name}(i64 %cap) -> ptr
    """
    b = MirHelperBuilder(
        name,
        [MirParam("%cap", I64)],
        ptr(),
    )
    cap_val = ValueOperand(b.fn.params[0].value)

    header_raw = b.call("__epx_alloc", [b.const_i64(24)], ptr())
    cap_zero = b.icmp("eq", cap_val, b.const_i64(0))
    zero_block = b.new_block("data_zero")
    alloc_block = b.new_block("data_alloc")
    init_block = b.new_block("init")
    b.entry.terminator = CondBr(ValueOperand(cap_zero), zero_block.name, alloc_block.name)

    b.entry = zero_block
    b.store(ConstNullOperand(), b.gep(ptr(), ValueOperand(header_raw), [b.const_i64(0)]))
    b.br(init_block)

    b.entry = alloc_block
    bytes_len = b.binop("add", cap_val, cap_val)
    bytes_len = b.binop("add", ValueOperand(bytes_len), ValueOperand(bytes_len))
    bytes_len = b.binop("add", ValueOperand(bytes_len), ValueOperand(bytes_len))
    data_raw = b.call("__epx_alloc", [ValueOperand(bytes_len)], ptr())
    b.store(data_raw, b.gep(ptr(), ValueOperand(header_raw), [b.const_i64(0)]))
    b.br(init_block)

    b.entry = init_block
    b.store(b.const_i64(0), b.gep(ptr(), ValueOperand(header_raw), [b.const_i64(1)]))
    b.store(cap_val, b.gep(ptr(), ValueOperand(header_raw), [b.const_i64(2)]))
    b.ret(ValueOperand(header_raw))

    return b.fn


def emit_slice_word_get(name: str, elem_type) -> MirFunction:
    """Bounds-checked read from a word-sized slice."""
    b = MirHelperBuilder(
        name,
        [MirParam("%arr", ptr()), MirParam("%idx", I64)],
        elem_type,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)

    len_addr = b.gep(ptr(), arr_val, [b.const_i64(1)])
    arr_len = b.load(I64, len_addr)

    ge_zero = b.icmp("ge", idx_val, b.const_i64(0))
    check_block = b.new_block("check_high")
    ok_block = b.new_block("ok")
    fail_block = b.new_block("fail")
    b.entry.terminator = CondBr(ValueOperand(ge_zero), check_block.name, fail_block.name)

    b.entry = check_block
    lt_len = b.icmp("lt", idx_val, arr_len)
    b.entry.terminator = CondBr(ValueOperand(lt_len), ok_block.name, fail_block.name)

    b.entry = ok_block
    data_addr = b.gep(ptr(), arr_val, [b.const_i64(0)])
    data = b.load(ptr(), data_addr)
    elem_addr = b.gep(ptr(), data, [idx_val])
    result = b.load(elem_type, elem_addr)
    b.ret(ValueOperand(result))

    b.entry = fail_block
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
            MirParam("%arr", ptr()),
            MirParam("%idx", I64),
            MirParam("%val", elem_type),
        ],
        VOID,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    idx_val = ValueOperand(b.fn.params[1].value)
    val_val = ValueOperand(b.fn.params[2].value)

    len_addr = b.gep(ptr(), arr_val, [b.const_i64(1)])
    arr_len = b.load(I64, len_addr)

    ge_zero = b.icmp("ge", idx_val, b.const_i64(0))
    check_block = b.new_block("check_high")
    ok_block = b.new_block("ok")
    fail_block = b.new_block("fail")
    b.entry.terminator = CondBr(ValueOperand(ge_zero), check_block.name, fail_block.name)

    b.entry = check_block
    lt_len = b.icmp("lt", idx_val, arr_len)
    b.entry.terminator = CondBr(ValueOperand(lt_len), ok_block.name, fail_block.name)

    b.entry = ok_block
    data_addr = b.gep(ptr(), arr_val, [b.const_i64(0)])
    data = b.load(ptr(), data_addr)
    elem_addr = b.gep(ptr(), data, [idx_val])
    b.store(val_val, elem_addr)
    b.ret()

    b.entry = fail_block
    b.call("ExitProcess", [b.const_i64(1)], VOID)
    b.ret()

    return b.fn


def emit_slice_word_push(name: str, elem_type) -> MirFunction:
    """Push one word-sized element, growing from zero capacity to four."""
    b = MirHelperBuilder(
        name,
        [
            MirParam("%arr", ptr()),
            MirParam("%val", elem_type),
        ],
        VOID,
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    val_val = ValueOperand(b.fn.params[1].value)

    len_addr = b.gep(ptr(), arr_val, [b.const_i64(1)])
    old_len = b.load(I64, len_addr)
    cap_addr = b.gep(ptr(), arr_val, [b.const_i64(2)])
    old_cap = b.load(I64, cap_addr)

    need_grow = b.icmp("ge", old_len, old_cap)
    grow_block = b.new_block("grow")
    store_block = b.new_block("store")
    b.entry.terminator = CondBr(ValueOperand(need_grow), grow_block.name, store_block.name)

    b.entry = grow_block
    new_cap_slot = b.alloca(I64)
    new_data_slot = b.alloca(ptr())
    i_slot = b.alloca(I64)

    cap_zero = b.icmp("eq", old_cap, b.const_i64(0))
    zero_block = b.new_block("grow_zero")
    double_block = b.new_block("grow_double")
    b.entry.terminator = CondBr(ValueOperand(cap_zero), zero_block.name, double_block.name)

    b.entry = zero_block
    nc0 = b.const_i64(4)
    b.store(nc0, ValueOperand(new_cap_slot))
    bytes0 = b.const_i64(32)
    nd0 = b.call("__epx_alloc", [bytes0], ptr())
    b.store(nd0, ValueOperand(new_data_slot))
    copy_entry = b.new_block("copy_entry")
    b.br(copy_entry)

    b.entry = double_block
    nc1 = b.binop("add", old_cap, old_cap)
    b.store(nc1, ValueOperand(new_cap_slot))
    bytes1 = b.binop("add", ValueOperand(nc1), ValueOperand(nc1))
    bytes1 = b.binop("add", ValueOperand(bytes1), ValueOperand(bytes1))
    bytes1 = b.binop("add", ValueOperand(bytes1), ValueOperand(bytes1))
    nd1 = b.call("__epx_alloc", [ValueOperand(bytes1)], ptr())
    b.store(nd1, ValueOperand(new_data_slot))
    b.br(copy_entry)

    b.entry = copy_entry
    old_data = b.load(ptr(), b.gep(ptr(), arr_val, [b.const_i64(0)]))
    new_data = b.load(ptr(), ValueOperand(new_data_slot))
    b.store(b.const_i64(0), ValueOperand(i_slot))
    copy_check = b.new_block("copy_check")
    b.br(copy_check)

    b.entry = copy_check
    i = b.load(I64, ValueOperand(i_slot))
    cond = b.icmp("lt", i, old_len)
    copy_body = b.new_block("copy_body")
    swap_block = b.new_block("swap")
    b.entry.terminator = CondBr(ValueOperand(cond), copy_body.name, swap_block.name)

    b.entry = copy_body
    old_elem_addr = b.gep(ptr(), old_data, [i])
    old_elem = b.load(elem_type, old_elem_addr)
    new_elem_addr = b.gep(ptr(), new_data, [i])
    b.store(ValueOperand(old_elem), new_elem_addr)
    i_next = b.binop("add", i, b.const_i64(1))
    b.store(i_next, ValueOperand(i_slot))
    b.br(copy_check)

    b.entry = swap_block
    b.store(new_data, b.gep(ptr(), arr_val, [b.const_i64(0)]))
    final_cap = b.load(I64, ValueOperand(new_cap_slot))
    b.store(final_cap, cap_addr)
    b.br(store_block)

    b.entry = store_block
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
            MirParam("%arr", ptr(mir_struct("_slice_u8"))),
            MirParam("%idx", I64),
            MirParam("%val", I64),
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

    data_addr = b.gep_field(arr_val, "_slice_u8", 0)
    data = b.load(ptr(), data_addr)
    byte_addr = b.gep(I8, data, [idx_val])
    b.store(ValueOperand(byte_val), byte_addr)
    b.ret()

    # fail: exit(1)
    b.entry = fail_block
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
            MirParam("%arr", ptr(mir_struct("_slice_u8"))),
            MirParam("%val", I64),
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

    # grow_zero: new_cap = 4
    b.entry = zero_block
    nc0 = b.const_i64(4)
    b.store(nc0, ValueOperand(new_cap_slot))
    nd0 = b.call("__epx_alloc", [nc0], ptr())
    b.store(nd0, ValueOperand(new_data_slot))
    copy_entry = b.new_block("copy_entry")
    b.entry.terminator = CondBr(ValueOperand(cap_zero), copy_entry.name, copy_entry.name)

    # grow_double: new_cap = old_cap * 2
    b.entry = double_block
    nc1 = b.binop("add", old_cap, old_cap)
    b.store(nc1, ValueOperand(new_cap_slot))
    nd1 = b.call("__epx_alloc", [nc1], ptr())
    b.store(nd1, ValueOperand(new_data_slot))
    b.entry.terminator = CondBr(ValueOperand(cap_zero), copy_entry.name, copy_entry.name)

    # copy_entry: load data pointer, init copy loop
    b.entry = copy_entry
    old_data = b.load(ptr(), b.gep_field(arr_val, "_slice_u8", 0))
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
    b.store(new_data, b.gep_field(arr_val, "_slice_u8", 0))
    final_cap = b.load(I64, ValueOperand(new_cap_slot))
    b.store(final_cap, b.gep_field(arr_val, "_slice_u8", 2))
    b.entry.terminator = CondBr(ValueOperand(cap_zero), store_block.name, store_block.name)

    # store: write byte and update len
    b.entry = store_block
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
            MirParam("%arr", ptr(mir_struct("_slice_u8"))),
            MirParam("%start", I64),
            MirParam("%end", I64),
        ],
        ptr(mir_struct("_slice_u8")),
    )
    arr_val = ValueOperand(b.fn.params[0].value)
    start_val = ValueOperand(b.fn.params[1].value)
    end_val = ValueOperand(b.fn.params[2].value)

    arr_len = b.load(I64, b.gep_field(arr_val, "_slice_u8", 1))

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
    result_arr = b.call("__ep_slice_u8_alloc", [slice_len, slice_len], ptr(mir_struct("_slice_u8")))
    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    src_data = b.load(ptr(), b.gep_field(arr_val, "_slice_u8", 0))
    src_start = b.gep(I8, src_data, [start_val])
    dst_data = b.load(ptr(), b.gep_field(ValueOperand(result_arr), "_slice_u8", 0))
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


def emit_extend_slice_u8() -> MirFunction:
    """Append src bytes into dst, snapshotting src.len before the loop.

    fn __ep_slice_u8_extend(ptr<_slice_u8> %dst, ptr<_slice_u8> %src) -> void
    """
    b = MirHelperBuilder(
        "__ep_slice_u8_extend",
        [
            MirParam("%dst", ptr(mir_struct("_slice_u8"))),
            MirParam("%src", ptr(mir_struct("_slice_u8"))),
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

    b.entry = loop_check
    i = b.load(I64, ValueOperand(i_slot))
    keep_copying = b.icmp("lt", i, src_len)
    b.entry.terminator = CondBr(ValueOperand(keep_copying), loop_body.name, done.name)

    b.entry = loop_body
    byte = b.call("__ep_slice_u8_get", [src_val, i], I64)
    b.call("__ep_slice_u8_push", [dst_val, ValueOperand(byte)], VOID)
    next_i = b.binop("add", i, b.const_i64(1))
    b.store(next_i, ValueOperand(i_slot))
    b.br(loop_check)

    b.entry = done
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
        return ConstNullOperand()
    if value_type == BOOL:
        return ConstBoolOperand(False)
    return ConstIntOperand(value_type, 0)


def emit_map_str_word_get(name: str, map_type, value_type) -> MirFunction:
    """Lookup a str key in a word-valued map, returning value zero on miss."""
    b = MirHelperBuilder(
        name,
        [MirParam("%map", map_type), MirParam("%key", ptr(mir_struct("str")))],
        value_type,
    )
    map_val = ValueOperand(b.fn.params[0].value)
    key_val = ValueOperand(b.fn.params[1].value)

    len_addr = b.gep(ptr(), map_val, [b.const_i64(1)])
    map_len = b.load(I64, len_addr)
    data_addr = b.gep(ptr(), map_val, [b.const_i64(0)])
    data = b.load(ptr(), data_addr)

    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    loop_check = b.new_block("loop_check")
    loop_body = b.new_block("loop_body")
    key_check = b.new_block("key_check")
    found = b.new_block("found")
    next_block = b.new_block("next")
    miss = b.new_block("miss")
    b.br(loop_check)

    b.entry = loop_check
    i = b.load(I64, ValueOperand(i_slot))
    in_range = b.icmp("lt", ValueOperand(i), ValueOperand(map_len))
    b.entry.terminator = CondBr(ValueOperand(in_range), loop_body.name, miss.name)

    b.entry = loop_body
    entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(i))
    occ_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(2)])
    occ = b.load(I64, ValueOperand(occ_addr))
    occupied = b.icmp("ne", ValueOperand(occ), b.const_i64(0))
    b.entry.terminator = CondBr(ValueOperand(occupied), key_check.name, next_block.name)

    b.entry = key_check
    key_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(0)])
    entry_key = b.load(ptr(mir_struct("str")), ValueOperand(key_addr))
    keys_equal = b.call("__ep_str_eq", [ValueOperand(entry_key), key_val], BOOL)
    b.entry.terminator = CondBr(ValueOperand(keys_equal), found.name, next_block.name)

    b.entry = found
    value_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(1)])
    result = b.load(value_type, ValueOperand(value_addr))
    b.ret(ValueOperand(result))

    b.entry = next_block
    next_i = b.binop("add", ValueOperand(i), b.const_i64(1))
    b.store(ValueOperand(next_i), ValueOperand(i_slot))
    b.br(loop_check)

    b.entry = miss
    b.ret(_map_zero_operand(value_type))
    return b.fn


def emit_map_str_word_has(name: str, map_type) -> MirFunction:
    """Return true when a key exists in a str-keyed map."""
    b = MirHelperBuilder(
        name,
        [MirParam("%map", map_type), MirParam("%key", ptr(mir_struct("str")))],
        BOOL,
    )
    map_val = ValueOperand(b.fn.params[0].value)
    key_val = ValueOperand(b.fn.params[1].value)

    len_addr = b.gep(ptr(), map_val, [b.const_i64(1)])
    map_len = b.load(I64, len_addr)
    data_addr = b.gep(ptr(), map_val, [b.const_i64(0)])
    data = b.load(ptr(), data_addr)

    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    loop_check = b.new_block("loop_check")
    loop_body = b.new_block("loop_body")
    key_check = b.new_block("key_check")
    yes = b.new_block("yes")
    next_block = b.new_block("next")
    no = b.new_block("no")
    b.br(loop_check)

    b.entry = loop_check
    i = b.load(I64, ValueOperand(i_slot))
    in_range = b.icmp("lt", ValueOperand(i), ValueOperand(map_len))
    b.entry.terminator = CondBr(ValueOperand(in_range), loop_body.name, no.name)

    b.entry = loop_body
    entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(i))
    occ_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(2)])
    occ = b.load(I64, ValueOperand(occ_addr))
    occupied = b.icmp("ne", ValueOperand(occ), b.const_i64(0))
    b.entry.terminator = CondBr(ValueOperand(occupied), key_check.name, next_block.name)

    b.entry = key_check
    key_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(0)])
    entry_key = b.load(ptr(mir_struct("str")), ValueOperand(key_addr))
    keys_equal = b.call("__ep_str_eq", [ValueOperand(entry_key), key_val], BOOL)
    b.entry.terminator = CondBr(ValueOperand(keys_equal), yes.name, next_block.name)

    b.entry = yes
    b.ret(ConstBoolOperand(True))

    b.entry = next_block
    next_i = b.binop("add", ValueOperand(i), b.const_i64(1))
    b.store(ValueOperand(next_i), ValueOperand(i_slot))
    b.br(loop_check)

    b.entry = no
    b.ret(ConstBoolOperand(False))
    return b.fn


def emit_map_str_word_set(name: str, map_type, value_type) -> MirFunction:
    """Insert or update a key/value entry in a str-keyed word map."""
    b = MirHelperBuilder(
        name,
        [
            MirParam("%map", map_type),
            MirParam("%key", ptr(mir_struct("str"))),
            MirParam("%val", value_type),
        ],
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

    i_slot = b.alloca(I64)
    b.store(b.const_i64(0), ValueOperand(i_slot))
    loop_check = b.new_block("loop_check")
    loop_body = b.new_block("loop_body")
    key_check = b.new_block("key_check")
    update = b.new_block("update")
    next_block = b.new_block("next")
    grow_check = b.new_block("grow_check")
    grow = b.new_block("grow")
    grow_zero = b.new_block("grow_zero")
    grow_double = b.new_block("grow_double")
    copy_init = b.new_block("copy_init")
    copy_check = b.new_block("copy_check")
    copy_body = b.new_block("copy_body")
    swap = b.new_block("swap")
    insert = b.new_block("insert")
    b.br(loop_check)

    b.entry = loop_check
    i = b.load(I64, ValueOperand(i_slot))
    in_range = b.icmp("lt", ValueOperand(i), ValueOperand(old_len))
    b.entry.terminator = CondBr(ValueOperand(in_range), loop_body.name, grow_check.name)

    b.entry = loop_body
    entry = _map_entry_addr(b, ValueOperand(old_data), ValueOperand(i))
    occ_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(2)])
    occ = b.load(I64, ValueOperand(occ_addr))
    occupied = b.icmp("ne", ValueOperand(occ), b.const_i64(0))
    b.entry.terminator = CondBr(ValueOperand(occupied), key_check.name, next_block.name)

    b.entry = key_check
    key_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(0)])
    entry_key = b.load(ptr(mir_struct("str")), ValueOperand(key_addr))
    keys_equal = b.call("__ep_str_eq", [ValueOperand(entry_key), key_val], BOOL)
    b.entry.terminator = CondBr(ValueOperand(keys_equal), update.name, next_block.name)

    b.entry = update
    update_value_addr = b.gep(ptr(), ValueOperand(entry), [b.const_i64(1)])
    b.store(val_val, ValueOperand(update_value_addr))
    b.ret()

    b.entry = next_block
    next_i = b.binop("add", ValueOperand(i), b.const_i64(1))
    b.store(ValueOperand(next_i), ValueOperand(i_slot))
    b.br(loop_check)

    b.entry = grow_check
    need_grow = b.icmp("ge", ValueOperand(old_len), ValueOperand(old_cap))
    b.entry.terminator = CondBr(ValueOperand(need_grow), grow.name, insert.name)

    b.entry = grow
    new_cap_slot = b.alloca(I64)
    new_data_slot = b.alloca(ptr())
    copy_i_slot = b.alloca(I64)
    cap_zero = b.icmp("eq", ValueOperand(old_cap), b.const_i64(0))
    b.entry.terminator = CondBr(ValueOperand(cap_zero), grow_zero.name, grow_double.name)

    b.entry = grow_zero
    b.store(b.const_i64(4), ValueOperand(new_cap_slot))
    b.br(copy_init)

    b.entry = grow_double
    doubled = b.binop("add", ValueOperand(old_cap), ValueOperand(old_cap))
    b.store(ValueOperand(doubled), ValueOperand(new_cap_slot))
    b.br(copy_init)

    b.entry = copy_init
    new_cap = b.load(I64, ValueOperand(new_cap_slot))
    bytes_count = b.binop("mul", ValueOperand(new_cap), b.const_i64(24))
    new_data = b.call("__epx_alloc", [ValueOperand(bytes_count)], ptr())
    b.store(ValueOperand(new_data), ValueOperand(new_data_slot))
    b.store(b.const_i64(0), ValueOperand(copy_i_slot))
    b.br(copy_check)

    b.entry = copy_check
    copy_i = b.load(I64, ValueOperand(copy_i_slot))
    total_words = b.binop("mul", ValueOperand(old_len), b.const_i64(3))
    keep_copying = b.icmp("lt", ValueOperand(copy_i), ValueOperand(total_words))
    b.entry.terminator = CondBr(ValueOperand(keep_copying), copy_body.name, swap.name)

    b.entry = copy_body
    old_word_addr = b.gep(ptr(), ValueOperand(old_data), [ValueOperand(copy_i)])
    old_word = b.load(I64, ValueOperand(old_word_addr))
    new_data_for_copy = b.load(ptr(), ValueOperand(new_data_slot))
    new_word_addr = b.gep(ptr(), ValueOperand(new_data_for_copy), [ValueOperand(copy_i)])
    b.store(ValueOperand(old_word), ValueOperand(new_word_addr))
    copy_next = b.binop("add", ValueOperand(copy_i), b.const_i64(1))
    b.store(ValueOperand(copy_next), ValueOperand(copy_i_slot))
    b.br(copy_check)

    b.entry = swap
    final_data = b.load(ptr(), ValueOperand(new_data_slot))
    b.store(ValueOperand(final_data), ValueOperand(data_addr))
    final_cap = b.load(I64, ValueOperand(new_cap_slot))
    b.store(ValueOperand(final_cap), ValueOperand(cap_addr))
    b.br(insert)

    b.entry = insert
    data = b.load(ptr(), ValueOperand(data_addr))
    new_entry = _map_entry_addr(b, ValueOperand(data), ValueOperand(old_len))
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


# ── Injection ─────────────────────────────────────────────────────────────


_HELPER_EMITTERS = {
    "__ep_slice_u8_from_str": lambda p: emit_bytes_slice_u8(),
    "__ep_str_from_slice_u8": lambda p: emit_str_slice_u8(),
    "__ep_str_from_bool": lambda p: emit_str_bool(),
    "__ep_str_eq": lambda p: emit___ep_str_eq(),
    "__ep_str_cat": lambda p: emit___ep_str_cat(),
    "__ep_str_slice": lambda p: emit___ep_str_slice(),
    "__ep_str_starts_with": lambda p: emit___ep_str_starts_with(),
    "__ep_str_get": lambda p: emit___ep_str_get(),
    "__ep_str_find": lambda p: emit___ep_str_find(),
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
    "__ep_map_str_i64_new": lambda p: emit_map_str_word_new("__ep_map_str_i64_new", ptr(mir_struct("_map_str_i64"))),
    "__ep_map_str_i64_get": lambda p: emit_map_str_word_get("__ep_map_str_i64_get", ptr(mir_struct("_map_str_i64")), I64),
    "__ep_map_str_i64_set": lambda p: emit_map_str_word_set("__ep_map_str_i64_set", ptr(mir_struct("_map_str_i64")), I64),
    "__ep_map_str_i64_has": lambda p: emit_map_str_word_has("__ep_map_str_i64_has", ptr(mir_struct("_map_str_i64"))),
}

_HELPER_ORDER = [
    "__ep_slice_u8_from_str",
    "__ep_str_from_slice_u8",
    "__ep_str_from_bool",
    "__ep_str_eq",
    "__ep_str_cat",
    "__ep_str_slice",
    "__ep_str_starts_with",
    "__ep_str_get",
    "__ep_str_find",
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
    "__ep_map_str_i64_new",
    "__ep_map_str_i64_get",
    "__ep_map_str_i64_set",
    "__ep_map_str_i64_has",
]


IMPLEMENTED_MIR_HELPERS = tuple(_HELPER_ORDER)


_RUNTIME_STRING_GLOBALS = (
    ("@str.runtime.bool.true", "true"),
    ("@str.runtime.bool.false", "false"),
)


def inject_all_mir_helpers(program: MirProgram) -> None:
    """Inject every implemented MIR helper in deterministic order."""
    implemented = set(IMPLEMENTED_MIR_HELPERS)

    # Remove matching externs so validate() doesn't see duplicate symbols.
    program.externs[:] = [e for e in program.externs if e.name not in implemented]

    global_names = {g.name for g in program.globals}
    for name, text in _RUNTIME_STRING_GLOBALS:
        if name not in global_names:
            program.globals.append(MirGlobal(name, ptr(mir_struct("str")), text))
            global_names.add(name)

    for name in IMPLEMENTED_MIR_HELPERS:
        program.functions.append(_HELPER_EMITTERS[name](program))
