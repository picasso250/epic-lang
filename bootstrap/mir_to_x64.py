"""Lower Epic MIR to structured X64 MachineIR."""

from backend_abi import WINAPI_ABI, validate_backend_abi
from mir import Br, CondBr, ConstBoolOperand, ConstIntOperand, ConstNullOperand, I8, I64, Ret, SymbolOperand, ValueOperand, VOID, validate
from x64 import I, M, MS, R, LabelRef, Symbol, X64Program
from mir_prune import prune_unreachable_functions
from mir_runtime_helpers import inject_all_mir_helpers
from x64_runtime import append_runtime_helpers, emit_runtime_data, emit_startup_hook_call


ARG_REGS = ["rcx", "rdx", "r8", "r9"]


class MirLowerError(RuntimeError):
    pass


def prepare_mir_for_x64(program):
    """Apply the x64 backend's MIR preparation contract in one place."""
    inject_all_mir_helpers(program)
    prune_unreachable_functions(program)
    program.retain_referenced_externs()
    validate(program)
    validate_backend_abi(program)
    return program


class MirLower:
    def __init__(self, program):
        self.program = program
        self.x64 = X64Program()
        self.value_slots = []
        self.addr_slots = []
        self.next_slot = 0
        self.return_label = None
        self.string_globals = {}
        self.global_slots = set()
        self.scratch_slots = []
        self.label_counter = 0
        self.temp_value_slots = []
        self.block_local_use_counts = []
        self.reusable_values = []
        self.free_value_slots = []

    def _prepare_program(self):
        self.x64.global_("_start")
        # The x64 runtime itself calls WinAPI; those imports are backend-owned.
        for name in sorted(WINAPI_ABI):
            self.x64.extern(name)
        self.x64.section(".data")
        self.string_globals = emit_runtime_data(self.x64, self.program)
        self.global_slots = {glob.name for glob in self.program.globals if glob.name != "argv" and glob.init is None}
        self.x64.section(".text")

    def lower(self):
        prepare_mir_for_x64(self.program)
        self._prepare_program()
        for fn in self.program.functions:
            self._lower_function(fn)
        append_runtime_helpers(self.x64)
        return self.x64

    def _lower_function(self, fn):
        value_capacity = self._value_capacity(fn)
        self.value_slots = [0] * value_capacity
        self.addr_slots = [0] * value_capacity
        self.next_slot = 0
        self.temp_value_slots = [False] * value_capacity
        self.block_local_use_counts = [0] * value_capacity
        self.reusable_values = [False] * value_capacity
        self.free_value_slots = []
        self.return_label = f"{fn.name}.__return"
        self._plan_slots(fn)
        label = "_start" if fn.name == "main" else fn.name
        frame = self._aligned_frame()
        self.x64.label(label)
        self.x64.inst("push", R("rbp"))
        self.x64.inst("mov", R("rbp"), R("rsp"))
        if frame:
            self._emit_stack_alloc(frame)
        if fn.name == "main":
            emit_startup_hook_call(self.x64)
        for idx, param in enumerate(fn.params):
            if idx < len(ARG_REGS):
                self.x64.inst("mov", M("rbp", self.value_slots[param.id]), R(ARG_REGS[idx]))
            else:
                self.x64.inst("mov", R("rax"), M("rbp", 16 + idx * 8))
                self.x64.inst("mov", M("rbp", self.value_slots[param.id]), R("rax"))
        for block in fn.blocks:
            self.x64.label(self._block_label(fn, block.name))
            for inst in block.instructions:
                self._lower_inst(inst)
            self._lower_term(fn, block.terminator)
        self.x64.label(self.return_label)
        if frame:
            self.x64.inst("add", R("rsp"), I(frame))
        self.x64.inst("pop", R("rbp"))
        self.x64.inst("ret")

    def _emit_stack_alloc(self, size):
        if size < 4096:
            self.x64.inst("sub", R("rsp"), I(size))
            return
        remaining = size
        while remaining > 0:
            step = 4096 if remaining > 4096 else remaining
            self.x64.inst("sub", R("rsp"), I(step))
            self.x64.inst("mov", R("r11"), M("rsp"))
            self.x64.inst("mov", M("rsp"), R("r11"))
            remaining -= step

    def _plan_slots(self, fn):
        for param in fn.params:
            self.value_slots[param.id] = self._slot()
        self._mark_reusable_values(fn)
        for block in fn.blocks:
            self.block_local_use_counts = self._count_block_local_uses(block)
            for inst in block.instructions:
                if inst.op == "alloca":
                    self.addr_slots[inst.result.id] = self._slot()
                    continue
                self._release_operands(inst.operands)
                if inst.result is not None:
                    if self.reusable_values[inst.result.id]:
                        slot = self._reuse_or_alloc_slot()
                        self.temp_value_slots[inst.result.id] = True
                    else:
                        slot = self._slot()
                    self.value_slots[inst.result.id] = slot
                    if self.block_local_use_counts[inst.result.id] == 0:
                        self._release_value(inst.result.id)
            self._release_terminator(block.terminator)
        self.scratch_slots = [self._slot() for _ in range(8)]

    @staticmethod
    def _value_capacity(fn):
        max_id = max((param.id for param in fn.params), default=0)
        for block in fn.blocks:
            for inst in block.instructions:
                if inst.result is not None:
                    max_id = max(max_id, inst.result.id)
        return max_id + 1

    def _mark_reusable_values(self, fn):
        def_blocks = [0] * len(self.value_slots)
        for block_index, block in enumerate(fn.blocks, start=1):
            for inst in block.instructions:
                if inst.result is not None and inst.op != "alloca":
                    def_blocks[inst.result.id] = block_index
                    self.reusable_values[inst.result.id] = True
        for block_index, block in enumerate(fn.blocks, start=1):
            for inst in block.instructions:
                for operand in inst.operands:
                    self._mark_cross_block_operand_use(def_blocks, operand, block_index)
            self._mark_cross_block_terminator_use(def_blocks, block.terminator, block_index)

    def _mark_cross_block_operand_use(self, def_blocks, operand, block_index):
        if not isinstance(operand, ValueOperand):
            return
        value_id = operand.value.id
        if def_blocks[value_id] != 0 and def_blocks[value_id] != block_index:
            self.reusable_values[value_id] = False

    def _mark_cross_block_terminator_use(self, def_blocks, term, block_index):
        if isinstance(term, CondBr):
            self._mark_cross_block_operand_use(def_blocks, term.cond, block_index)
        elif isinstance(term, Ret) and term.value is not None:
            self._mark_cross_block_operand_use(def_blocks, term.value, block_index)

    def _count_block_local_uses(self, block):
        counts = [0] * len(self.value_slots)
        for inst in block.instructions:
            for operand in inst.operands:
                if isinstance(operand, ValueOperand) and self.reusable_values[operand.value.id]:
                    counts[operand.value.id] += 1
        if isinstance(block.terminator, CondBr):
            operand = block.terminator.cond
            if isinstance(operand, ValueOperand) and self.reusable_values[operand.value.id]:
                counts[operand.value.id] += 1
        elif isinstance(block.terminator, Ret) and block.terminator.value is not None:
            operand = block.terminator.value
            if isinstance(operand, ValueOperand) and self.reusable_values[operand.value.id]:
                counts[operand.value.id] += 1
        return counts

    def _reuse_or_alloc_slot(self):
        if self.free_value_slots:
            return self.free_value_slots.pop()
        return self._slot()

    def _release_operands(self, operands):
        for operand in operands:
            if not isinstance(operand, ValueOperand):
                continue
            value_id = operand.value.id
            remaining = self.block_local_use_counts[value_id]
            if remaining <= 0:
                continue
            remaining -= 1
            self.block_local_use_counts[value_id] = remaining
            if remaining == 0:
                self._release_value(value_id)

    def _release_terminator(self, term):
        if isinstance(term, CondBr):
            self._release_operands([term.cond])
        elif isinstance(term, Ret) and term.value is not None:
            self._release_operands([term.value])

    def _release_value(self, value_id):
        if not self.temp_value_slots[value_id]:
            return
        self.temp_value_slots[value_id] = False
        self.free_value_slots.append(self.value_slots[value_id])

    def _slot(self):
        self.next_slot += 8
        return -self.next_slot

    def _aligned_frame(self):
        return ((self.next_slot + 15) // 16) * 16

    def _block_label(self, fn, block_name):
        return f"{fn.name}.{block_name}"

    def _lower_inst(self, inst):
        if inst.op == "alloca":
            return
        if inst.op == "store":
            value, addr = inst.operands
            self._load_operand("rax", value)
            self._load_operand("rcx", addr)
            self._trap_if_zero("rcx")
            self.x64.inst("mov", M("rcx", 0, 1 if value.type == I8 else 8), R("al") if value.type == I8 else R("rax"))
            return
        if inst.op == "load":
            self._load_operand("rax", inst.operands[0])
            self._trap_if_zero("rax")
            if inst.type == I8:
                self.x64.inst("movzx", R("rax"), M("rax", 0, 1))
            else:
                self.x64.inst("mov", R("rax"), M("rax"))
            self._store_result(inst.result, "rax")
            return
        if inst.op == "gep":
            self._lower_gep(inst)
            return
        if inst.op == "ptrtoint":
            self._load_operand("rax", inst.operands[0])
            self._store_result(inst.result, "rax")
            return
        if inst.op in ("add", "sub", "mul", "sdiv", "udiv", "srem", "urem", "and", "or", "xor", "shl", "sar", "shr"):
            self._load_operand("rax", inst.operands[0])
            self._load_operand("rcx", inst.operands[1])
            if inst.op == "add":
                self.x64.inst("add", R("rax"), R("rcx"))
            elif inst.op == "sub":
                self.x64.inst("sub", R("rax"), R("rcx"))
            elif inst.op == "and":
                self.x64.inst("and", R("rax"), R("rcx"))
            elif inst.op == "or":
                self.x64.inst("or", R("rax"), R("rcx"))
            elif inst.op == "xor":
                self.x64.inst("xor", R("rax"), R("rcx"))
            elif inst.op in ("shl", "sar", "shr"):
                self.x64.inst(inst.op, R("rax"), R("cl"))
            elif inst.op == "mul":
                self.x64.inst("imul", R("rax"), R("rcx"))
            elif inst.op in ("sdiv", "srem"):
                self.x64.inst("cqo")
                self.x64.inst("idiv", R("rcx"))
                if inst.op == "srem":
                    self.x64.inst("mov", R("rax"), R("rdx"))
            elif inst.op in ("udiv", "urem"):
                self.x64.inst("xor", R("rdx"), R("rdx"))
                self.x64.inst("div", R("rcx"))
                if inst.op == "urem":
                    self.x64.inst("mov", R("rax"), R("rdx"))
            self._store_result(inst.result, "rax")
            return
        if inst.op == "not":
            self._load_operand("rax", inst.operands[0])
            self.x64.inst("test", R("rax"), R("rax"))
            self.x64.inst("sete", R("al"))
            self.x64.inst("movzx", R("eax"), R("al"))
            self._store_result(inst.result, "rax")
            return
        if inst.op.startswith("icmp."):
            self._load_operand("rax", inst.operands[0])
            self._load_operand("rcx", inst.operands[1])
            self.x64.inst("cmp", R("rax"), R("rcx"))
            cc = {
                "eq": "sete", "ne": "setne",
                "slt": "setl", "sgt": "setg", "sle": "setle", "sge": "setge",
                "ult": "setb", "ugt": "seta", "ule": "setbe", "uge": "setae",
            }[inst.op[5:]]
            self.x64.inst(cc, R("al"))
            self.x64.inst("movzx", R("eax"), R("al"))
            self._store_result(inst.result, "rax")
            return
        if inst.op == "call":
            self._lower_call(inst)
            return
        raise MirLowerError(f"unsupported MIR instruction: {inst.op}")

    def _lower_call(self, inst):
        stack_args = max(0, len(inst.operands) - 4)
        extra = ((stack_args * 8 + 15) // 16) * 16
        frame = 32 + extra
        for idx, operand in enumerate(inst.operands[:4]):
            self._load_operand(ARG_REGS[idx], operand)
        self.x64.inst("sub", R("rsp"), I(frame))
        for idx, operand in enumerate(inst.operands[4:]):
            self._load_operand("rax", operand)
            self.x64.inst("mov", M("rsp", 32 + idx * 8), R("rax"))
        self.x64.inst("call", Symbol(inst.callee))
        self.x64.inst("add", R("rsp"), I(frame))
        if inst.result is not None:
            self._store_result(inst.result, "rax")

    def _lower_term(self, fn, term):
        if isinstance(term, Br):
            self.x64.inst("jmp", LabelRef(self._block_label(fn, term.target)))
        elif isinstance(term, CondBr):
            self._load_operand("rax", term.cond)
            self.x64.inst("test", R("rax"), R("rax"))
            self.x64.inst("jnz", LabelRef(self._block_label(fn, term.then_target)))
            self.x64.inst("jmp", LabelRef(self._block_label(fn, term.else_target)))
        elif isinstance(term, Ret):
            if term.value is not None:
                self._load_operand("rax", term.value)
            if fn.name == "main":
                self.x64.inst("mov", R("rcx"), R("rax") if term.value is not None else I(0))
                self.x64.inst("sub", R("rsp"), I(32))
                self.x64.inst("call", Symbol("ExitProcess"))
            else:
                self.x64.inst("jmp", LabelRef(self.return_label))
        else:
            raise MirLowerError("missing terminator")

    def _load_operand(self, reg, operand):
        if isinstance(operand, ConstBoolOperand):
            self.x64.inst("mov", R(reg), I(1 if operand.value else 0))
        elif isinstance(operand, ConstIntOperand):
            self.x64.inst("mov", R(reg), I(operand.value))
        elif isinstance(operand, ConstNullOperand):
            self.x64.inst("mov", R(reg), I(0))
        elif isinstance(operand, ValueOperand):
            value_id = operand.value.id
            if self.value_slots[value_id] != 0:
                self.x64.inst("mov", R(reg), M("rbp", self.value_slots[value_id]))
            elif self.addr_slots[value_id] != 0:
                self.x64.inst("lea", R(reg), M("rbp", self.addr_slots[value_id]))
            else:
                raise MirLowerError(f"unknown MIR value: {value_id}")
        elif isinstance(operand, SymbolOperand):
            if operand.name == "argv":
                self.x64.inst("mov", R(reg), MS("_argv"))
                return
            if operand.name in self.global_slots:
                self.x64.inst("lea", R(reg), MS(operand.name))
                return
            if operand.name not in self.string_globals:
                raise MirLowerError(f"unsupported symbol operand: {operand.name}")
            header_label, data_label, length = self.string_globals[operand.name]
            self.x64.inst("lea", R("r11"), MS(data_label))
            self.x64.inst("lea", R(reg), MS(header_label))
            self.x64.inst("mov", M(reg), R("r11"))
            self.x64.inst("mov", R("r11"), I(length))
            self.x64.inst("mov", M(reg, 8), R("r11"))
        else:
            raise MirLowerError(f"unsupported operand: {type(operand).__name__}")

    def _store_result(self, value, reg):
        self.x64.inst("mov", M("rbp", self.value_slots[value.id]), R(reg))

    def _trap_if_zero(self, reg):
        self.x64.inst("test", R(reg), R(reg))
        self.x64.inst("jz", LabelRef("__epx_null_deref"))

    def _addr_slot(self, operand):
        if not isinstance(operand, ValueOperand) or self.addr_slots[operand.value.id] == 0:
            raise MirLowerError("only alloca addresses are supported in first MIR lowering")
        return self.addr_slots[operand.value.id]

    def _lower_gep(self, inst):
        base = inst.operands[0]
        self._load_operand("rax", base)
        if not isinstance(base, ConstNullOperand):
            self._trap_if_zero("rax")
        source = inst.type
        indices = inst.operands[1:]
        if source.kind == "struct":
            if len(indices) == 1:
                self._add_scaled_index(indices[0], self._sizeof_type(source))
            elif len(indices) == 2:
                self._add_scaled_index(indices[0], self._sizeof_type(source))
                field_index = indices[1]
                if not isinstance(field_index, ConstIntOperand):
                    raise MirLowerError("struct field gep needs a constant field index")
                self._add_rax_imm(self._field_offset_by_index(source.name, field_index.value))
            else:
                raise MirLowerError("struct gep needs one or two indices")
        elif source.kind == "i8":
            self._add_scaled_index(indices[0], 1)
        elif source.kind in ("i64", "ptr"):
            self._add_scaled_index(indices[0], 8)
        elif source.kind == "array":
            self._add_scaled_index(indices[0], self._sizeof_type(source.elem))
        else:
            raise MirLowerError(f"unsupported gep source type: {source}")
        self._store_result(inst.result, "rax")

    def _add_scaled_index(self, operand, scale):
        if isinstance(operand, ConstIntOperand):
            self._add_rax_imm(operand.value * scale)
            return
        self._load_operand("rcx", operand)
        if scale == 8:
            self._scale_rcx_by_8()
        elif scale != 1:
            raise MirLowerError(f"dynamic gep scale is not supported yet: {scale}")
        self.x64.inst("add", R("rax"), R("rcx"))

    def _add_rax_imm(self, value):
        if value == 0:
            return
        if -128 <= value <= 127:
            self.x64.inst("add", R("rax"), I(value))
            return
        self.x64.inst("mov", R("rcx"), I(value))
        self.x64.inst("add", R("rax"), R("rcx"))

    def _sizeof_type(self, typ):
        if typ.kind == "struct":
            try:
                return self.program.structs[typ.name].size
            except KeyError as exc:
                raise MirLowerError(f"unknown struct layout: {typ.name}") from exc
        if typ.kind == "array":
            return typ.count * self._sizeof_type(typ.elem)
        if typ.kind == "i8":
            return 1
        return 8

    def _field_offset_by_index(self, struct_name, field_index):
        try:
            return self.program.structs[struct_name].field_by_index(field_index).offset
        except (KeyError, IndexError) as exc:
            raise MirLowerError(f"unknown field index {struct_name}.{field_index}") from exc

    def _scale_rcx_by_8(self):
        self.x64.inst("add", R("rcx"), R("rcx"))
        self.x64.inst("add", R("rcx"), R("rcx"))
        self.x64.inst("add", R("rcx"), R("rcx"))


def lower_mir_to_x64(program):
    return MirLower(program).lower()
