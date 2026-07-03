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
        self.scratch_slots = []
        self.label_counter = 0

    def lower(self):
        self.x64.global_("_start")
        for imp in self.program.imports:
            self.x64.extern(imp.name)
        self.x64.section(".data")
        self.string_globals = emit_runtime_data(self.x64, self.program)
        self.x64.section(".text")
        for fn in self.program.functions:
            self._lower_function(fn)
        append_runtime_helpers(self)
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
            emit_startup_hook_call(self.x64)
        for idx, param in enumerate(fn.params):
            if idx >= len(ARG_REGS):
                raise MirLowerError(f"{fn.name}: more than four params are not supported")
            self.x64.inst("mov", M("rbp", self.value_slots[param.name]), R(ARG_REGS[idx]))
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
            self.x64.inst("mov", M("rcx", 0, 1 if value.type == I8 else 8), R("al") if value.type == I8 else R("rax"))
            return
        if inst.op == "load":
            self._load_operand("rax", inst.operands[0])
            if inst.type == I8:
                self.x64.inst("movsx", R("rax"), M("rax", 0, 1))
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
        if inst.op in ("add", "sub", "mul", "div", "mod", "and", "or", "xor", "shl", "sar", "shr"):
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
            elif inst.op in ("div", "mod"):
                self.x64.inst("cqo")
                self.x64.inst("idiv", R("rcx"))
                if inst.op == "mod":
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
            cc = {"eq": "sete", "ne": "setne", "lt": "setl", "gt": "setg", "le": "setle", "ge": "setge"}[inst.op[5:]]
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
            if operand.name == "@argv":
                self.x64.inst("mov", R(reg), MS("_argv"))
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

    def _addr_slot(self, operand):
        if not isinstance(operand, ValueOperand) or operand.value.name not in self.addr_slots:
            raise MirLowerError("only alloca addresses are supported in first MIR lowering")
        return self.addr_slots[operand.value.name]

    def _lower_gep(self, inst):
        self._load_operand("rax", inst.operands[0])
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
                return self.program.structs[typ.name]["size"]
            except KeyError as exc:
                raise MirLowerError(f"unknown struct layout: {typ.name}") from exc
        if typ.kind == "array":
            return typ.count * self._sizeof_type(typ.elem)
        if typ.kind == "i8":
            return 1
        return 8

    def _field_offset_by_index(self, struct_name, field_index):
        try:
            fields = list(self.program.structs[struct_name]["fields"].values())
            return fields[field_index]["offset"]
        except (KeyError, IndexError) as exc:
            raise MirLowerError(f"unknown field index {struct_name}.{field_index}") from exc

    def _scale_rcx_by_8(self):
        self.x64.inst("add", R("rcx"), R("rcx"))
        self.x64.inst("add", R("rcx"), R("rcx"))
        self.x64.inst("add", R("rcx"), R("rcx"))

    def _emit_runtime_helpers(self):
        self._emit_epic_alloc()
        self._emit_epic_arr_qword_new()
        self._emit_epic_arr_qword_push("__epic_arr_i64_push")
        self._emit_epic_arr_qword_push("__epic_arr_ptr_push")
        self._emit_epic_arr_qword_extend()
        self._emit_epic_arr_qword_get("__epic_arr_i64_get", "array_oob")
        self._emit_epic_arr_qword_get("__epic_arr_ptr_get", "array_oob")
        self._emit_arr_i64_set()
        self._emit_map_new()
        self._emit_map_get()
        self._emit_map_set()
        self._emit_map_has()
        self._emit_map_repr()
        self._emit_cstr()
        self._emit_write_file()
        self._emit_read_file()
        self._emit_system_cmd()
        self._emit_argv_init()
        self._emit_str_i64()
        self._emit_print_str()
        self._emit_print_newline()
        self._emit_putc()
        self._emit_array_oob()

    def _data_label(self, name):
        return name.replace("@", "_").replace(".", "_") + "_data"

    def _header_label(self, name):
        return name.replace("@", "_").replace(".", "_") + "_header"

    def _emit_epic_alloc(self):
        x = self.x64
        x.label("__epic_alloc")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("mov", R("r8"), R("rcx"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_epic_arr_qword_new(self):
        x = self.x64
        x.label("__epic_arr_qword_new")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(64))
        x.inst("mov", M("rbp", -8), R("rcx"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), I(24))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -16), R("rax"))
        x.inst("mov", R("r8"), M("rbp", -8))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rcx"), M("rbp", -16))
        x.inst("mov", M("rcx"), R("rax"))
        x.inst("mov", M("rcx", 8), I(0))
        x.inst("mov", R("rdx"), M("rbp", -8))
        x.inst("mov", M("rcx", 16), R("rdx"))
        x.inst("mov", R("rax"), R("rcx"))
        x.inst("add", R("rsp"), I(64))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_epic_arr_qword_push(self, label):
        x = self.x64
        grow = f"{label}.grow"
        store = f"{label}.store"
        copy_loop = f"{label}.copy"
        copy_done = f"{label}.copy_done"
        cap_nonzero = f"{label}.cap_nonzero"
        x.label(label)
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(96))
        x.inst("mov", M("rbp", -8), R("rcx"))
        x.inst("mov", M("rbp", -16), R("rdx"))
        x.inst("mov", R("rax"), M("rcx", 8))
        x.inst("mov", M("rbp", -24), R("rax"))
        x.inst("mov", R("rdx"), M("rcx", 16))
        x.inst("cmp", R("rax"), R("rdx"))
        x.inst("jge", LabelRef(grow))
        x.inst("jmp", LabelRef(store))
        x.label(grow)
        x.inst("test", R("rdx"), R("rdx"))
        x.inst("jnz", LabelRef(cap_nonzero))
        x.inst("mov", R("rdx"), I(2))
        x.label(cap_nonzero)
        x.inst("add", R("rdx"), R("rdx"))
        x.inst("mov", M("rbp", -32), R("rdx"))
        x.inst("mov", R("r8"), R("rdx"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -40), R("rax"))
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("r8"), M("rcx"))
        x.inst("mov", R("r9"), M("rbp", -40))
        x.inst("mov", R("r10"), M("rbp", -24))
        x.label(copy_loop)
        x.inst("test", R("r10"), R("r10"))
        x.inst("jz", LabelRef(copy_done))
        x.inst("mov", R("rax"), M("r8"))
        x.inst("mov", M("r9"), R("rax"))
        x.inst("add", R("r8"), I(8))
        x.inst("add", R("r9"), I(8))
        x.inst("dec", R("r10"))
        x.inst("jmp", LabelRef(copy_loop))
        x.label(copy_done)
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("rax"), M("rbp", -40))
        x.inst("mov", M("rcx"), R("rax"))
        x.inst("mov", R("rax"), M("rbp", -32))
        x.inst("mov", M("rcx", 16), R("rax"))
        x.label(store)
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("rax"), M("rcx"))
        x.inst("mov", R("r8"), M("rbp", -24))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("rax"), R("r8"))
        x.inst("mov", R("rdx"), M("rbp", -16))
        x.inst("mov", M("rax"), R("rdx"))
        x.inst("mov", R("rax"), M("rbp", -24))
        x.inst("add", R("rax"), I(1))
        x.inst("mov", M("rcx", 8), R("rax"))
        x.inst("add", R("rsp"), I(96))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_epic_arr_qword_extend(self):
        x = self.x64
        label = "__epic_arr_qword_extend"
        grow = f"{label}.grow"
        have_cap = f"{label}.have_cap"
        cap_loop = f"{label}.cap_loop"
        cap_ready = f"{label}.cap_ready"
        copy_old = f"{label}.copy_old"
        swap = f"{label}.swap"
        copy_src = f"{label}.copy_src"
        finish = f"{label}.finish"
        x.label(label)
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(96))
        x.inst("mov", M("rbp", -8), R("rcx"))
        x.inst("mov", M("rbp", -16), R("rdx"))
        x.inst("mov", R("rax"), M("rdx"))
        x.inst("mov", M("rbp", -24), R("rax"))
        x.inst("mov", R("rax"), M("rdx", 8))
        x.inst("mov", M("rbp", -32), R("rax"))
        x.inst("mov", R("rax"), M("rcx", 8))
        x.inst("mov", M("rbp", -40), R("rax"))
        x.inst("mov", R("r8"), M("rbp", -32))
        x.inst("add", R("rax"), R("r8"))
        x.inst("mov", M("rbp", -48), R("rax"))
        x.inst("mov", R("rdx"), M("rcx", 16))
        x.inst("cmp", R("rdx"), R("rax"))
        x.inst("jl", LabelRef(grow))
        x.inst("jmp", LabelRef(have_cap))
        x.label(grow)
        x.inst("test", R("rdx"), R("rdx"))
        x.inst("jnz", LabelRef(cap_loop))
        x.inst("mov", R("rdx"), I(2))
        x.label(cap_loop)
        x.inst("mov", R("rax"), M("rbp", -48))
        x.inst("cmp", R("rdx"), R("rax"))
        x.inst("jge", LabelRef(cap_ready))
        x.inst("add", R("rdx"), R("rdx"))
        x.inst("jmp", LabelRef(cap_loop))
        x.label(cap_ready)
        x.inst("mov", M("rbp", -56), R("rdx"))
        x.inst("mov", R("r8"), R("rdx"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -64), R("rax"))
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("r8"), M("rcx"))
        x.inst("mov", R("r9"), M("rbp", -64))
        x.inst("mov", R("r10"), M("rbp", -40))
        x.label(copy_old)
        x.inst("test", R("r10"), R("r10"))
        x.inst("jz", LabelRef(swap))
        x.inst("mov", R("rax"), M("r8"))
        x.inst("mov", M("r9"), R("rax"))
        x.inst("add", R("r8"), I(8))
        x.inst("add", R("r9"), I(8))
        x.inst("dec", R("r10"))
        x.inst("jmp", LabelRef(copy_old))
        x.label(swap)
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("rax"), M("rbp", -64))
        x.inst("mov", M("rcx"), R("rax"))
        x.inst("mov", R("rax"), M("rbp", -56))
        x.inst("mov", M("rcx", 16), R("rax"))
        x.label(have_cap)
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("r8"), M("rcx"))
        x.inst("mov", R("rax"), M("rbp", -40))
        x.inst("add", R("rax"), R("rax"))
        x.inst("add", R("rax"), R("rax"))
        x.inst("add", R("rax"), R("rax"))
        x.inst("add", R("r8"), R("rax"))
        x.inst("mov", R("r9"), M("rbp", -24))
        x.inst("mov", R("r10"), M("rbp", -32))
        x.label(copy_src)
        x.inst("test", R("r10"), R("r10"))
        x.inst("jz", LabelRef(finish))
        x.inst("mov", R("rax"), M("r9"))
        x.inst("mov", M("r8"), R("rax"))
        x.inst("add", R("r8"), I(8))
        x.inst("add", R("r9"), I(8))
        x.inst("dec", R("r10"))
        x.inst("jmp", LabelRef(copy_src))
        x.label(finish)
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("rax"), M("rbp", -48))
        x.inst("mov", M("rcx", 8), R("rax"))
        x.inst("add", R("rsp"), I(96))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_epic_arr_qword_get(self, label, oob_label):
        x = self.x64
        x.label(label)
        x.inst("cmp", R("rdx"), I(0))
        x.inst("jl", LabelRef(oob_label))
        x.inst("mov", R("r8"), M("rcx", 8))
        x.inst("cmp", R("rdx"), R("r8"))
        x.inst("jge", LabelRef(oob_label))
        x.inst("mov", R("rax"), M("rcx"))
        x.inst("mov", R("r8"), R("rdx"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("r8"), R("r8"))
        x.inst("add", R("rax"), R("r8"))
        x.inst("mov", R("rax"), M("rax"))
        x.inst("ret")

    def _emit_arr_i64_set(self):
        x = self.x64
        x.label("arr_i64_set")
        x.inst("cmp", R("rdx"), I(0))
        x.inst("jl", LabelRef("arr_i64_oob"))
        x.inst("mov", R("r10"), M("rcx", 8))
        x.inst("cmp", R("rdx"), R("r10"))
        x.inst("jge", LabelRef("arr_i64_oob"))
        x.inst("mov", R("rax"), M("rcx"))
        x.inst("mov", R("r10"), R("rdx"))
        x.inst("add", R("r10"), R("r10"))
        x.inst("add", R("r10"), R("r10"))
        x.inst("add", R("r10"), R("r10"))
        x.inst("add", R("rax"), R("r10"))
        x.inst("mov", M("rax"), R("r8"))
        x.inst("ret")
        x.label("arr_i64_oob")
        x.inst("mov", R("rcx"), I(1))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("ExitProcess"))

    def _map_entry_addr(self, index_reg="r9"):
        x = self.x64
        x.inst("mov", R("rax"), R(index_reg))
        x.inst("add", R("rax"), R("rax"))
        x.inst("add", R("rax"), R("rax"))
        x.inst("add", R("rax"), R("rax"))
        x.inst("mov", R("r10"), R(index_reg))
        x.inst("add", R("r10"), R("r10"))
        x.inst("add", R("r10"), R("r10"))
        x.inst("add", R("r10"), R("r10"))
        x.inst("add", R("r10"), R("r10"))
        x.inst("add", R("rax"), R("r10"))
        x.inst("mov", R("r11"), M("rbp", -8))
        x.inst("mov", R("r11"), M("r11"))
        x.inst("add", R("r11"), R("rax"))

    def _emit_map_new(self):
        x = self.x64
        x.label("map_new")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(64))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), I(24))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -8), R("rax"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), I(192))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", M("rcx"), R("rax"))
        x.inst("mov", R("rdx"), I(0))
        x.inst("mov", M("rcx", 8), R("rdx"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", M("rcx", 16), R("rdx"))
        x.inst("mov", R("rax"), R("rcx"))
        x.inst("add", R("rsp"), I(64))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_map_get(self):
        x = self.x64
        x.label("map_get")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(32))
        x.inst("mov", M("rbp", -8), R("rcx"))
        x.inst("mov", M("rbp", -16), R("rdx"))
        x.inst("mov", R("r8"), M("rcx", 8))
        x.inst("mov", R("r9"), I(0))
        x.label("map_get.loop")
        x.inst("cmp", R("r9"), R("r8"))
        x.inst("jge", LabelRef("map_get.miss"))
        self._map_entry_addr("r9")
        x.inst("mov", R("rax"), M("r11", 16))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jz", LabelRef("map_get.next"))
        x.inst("mov", R("rax"), M("r11"))
        x.inst("mov", R("rcx"), M("rbp", -16))
        x.inst("cmp", R("rax"), R("rcx"))
        x.inst("jz", LabelRef("map_get.found"))
        x.label("map_get.next")
        x.inst("add", R("r9"), I(1))
        x.inst("jmp", LabelRef("map_get.loop"))
        x.label("map_get.found")
        x.inst("mov", R("rax"), M("r11", 8))
        x.inst("jmp", LabelRef("map_get.done"))
        x.label("map_get.miss")
        x.inst("mov", R("rax"), I(0))
        x.label("map_get.done")
        x.inst("add", R("rsp"), I(32))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_map_set(self):
        x = self.x64
        x.label("map_set")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(48))
        x.inst("mov", M("rbp", -8), R("rcx"))
        x.inst("mov", M("rbp", -16), R("rdx"))
        x.inst("mov", M("rbp", -24), R("r8"))
        x.inst("mov", R("r8"), M("rcx", 8))
        x.inst("mov", R("r9"), I(0))
        x.label("map_set.loop")
        x.inst("cmp", R("r9"), R("r8"))
        x.inst("jge", LabelRef("map_set.insert"))
        self._map_entry_addr("r9")
        x.inst("mov", R("rax"), M("r11", 16))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jz", LabelRef("map_set.next"))
        x.inst("mov", R("rax"), M("r11"))
        x.inst("mov", R("rcx"), M("rbp", -16))
        x.inst("cmp", R("rax"), R("rcx"))
        x.inst("jz", LabelRef("map_set.update"))
        x.label("map_set.next")
        x.inst("add", R("r9"), I(1))
        x.inst("jmp", LabelRef("map_set.loop"))
        x.label("map_set.update")
        x.inst("mov", R("rax"), M("rbp", -24))
        x.inst("mov", M("r11", 8), R("rax"))
        x.inst("jmp", LabelRef("map_set.done"))
        x.label("map_set.insert")
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("r9"), M("rcx", 8))
        self._map_entry_addr("r9")
        x.inst("mov", R("rax"), M("rbp", -16))
        x.inst("mov", M("r11"), R("rax"))
        x.inst("mov", R("rax"), M("rbp", -24))
        x.inst("mov", M("r11", 8), R("rax"))
        x.inst("mov", M("r11", 16), I(1))
        x.inst("add", R("r9"), I(1))
        x.inst("mov", M("rcx", 8), R("r9"))
        x.label("map_set.done")
        x.inst("add", R("rsp"), I(48))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_map_has(self):
        x = self.x64
        x.label("map_has")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(32))
        x.inst("mov", M("rbp", -8), R("rcx"))
        x.inst("mov", M("rbp", -16), R("rdx"))
        x.inst("mov", R("r8"), M("rcx", 8))
        x.inst("mov", R("r9"), I(0))
        x.label("map_has.loop")
        x.inst("cmp", R("r9"), R("r8"))
        x.inst("jge", LabelRef("map_has.no"))
        self._map_entry_addr("r9")
        x.inst("mov", R("rax"), M("r11", 16))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jz", LabelRef("map_has.next"))
        x.inst("mov", R("rax"), M("r11"))
        x.inst("mov", R("rcx"), M("rbp", -16))
        x.inst("cmp", R("rax"), R("rcx"))
        x.inst("jz", LabelRef("map_has.yes"))
        x.label("map_has.next")
        x.inst("add", R("r9"), I(1))
        x.inst("jmp", LabelRef("map_has.loop"))
        x.label("map_has.yes")
        x.inst("mov", R("rax"), I(1))
        x.inst("jmp", LabelRef("map_has.done"))
        x.label("map_has.no")
        x.inst("mov", R("rax"), I(0))
        x.label("map_has.done")
        x.inst("add", R("rsp"), I(32))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_map_repr(self):
        x = self.x64
        x.label("map_repr")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(96))
        x.inst("mov", M("rbp", -8), R("rcx"))
        self._runtime_string("rax", "_map_repr_prefix")
        x.inst("mov", M("rbp", -16), R("rax"))
        x.inst("mov", M("rbp", -24), I(0))
        x.label("map_repr.loop")
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("rdx"), M("rcx", 8))
        x.inst("mov", R("r9"), M("rbp", -24))
        x.inst("cmp", R("r9"), R("rdx"))
        x.inst("jge", LabelRef("map_repr.close"))
        x.inst("test", R("r9"), R("r9"))
        x.inst("jz", LabelRef("map_repr.entry"))
        self._append_runtime_string(-16, "_map_repr_sep")
        x.label("map_repr.entry")
        x.inst("mov", R("r9"), M("rbp", -24))
        self._map_entry_addr("r9")
        x.inst("mov", R("rax"), M("r11"))
        x.inst("mov", M("rbp", -32), R("rax"))
        x.inst("mov", R("rax"), M("r11", 8))
        x.inst("mov", M("rbp", -40), R("rax"))
        self._append_runtime_string(-16, "_map_repr_quote")
        self._append_reg_string(-16, "qword", -32)
        self._append_runtime_string(-16, "_map_repr_quote")
        self._append_runtime_string(-16, "_map_repr_colon")
        x.inst("mov", R("rcx"), M("rbp", -40))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("str_i64"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -48), R("rax"))
        self._append_reg_string(-16, "qword", -48)
        x.inst("mov", R("rax"), M("rbp", -24))
        x.inst("add", R("rax"), I(1))
        x.inst("mov", M("rbp", -24), R("rax"))
        x.inst("jmp", LabelRef("map_repr.loop"))
        x.label("map_repr.close")
        self._append_runtime_string(-16, "_map_repr_close")
        x.inst("mov", R("rax"), M("rbp", -16))
        x.inst("add", R("rsp"), I(96))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _runtime_string(self, reg, name):
        self.x64.inst("lea", R("r11"), MS(f"{name}_data"))
        self.x64.inst("lea", R(reg), MS(f"{name}_header"))
        self.x64.inst("mov", M(reg), R("r11"))
        length = {
            "_map_repr_prefix": 12,
            "_map_repr_close": 1,
            "_map_repr_sep": 2,
            "_map_repr_colon": 2,
            "_map_repr_quote": 1,
        }[name]
        self.x64.inst("mov", R("r11"), I(length))
        self.x64.inst("mov", M(reg, 8), R("r11"))

    def _append_runtime_string(self, dst_slot, name):
        self.x64.inst("mov", R("rcx"), M("rbp", dst_slot))
        self._runtime_string("rdx", name)
        self.x64.inst("sub", R("rsp"), I(32))
        self.x64.inst("call", Symbol("str_cat"))
        self.x64.inst("add", R("rsp"), I(32))
        self.x64.inst("mov", M("rbp", dst_slot), R("rax"))

    def _append_reg_string(self, dst_slot, _unused, src_slot):
        self.x64.inst("mov", R("rcx"), M("rbp", dst_slot))
        self.x64.inst("mov", R("rdx"), M("rbp", src_slot))
        self.x64.inst("sub", R("rsp"), I(32))
        self.x64.inst("call", Symbol("str_cat"))
        self.x64.inst("add", R("rsp"), I(32))
        self.x64.inst("mov", M("rbp", dst_slot), R("rax"))

    def _emit_cstr(self):
        x = self.x64
        x.label("__epic_cstr")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(96))
        x.inst("mov", M("rbp", -8), R("rcx"))
        x.inst("mov", M("rbp", -16), R("rdx"))
        x.inst("test", R("rcx"), R("rcx"))
        x.inst("jz", LabelRef("__epic_cstr.fail"))
        x.inst("mov", R("r8"), M("rcx"))
        x.inst("test", R("r8"), R("r8"))
        x.inst("jz", LabelRef("__epic_cstr.fail"))
        x.inst("mov", R("r9"), M("rcx", 8))
        x.inst("cmp", R("r9"), I(0))
        x.inst("jl", LabelRef("__epic_cstr.fail"))
        x.inst("mov", R("r10"), I(0))
        x.label("__epic_cstr.loop")
        x.inst("cmp", R("r10"), R("r9"))
        x.inst("jge", LabelRef("__epic_cstr.tail"))
        x.inst("mov", R("r11"), R("r8"))
        x.inst("add", R("r11"), R("r10"))
        x.inst("movsx", R("rax"), M("r11", 0, 1))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jz", LabelRef("__epic_cstr.fail"))
        x.inst("add", R("r10"), I(1))
        x.inst("jmp", LabelRef("__epic_cstr.loop"))
        x.label("__epic_cstr.tail")
        x.inst("mov", R("r11"), R("r8"))
        x.inst("add", R("r11"), R("r9"))
        x.inst("movsx", R("rax"), M("r11", 0, 1))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jnz", LabelRef("__epic_cstr.fail"))
        x.inst("mov", R("rax"), R("r8"))
        x.inst("add", R("rsp"), I(96))
        x.inst("pop", R("rbp"))
        x.inst("ret")
        x.label("__epic_cstr.fail")
        x.inst("mov", R("rcx"), I(-11))
        x.inst("call", Symbol("GetStdHandle"))
        x.inst("mov", M("rbp", -24), R("rax"))
        x.inst("mov", R("rcx"), R("rax"))
        x.inst("lea", R("rdx"), MS("_cstr_panic_prefix"))
        x.inst("mov", R("r8"), I(11))
        x.inst("lea", R("r9"), MS("_written"))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("WriteFile"))
        x.inst("mov", R("rcx"), M("rbp", -16))
        x.inst("call", Symbol("str_i64"))
        x.inst("mov", R("rcx"), R("rax"))
        x.inst("call", Symbol("print_str"))
        x.inst("mov", R("rcx"), M("rbp", -24))
        x.inst("lea", R("rdx"), MS("_cstr_panic_suffix"))
        x.inst("mov", R("r8"), I(14))
        x.inst("lea", R("r9"), MS("_written"))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("WriteFile"))
        x.inst("mov", R("rcx"), M("rbp", -24))
        x.inst("lea", R("rdx"), MS("_newline"))
        x.inst("mov", R("r8"), I(1))
        x.inst("lea", R("r9"), MS("_written"))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("WriteFile"))
        x.inst("mov", R("rcx"), I(1))
        x.inst("call", Symbol("ExitProcess"))

    def _emit_write_file(self):
        x = self.x64
        x.label("write_file")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(96))
        x.inst("mov", M("rbp", -56), R("rdx"))
        x.inst("mov", R("rdx"), R("r8"))
        x.inst("call", Symbol("__epic_cstr"))
        x.inst("mov", M("rbp", -8), R("rax"))
        x.inst("mov", R("rdx"), M("rbp", -56))
        x.inst("mov", R("rax"), M("rdx"))
        x.inst("mov", M("rbp", -16), R("rax"))
        x.inst("mov", R("rax"), M("rdx", 8))
        x.inst("mov", M("rbp", -24), R("rax"))
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("rdx"), I(0x40000000))
        x.inst("mov", R("r8"), I(0))
        x.inst("mov", R("r9"), I(0))
        x.inst("sub", R("rsp"), I(56))
        x.inst("mov", M("rsp", 32), I(2))
        x.inst("mov", M("rsp", 40), I(0x80))
        x.inst("mov", M("rsp", 48), I(0))
        x.inst("call", Symbol("CreateFileA"))
        x.inst("add", R("rsp"), I(56))
        x.inst("mov", R("rcx"), I(-1))
        x.inst("cmp", R("rax"), R("rcx"))
        x.inst("jz", LabelRef("write_file.fail"))
        x.inst("mov", M("rbp", -32), R("rax"))
        x.inst("mov", R("rcx"), M("rbp", -32))
        x.inst("mov", R("rdx"), M("rbp", -16))
        x.inst("mov", R("r8"), M("rbp", -24))
        x.inst("lea", R("r9"), M("rbp", -40))
        x.inst("mov", M("rbp", -40), I(0))
        x.inst("sub", R("rsp"), I(40))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("WriteFile"))
        x.inst("add", R("rsp"), I(40))
        x.inst("mov", R("rcx"), M("rbp", -32))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("CloseHandle"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rax"), M("rbp", -40))
        x.inst("jmp", LabelRef("write_file.done"))
        x.label("write_file.fail")
        x.inst("mov", R("rax"), I(-1))
        x.label("write_file.done")
        x.inst("add", R("rsp"), I(96))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_read_file(self):
        x = self.x64
        x.label("read_file")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(112))
        x.inst("call", Symbol("__epic_cstr"))
        x.inst("mov", M("rbp", -8), R("rax"))
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", R("rdx"), I(0x80000000))
        x.inst("mov", R("r8"), I(1))
        x.inst("mov", R("r9"), I(0))
        x.inst("sub", R("rsp"), I(56))
        x.inst("mov", M("rsp", 32), I(3))
        x.inst("mov", M("rsp", 40), I(0x80))
        x.inst("mov", M("rsp", 48), I(0))
        x.inst("call", Symbol("CreateFileA"))
        x.inst("add", R("rsp"), I(56))
        x.inst("mov", R("rcx"), I(-1))
        x.inst("cmp", R("rax"), R("rcx"))
        x.inst("jz", LabelRef("read_file.empty"))
        x.inst("mov", M("rbp", -16), R("rax"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), I(24))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -56), R("rax"))
        x.inst("mov", R("rcx"), M("rbp", -16))
        x.inst("mov", R("rdx"), I(0))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("GetFileSize"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -24), R("rax"))
        x.inst("mov", M("rbp", -64), R("rax"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), M("rbp", -64))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -32), R("rax"))
        x.inst("mov", R("rcx"), M("rbp", -16))
        x.inst("mov", R("rdx"), M("rbp", -32))
        x.inst("mov", R("r8"), M("rbp", -24))
        x.inst("lea", R("r9"), M("rbp", -40))
        x.inst("mov", M("rbp", -40), I(0))
        x.inst("sub", R("rsp"), I(40))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("ReadFile"))
        x.inst("add", R("rsp"), I(40))
        x.inst("mov", R("rcx"), M("rbp", -16))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("CloseHandle"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rcx"), M("rbp", -56))
        x.inst("mov", R("rax"), M("rbp", -32))
        x.inst("mov", M("rcx"), R("rax"))
        x.inst("mov", R("rax"), M("rbp", -40))
        x.inst("mov", M("rcx", 8), R("rax"))
        x.inst("mov", R("rax"), M("rbp", -64))
        x.inst("mov", M("rcx", 16), R("rax"))
        x.inst("mov", R("rax"), R("rcx"))
        x.inst("jmp", LabelRef("read_file.done"))
        x.label("read_file.empty")
        x.inst("mov", R("rcx"), I(0))
        x.inst("call", Symbol("new_arr_i8"))
        x.label("read_file.done")
        x.inst("add", R("rsp"), I(112))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_system_cmd(self):
        x = self.x64
        x.label("system_cmd")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(272))
        x.inst("call", Symbol("__epic_cstr"))
        x.inst("mov", M("rbp", -16), R("rax"))
        x.inst("mov", R("rax"), I(0))
        x.inst("mov", M("rbp", -8), R("rax"))
        for off in range(96, 224, 8):
            x.inst("mov", M("rsp", off), I(0))
        x.inst("mov", M("rsp", 96), I(104))
        x.inst("mov", R("rcx"), I(0))
        x.inst("mov", R("rdx"), M("rbp", -16))
        x.inst("mov", R("r8"), I(0))
        x.inst("mov", R("r9"), I(0))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("mov", M("rsp", 40), I(0))
        x.inst("mov", M("rsp", 48), I(0))
        x.inst("mov", M("rsp", 56), I(0))
        x.inst("lea", R("rax"), M("rsp", 96))
        x.inst("mov", M("rsp", 64), R("rax"))
        x.inst("lea", R("rax"), M("rsp", 200))
        x.inst("mov", M("rsp", 72), R("rax"))
        x.inst("call", Symbol("CreateProcessA"))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jnz", LabelRef("system_cmd.ok"))
        x.inst("mov", R("rax"), I(-1))
        x.inst("jmp", LabelRef("system_cmd.done"))
        x.label("system_cmd.ok")
        x.inst("mov", R("rcx"), M("rsp", 200))
        x.inst("mov", R("rdx"), I(-1))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("WaitForSingleObject"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rcx"), M("rsp", 200))
        x.inst("lea", R("rdx"), M("rbp", -8))
        x.inst("mov", M("rbp", -8), I(0))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("GetExitCodeProcess"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rcx"), M("rsp", 200))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("CloseHandle"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rcx"), M("rsp", 208))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("CloseHandle"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rax"), M("rbp", -8))
        x.label("system_cmd.done")
        x.inst("add", R("rsp"), I(272))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_argv_init(self):
        x = self.x64
        x.label("argv_init")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(128))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("GetCommandLineA"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rsi"), R("rax"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), I(24))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -8), R("rax"))
        x.inst("mov", R("rcx"), I(0))
        x.inst("mov", M("rax", 8), R("rcx"))
        x.inst("mov", R("rcx"), I(16))
        x.inst("mov", M("rax", 16), R("rcx"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), I(128))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rcx"), M("rbp", -8))
        x.inst("mov", M("rcx"), R("rax"))
        x.label("argv_init.skip_ws")
        x.inst("movsx", R("rax"), M("rsi", 0, 1))
        x.inst("mov", R("rcx"), I(0))
        x.inst("cmp", R("rax"), R("rcx"))
        x.inst("jz", LabelRef("argv_init.done"))
        for value in (32, 9, 13, 10):
            x.inst("mov", R("rcx"), I(value))
            x.inst("cmp", R("rax"), R("rcx"))
            x.inst("jz", LabelRef("argv_init.advance_ws"))
        x.inst("jmp", LabelRef("argv_init.arg_start"))
        x.label("argv_init.advance_ws")
        x.inst("add", R("rsi"), I(1))
        x.inst("jmp", LabelRef("argv_init.skip_ws"))
        x.label("argv_init.arg_start")
        x.inst("mov", R("r11"), I(0))
        x.inst("mov", R("rcx"), I(34))
        x.inst("cmp", R("rax"), R("rcx"))
        x.inst("jnz", LabelRef("argv_init.start_plain"))
        x.inst("mov", R("r11"), I(1))
        x.inst("add", R("rsi"), I(1))
        x.label("argv_init.start_plain")
        x.inst("mov", M("rbp", -24), R("rsi"))
        x.inst("mov", R("r10"), I(0))
        x.label("argv_init.scan")
        x.inst("movsx", R("rax"), M("rsi", 0, 1))
        x.inst("mov", R("rcx"), I(0))
        x.inst("cmp", R("rax"), R("rcx"))
        x.inst("jz", LabelRef("argv_init.store"))
        x.inst("test", R("r11"), R("r11"))
        x.inst("jnz", LabelRef("argv_init.scan_quoted"))
        for value in (32, 9, 13, 10):
            x.inst("mov", R("rcx"), I(value))
            x.inst("cmp", R("rax"), R("rcx"))
            x.inst("jz", LabelRef("argv_init.store"))
        x.inst("jmp", LabelRef("argv_init.take"))
        x.label("argv_init.scan_quoted")
        x.inst("mov", R("rcx"), I(34))
        x.inst("cmp", R("rax"), R("rcx"))
        x.inst("jz", LabelRef("argv_init.store_quoted"))
        x.label("argv_init.take")
        x.inst("add", R("rsi"), I(1))
        x.inst("add", R("r10"), I(1))
        x.inst("jmp", LabelRef("argv_init.scan"))
        x.label("argv_init.store_quoted")
        x.inst("add", R("rsi"), I(1))
        x.label("argv_init.store")
        x.inst("mov", M("rbp", -32), R("rsi"))
        x.inst("mov", M("rbp", -40), R("r10"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), I(16))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", R("rcx"), M("rbp", -24))
        x.inst("mov", M("rax"), R("rcx"))
        x.inst("mov", R("rcx"), M("rbp", -40))
        x.inst("mov", M("rax", 8), R("rcx"))
        x.inst("mov", R("rdx"), M("rbp", -8))
        x.inst("mov", R("rcx"), M("rdx", 8))
        x.inst("mov", R("r8"), M("rdx"))
        x.inst("mov", R("r9"), R("rcx"))
        x.inst("add", R("r9"), R("r9"))
        x.inst("add", R("r9"), R("r9"))
        x.inst("add", R("r9"), R("r9"))
        x.inst("add", R("r8"), R("r9"))
        x.inst("mov", M("r8"), R("rax"))
        x.inst("add", R("rcx"), I(1))
        x.inst("mov", M("rdx", 8), R("rcx"))
        x.inst("mov", R("rsi"), M("rbp", -32))
        x.inst("jmp", LabelRef("argv_init.skip_ws"))
        x.label("argv_init.done")
        x.inst("mov", R("rax"), M("rbp", -8))
        x.inst("add", R("rsp"), I(128))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_str_i64(self):
        x = self.x64
        x.label("str_i64")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(64))
        x.inst("lea", R("r10"), MS("_str_i64_buf"))
        x.inst("add", R("r10"), I(31))
        x.inst("mov", M("r10", 0, 1), I(0))
        x.inst("mov", R("r11"), I(0))
        x.inst("mov", R("rax"), R("rcx"))
        x.inst("mov", R("r8"), I(0))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jns", LabelRef("str_i64.positive"))
        x.inst("neg", R("rax"))
        x.inst("mov", R("r8"), I(1))
        x.label("str_i64.positive")
        x.inst("test", R("rax"), R("rax"))
        x.inst("jnz", LabelRef("str_i64.loop"))
        x.inst("dec", R("r10"))
        x.inst("mov", M("r10", 0, 1), I(48))
        x.inst("inc", R("r11"))
        x.inst("jmp", LabelRef("str_i64.digits_done"))
        x.label("str_i64.loop")
        x.inst("xor", R("rdx"), R("rdx"))
        x.inst("mov", R("rcx"), I(10))
        x.inst("div", R("rcx"))
        x.inst("add", R("dl"), I(48))
        x.inst("dec", R("r10"))
        x.inst("mov", M("r10", 0, 1), R("dl"))
        x.inst("inc", R("r11"))
        x.inst("test", R("rax"), R("rax"))
        x.inst("jnz", LabelRef("str_i64.loop"))
        x.label("str_i64.digits_done")
        x.inst("test", R("r8"), R("r8"))
        x.inst("jz", LabelRef("str_i64.finish"))
        x.inst("dec", R("r10"))
        x.inst("mov", M("r10", 0, 1), I(45))
        x.inst("inc", R("r11"))
        x.label("str_i64.finish")
        x.inst("mov", M("rbp", -8), R("r10"))
        x.inst("mov", M("rbp", -16), R("r11"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), I(16))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -24), R("rax"))
        x.inst("mov", R("rcx"), MS("_heap"))
        x.inst("mov", R("rdx"), I(8))
        x.inst("mov", R("r8"), M("rbp", -16))
        x.inst("add", R("r8"), I(1))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("HeapAlloc"))
        x.inst("add", R("rsp"), I(32))
        x.inst("mov", M("rbp", -32), R("rax"))
        x.inst("mov", R("rcx"), M("rbp", -24))
        x.inst("mov", M("rcx"), R("rax"))
        x.inst("mov", R("rdx"), M("rbp", -16))
        x.inst("mov", M("rcx", 8), R("rdx"))
        x.inst("mov", R("rsi"), M("rbp", -8))
        x.inst("mov", R("rdi"), M("rbp", -32))
        x.label("str_i64.copy")
        x.inst("test", R("rdx"), R("rdx"))
        x.inst("jz", LabelRef("str_i64.copy_done"))
        x.inst("movsx", R("rax"), M("rsi", 0, 1))
        x.inst("mov", M("rdi", 0, 1), R("al"))
        x.inst("add", R("rsi"), I(1))
        x.inst("add", R("rdi"), I(1))
        x.inst("dec", R("rdx"))
        x.inst("jmp", LabelRef("str_i64.copy"))
        x.label("str_i64.copy_done")
        x.inst("mov", M("rdi", 0, 1), I(0))
        x.inst("mov", R("rax"), M("rbp", -24))
        x.inst("add", R("rsp"), I(64))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_print_str(self):
        x = self.x64
        x.label("print_str")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(48))
        x.inst("mov", M("rbp", -8), R("rcx"))
        x.inst("mov", R("rcx"), I(-11))
        x.inst("call", Symbol("GetStdHandle"))
        x.inst("mov", R("rcx"), R("rax"))
        x.inst("mov", R("rax"), M("rbp", -8))
        x.inst("mov", R("rdx"), M("rax"))
        x.inst("mov", R("r8"), M("rax", 8))
        x.inst("lea", R("r9"), MS("_written"))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("WriteFile"))
        x.inst("add", R("rsp"), I(48))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_print_newline(self):
        x = self.x64
        x.label("print_newline")
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(48))
        x.inst("mov", R("rcx"), I(-11))
        x.inst("call", Symbol("GetStdHandle"))
        x.inst("mov", R("rcx"), R("rax"))
        x.inst("lea", R("rdx"), MS("_newline"))
        x.inst("mov", R("r8"), I(1))
        x.inst("lea", R("r9"), MS("_written"))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("WriteFile"))
        x.inst("add", R("rsp"), I(48))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_putc(self):
        x = self.x64
        x.label("putc")
        x.inst("mov", R("rax"), R("rcx"))
        x.inst("mov", MS("_putc_buf", 1), R("al"))
        x.inst("push", R("rbp"))
        x.inst("mov", R("rbp"), R("rsp"))
        x.inst("sub", R("rsp"), I(48))
        x.inst("mov", R("rcx"), I(-11))
        x.inst("call", Symbol("GetStdHandle"))
        x.inst("mov", R("rcx"), R("rax"))
        x.inst("lea", R("rdx"), MS("_putc_buf", 1))
        x.inst("mov", R("r8"), I(1))
        x.inst("lea", R("r9"), MS("_written"))
        x.inst("mov", M("rsp", 32), I(0))
        x.inst("call", Symbol("WriteFile"))
        x.inst("add", R("rsp"), I(48))
        x.inst("pop", R("rbp"))
        x.inst("ret")

    def _emit_array_oob(self):
        x = self.x64
        x.label("array_oob")
        x.inst("mov", R("rcx"), I(1))
        x.inst("sub", R("rsp"), I(32))
        x.inst("call", Symbol("ExitProcess"))


def lower_mir_to_x64(program):
    return MirLower(program).lower()
