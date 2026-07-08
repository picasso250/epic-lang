"""Lower Epic MIR to structured X64 MachineIR."""

from mir import Br, CondBr, ConstBoolOperand, ConstIntOperand, ConstNullOperand, I8, I64, Ret, SymbolOperand, ValueOperand, VOID
from x64 import I, M, MS, R, LabelRef, Symbol, X64Program
from x64_runtime import append_runtime_helpers, emit_runtime_data, emit_startup_hook_call


ARG_REGS = ["rcx", "rdx", "r8", "r9"]


class MirLowerError(RuntimeError):
    pass


class MirLower:
    def __init__(self, program):
        self.program = program
        self.x64 = X64Program()
        self.value_slots = {}
        self.addr_slots = {}
        self.next_slot = 0
        self.return_label = None
        self.string_globals = {}
        self.global_slots = set()
        self.has_global_init = False
        self.scratch_slots = []
        self.label_counter = 0

    def lower(self):
        self.x64.global_("_start")
        for imp in self.program.imports:
            self.x64.extern(imp.name)
        self.x64.section(".data")
        self.string_globals = emit_runtime_data(self.x64, self.program)
        self.global_slots = {glob.name for glob in self.program.globals if glob.name != "argv" and glob.init is None}
        self.has_global_init = any(fn.name == "__ep_global_init" for fn in self.program.functions)
        self.x64.section(".text")
        for fn in self.program.functions:
            self._lower_function(fn)
        append_runtime_helpers(self.x64)
        return self.x64

    def _lower_function(self, fn):
        self.value_slots = {}
        self.addr_slots = {}
        self.next_slot = 0
        self.return_label = f"{fn.name}.__return"
        self._plan_slots(fn)
        label = "_start" if fn.name == "main" else fn.name
        frame = self._aligned_frame()
        self.x64.label(label)
        self.x64.inst("push", R("rbp"))
        self.x64.inst("mov", R("rbp"), R("rsp"))
        if frame:
            self.x64.inst("sub", R("rsp"), I(frame))
        if fn.name == "main":
            emit_startup_hook_call(self.x64, self.has_global_init)
        for idx, param in enumerate(fn.params):
            if idx < len(ARG_REGS):
                self.x64.inst("mov", M("rbp", self.value_slots[param.name]), R(ARG_REGS[idx]))
            else:
                self.x64.inst("mov", R("rax"), M("rbp", 16 + idx * 8))
                self.x64.inst("mov", M("rbp", self.value_slots[param.name]), R("rax"))
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

    def _plan_slots(self, fn):
        for param in fn.params:
            self.value_slots[param.name] = self._slot()
        for block in fn.blocks:
            for inst in block.instructions:
                if inst.op == "alloca":
                    self.addr_slots[inst.result.name] = self._slot()
                elif inst.result is not None:
                    self.value_slots[inst.result.name] = self._slot()
        self.scratch_slots = [self._slot() for _ in range(8)]

    def _slot(self):
        self.next_slot += 8
        return -self.next_slot

    def _aligned_frame(self):
        return ((self.next_slot + 32 + 15) // 16) * 16

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
            name = operand.value.name
            if name in self.value_slots:
                self.x64.inst("mov", R(reg), M("rbp", self.value_slots[name]))
            elif name in self.addr_slots:
                self.x64.inst("lea", R(reg), M("rbp", self.addr_slots[name]))
            else:
                raise MirLowerError(f"unknown MIR value: {name}")
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
        self.x64.inst("mov", M("rbp", self.value_slots[value.name]), R(reg))

    def _trap_if_zero(self, reg):
        self.x64.inst("test", R(reg), R(reg))
        self.x64.inst("jz", LabelRef("__epx_null_deref"))

    def _addr_slot(self, operand):
        if not isinstance(operand, ValueOperand) or operand.value.name not in self.addr_slots:
            raise MirLowerError("only alloca addresses are supported in first MIR lowering")
        return self.addr_slots[operand.value.name]

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
